#!/usr/bin/env python3
"""Standalone regression checks for Windows release verification."""

from __future__ import annotations

import copy
import hashlib
import tempfile
from pathlib import Path

from windows_release_verification import (
    ReleaseVerificationError,
    find_release_asset,
    parse_osslsigncode_output,
    parse_sha256_sidecar,
    sha256_file,
    validate_evidence,
)


INSTALLER_NAME = "Catalyst-Setup-v1.3.17.exe"
VALID_HASH = "c" * 64
VALID_EVIDENCE = {
    "schema_version": 1,
    "artifact": {
        "name": INSTALLER_NAME,
        "size_bytes": 16,
        "sha256": VALID_HASH,
    },
    "signature": {
        "authenticode_status": "Valid",
        "publisher": "SignPath Foundation",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_status": "Valid",
        "timestamp_subject": "CN=DigiCert Timestamp 2025",
        "timestamp_thumbprint": "B" * 40,
        "product_name": "CATalyst",
        "product_version": "1.3.17",
        "file_version": "1.3.17.0",
    },
    "source": {
        "repository": "catalystxch/catalyst-bot",
        "tag": "v1.3.17",
        "commit": "a" * 40,
        "workflow_run_url": (
            "https://github.com/catalystxch/catalyst-bot/actions/runs/123"
        ),
    },
    "signpath": {
        "application_signing_request_id": "application-request-id",
        "installer_signing_request_id": "installer-request-id",
    },
}


def expect_failure(action, expected: str) -> None:
    try:
        action()
    except ReleaseVerificationError as exc:
        if expected not in str(exc):
            raise AssertionError(f"expected {expected!r} in {str(exc)!r}") from exc
    else:
        raise AssertionError(f"expected ReleaseVerificationError containing {expected!r}")


def check_pure_validation() -> None:
    normalized = validate_evidence(
        VALID_EVIDENCE,
        INSTALLER_NAME,
        VALID_HASH,
        16,
        "1.3.17",
    )
    assert normalized["signature"]["publisher"] == "SignPath Foundation"
    assert normalized["source"]["tag"] == "v1.3.17"

    mutations = [
        (("schema_version",), 2, "schema_version"),
        (("artifact", "name"), "other.exe", "artifact name"),
        (("artifact", "size_bytes"), 17, "artifact size"),
        (("artifact", "sha256"), "d" * 64, "artifact hash"),
        (("signature", "publisher"), "Unknown", "publisher"),
        (("signature", "authenticode_status"), "Invalid", "Authenticode"),
        (("signature", "timestamp_status"), "Invalid", "timestamp status"),
        (("signature", "product_name"), "Other", "product"),
        (("signature", "product_version"), "1.3.16", "product version"),
        (("signature", "file_version"), "1.3.16.0", "file version"),
        (("source", "repository"), "someone/else", "source repository"),
        (("source", "tag"), "v1.3.16", "source tag"),
        (("source", "commit"), "a" * 39, "source commit"),
        (("source", "workflow_run_url"), "https://example.com/run/1", "workflow URL"),
        (("signpath", "application_signing_request_id"), "", "application_signing_request_id"),
        (("signpath", "installer_signing_request_id"), "", "installer_signing_request_id"),
    ]
    for path, value, message in mutations:
        evidence = copy.deepcopy(VALID_EVIDENCE)
        target = evidence
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        expect_failure(
            lambda evidence=evidence: validate_evidence(
                evidence, INSTALLER_NAME, VALID_HASH, 16, "1.3.17"
            ),
            message,
        )

    assert parse_sha256_sidecar(
        f"{VALID_HASH}  {INSTALLER_NAME}\n", INSTALLER_NAME
    ) == VALID_HASH
    for text, message in [
        (f"{VALID_HASH}  other.exe\n", "filename"),
        (f"{'d' * 64}  {INSTALLER_NAME}\n", "checksum"),
        (f"{VALID_HASH}  {INSTALLER_NAME}\n{VALID_HASH}  {INSTALLER_NAME}\n", "one record"),
        (f"not-a-hash  {INSTALLER_NAME}\n", "filename"),
    ]:
        expect_failure(
            lambda text=text: parse_sha256_sidecar(
                text, INSTALLER_NAME, expected_sha256=VALID_HASH
            ),
            message,
        )

    release = {"assets": [{"name": INSTALLER_NAME, "size": 16}]}
    assert find_release_asset(release, INSTALLER_NAME)["size"] == 16
    expect_failure(lambda: find_release_asset(release, "missing.exe"), "expected one")

    output = """Succeeded
Subject: CN=SignPath Foundation, O=SignPath Foundation
The signature is timestamped: Aug 28 2026
"""
    assert parse_osslsigncode_output(output).startswith("CN=SignPath Foundation")
    for bad_output, message in [
        (output.replace("Succeeded", "Failed"), "timestamped signature"),
        (output.replace("The signature is timestamped", "No timestamp"), "timestamped signature"),
        (
            output.replace(
                "Subject: CN=SignPath Foundation, O=SignPath Foundation",
                "Note: SignPath Foundation\nSubject: CN=Unknown Publisher",
            ),
            "publisher",
        ),
    ]:
        expect_failure(lambda value=bad_output: parse_osslsigncode_output(value), message)

    with tempfile.TemporaryDirectory() as directory:
        artifact = Path(directory) / "artifact.bin"
        artifact.write_bytes(b"exact bytes")
        assert sha256_file(artifact) == hashlib.sha256(b"exact bytes").hexdigest()


def main() -> None:
    check_pure_validation()
    print("Windows release evidence validation checks passed")


if __name__ == "__main__":
    main()

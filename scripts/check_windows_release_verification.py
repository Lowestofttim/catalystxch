#!/usr/bin/env python3
"""Standalone regression checks for Windows release verification."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import tempfile
import urllib.error
from pathlib import Path

from windows_release_verification import (
    ReleaseVerificationError,
    find_release_asset,
    parse_osslsigncode_output,
    parse_sha256_sidecar,
    sha256_file,
    validate_evidence,
    verify_windows_release,
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
    slash_output = """Succeeded
		Subject: /C=AT/O=SignPath Foundation/CN=SignPath Foundation
The signature is timestamped: Aug 28 2026
"""
    assert "/O=SignPath Foundation/" in parse_osslsigncode_output(slash_output)
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


class FakeResponse:
    def __init__(self, content: bytes, url: str):
        self._content = io.BytesIO(content)
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._content.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def build_release_fixture():
    installer_bytes = b"signed-installer"
    installer_hash = hashlib.sha256(installer_bytes).hexdigest()
    base_url = (
        "https://github.com/Lowestofttim/catalyst-releases/"
        "releases/download/v1.3.17"
    )
    evidence = copy.deepcopy(VALID_EVIDENCE)
    evidence["artifact"]["sha256"] = installer_hash
    evidence_bytes = (json.dumps(evidence, sort_keys=True) + "\n").encode()
    sidecar_name = f"{INSTALLER_NAME}.sha256"
    evidence_name = "windows-signature-v1.3.17.json"
    payloads = {
        f"{base_url}/{INSTALLER_NAME}": installer_bytes,
        f"{base_url}/{sidecar_name}": (
            f"{installer_hash}  {INSTALLER_NAME}".encode()
        ),
        f"{base_url}/{evidence_name}": evidence_bytes,
    }
    release = {
        "tagName": "v1.3.17",
        "assets": [
            {
                "name": INSTALLER_NAME,
                "url": f"{base_url}/{INSTALLER_NAME}",
                "size": len(installer_bytes),
                "digest": f"sha256:{installer_hash}",
            },
            {
                "name": sidecar_name,
                "url": f"{base_url}/{sidecar_name}",
                "size": len(payloads[f"{base_url}/{sidecar_name}"]),
            },
            {
                "name": evidence_name,
                "url": f"{base_url}/{evidence_name}",
                "size": len(evidence_bytes),
            },
        ],
    }
    return release, payloads, evidence_bytes, installer_hash


def check_end_to_end_verification() -> None:
    release, payloads, evidence_bytes, _installer_hash = build_release_fixture()

    def opener(request, timeout):
        assert timeout > 0
        url = request.full_url
        return FakeResponse(payloads[url], url)

    def runner(command, **options):
        assert command[0:3] == ["osslsigncode", "verify", "-in"]
        assert Path(command[3]).read_bytes() == b"signed-installer"
        assert options["check"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            """Succeeded
Subject: CN=SignPath Foundation, O=SignPath Foundation
The signature is timestamped: Aug 28 2026
""",
            "",
        )

    result = verify_windows_release(
        release,
        urlopen=opener,
        runner=runner,
    )
    assert result == {
        "download_enabled": True,
        "verification": {
            "authenticode_status": "valid",
            "publisher": "SignPath Foundation",
            "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
            "signer_thumbprint": "A" * 40,
            "timestamp_status": "valid",
            "evidence_url": (
                "https://github.com/Lowestofttim/catalyst-releases/"
                "releases/download/v1.3.17/windows-signature-v1.3.17.json"
            ),
            "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        },
    }

    def expect_verification_failure(release_value, payload_values, runner_value=runner):
        def test_opener(request, timeout):
            url = request.full_url
            return FakeResponse(payload_values[url], url)

        expect_failure(
            lambda: verify_windows_release(
                release_value,
                urlopen=test_opener,
                runner=runner_value,
            ),
            "Windows release verification failed",
        )

    expect_failure(
        lambda: verify_windows_release(
            release,
            urlopen=lambda request, timeout: (_ for _ in ()).throw(
                urllib.error.URLError("offline")
            ),
            runner=runner,
        ),
        "Windows release verification failed",
    )

    def redirected_opener(request, timeout):
        return FakeResponse(payloads[request.full_url], "https://evil.example/file")

    expect_failure(
        lambda: verify_windows_release(
            release, urlopen=redirected_opener, runner=runner
        ),
        "Windows release verification failed",
    )

    missing = copy.deepcopy(release)
    missing["assets"] = missing["assets"][:-1]
    expect_verification_failure(missing, payloads)

    bad_digest = copy.deepcopy(release)
    bad_digest["assets"][0]["digest"] = "sha256:" + "d" * 64
    expect_verification_failure(bad_digest, payloads)

    sidecar_url = release["assets"][1]["url"]
    bad_sidecar_payloads = dict(payloads)
    bad_sidecar_payloads[sidecar_url] = f"{'d' * 64}  {INSTALLER_NAME}".encode()
    expect_verification_failure(release, bad_sidecar_payloads)

    evidence_url = release["assets"][2]["url"]
    bad_evidence_payloads = dict(payloads)
    bad_evidence = copy.deepcopy(VALID_EVIDENCE)
    bad_evidence["signature"]["publisher"] = "Unknown"
    bad_evidence_payloads[evidence_url] = json.dumps(bad_evidence).encode()
    expect_verification_failure(release, bad_evidence_payloads)

    expect_verification_failure(
        release,
        payloads,
        lambda command, **options: (_ for _ in ()).throw(
            FileNotFoundError("osslsigncode")
        ),
    )
    expect_verification_failure(
        release,
        payloads,
        lambda command, **options: subprocess.CompletedProcess(
            command, 1, "Failed", "invalid signature"
        ),
    )
    expect_verification_failure(
        release,
        payloads,
        lambda command, **options: subprocess.CompletedProcess(
            command, 0, "Succeeded but no timestamp", ""
        ),
    )


def main() -> None:
    check_pure_validation()
    check_end_to_end_verification()
    print("Windows release evidence validation checks passed")


if __name__ == "__main__":
    main()

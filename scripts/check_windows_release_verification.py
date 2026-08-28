#!/usr/bin/env python3
"""Standalone regression checks for Windows release verification."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import subprocess
import tempfile
import urllib.error
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from windows_release_verification import (
    ReleaseVerificationError,
    find_release_asset,
    parse_osslsigncode_output,
    parse_sha256_sidecar,
    sha256_file,
    validate_evidence,
    validate_signed_update_manifest,
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
        raise AssertionError(
            f"expected ReleaseVerificationError containing {expected!r}"
        )


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
        (
            ("signpath", "application_signing_request_id"),
            "",
            "application_signing_request_id",
        ),
        (
            ("signpath", "installer_signing_request_id"),
            "",
            "installer_signing_request_id",
        ),
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

    assert (
        parse_sha256_sidecar(f"{VALID_HASH}  {INSTALLER_NAME}\n", INSTALLER_NAME)
        == VALID_HASH
    )
    for text, message in [
        (f"{VALID_HASH}  other.exe\n", "filename"),
        (f"{'d' * 64}  {INSTALLER_NAME}\n", "checksum"),
        (
            f"{VALID_HASH}  {INSTALLER_NAME}\n{VALID_HASH}  {INSTALLER_NAME}\n",
            "one record",
        ),
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
        (
            output.replace("The signature is timestamped", "No timestamp"),
            "timestamped signature",
        ),
        (
            output.replace(
                "Subject: CN=SignPath Foundation, O=SignPath Foundation",
                "Note: SignPath Foundation\nSubject: CN=Unknown Publisher",
            ),
            "publisher",
        ),
    ]:
        expect_failure(
            lambda value=bad_output: parse_osslsigncode_output(value), message
        )

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
        "https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.3.17"
    )
    evidence = copy.deepcopy(VALID_EVIDENCE)
    evidence["artifact"]["sha256"] = installer_hash
    evidence_bytes = (json.dumps(evidence, sort_keys=True) + "\n").encode()
    sidecar_name = f"{INSTALLER_NAME}.sha256"
    evidence_name = "windows-signature-v1.3.17.json"
    manifest_name = "latest.json"
    manifest_signature_name = "latest.json.sig"
    manifest = {
        "schema": 1,
        "app": "CATalyst",
        "channel": "stable",
        "version": "1.3.17",
        "tag": "v1.3.17",
        "published_at": "2026-08-28T08:00:00Z",
        "expires_at": "2026-11-26T08:00:00Z",
        "release_url": (
            "https://github.com/Lowestofttim/catalyst-releases/releases/tag/v1.3.17"
        ),
        "release_notes": "Signed release",
        "platforms": {
            "windows-x64": {
                "installer": {
                    "name": INSTALLER_NAME,
                    "url": f"{base_url}/{INSTALLER_NAME}",
                    "size": len(installer_bytes),
                    "sha256": installer_hash,
                }
            }
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    signing_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key_b64 = base64.b64encode(
        signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    canonical_manifest = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest_signature = base64.b64encode(signing_key.sign(canonical_manifest)) + b"\n"
    payloads = {
        f"{base_url}/{INSTALLER_NAME}": installer_bytes,
        f"{base_url}/{sidecar_name}": (f"{installer_hash}  {INSTALLER_NAME}".encode()),
        f"{base_url}/{evidence_name}": evidence_bytes,
        f"{base_url}/{manifest_name}": manifest_bytes,
        f"{base_url}/{manifest_signature_name}": manifest_signature,
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
            {
                "name": manifest_name,
                "url": f"{base_url}/{manifest_name}",
                "size": len(manifest_bytes),
            },
            {
                "name": manifest_signature_name,
                "url": f"{base_url}/{manifest_signature_name}",
                "size": len(manifest_signature),
            },
        ],
    }
    return release, payloads, evidence_bytes, installer_hash, public_key_b64


def check_end_to_end_verification() -> None:
    release, payloads, evidence_bytes, installer_hash, public_key_b64 = (
        build_release_fixture()
    )

    manifest = json.loads(payloads[release["assets"][3]["url"]])
    signature = payloads[release["assets"][4]["url"]]
    validated_manifest = validate_signed_update_manifest(
        manifest,
        signature,
        public_key_b64=public_key_b64,
        installer_name=INSTALLER_NAME,
        installer_url=release["assets"][0]["url"],
        installer_size=len(payloads[release["assets"][0]["url"]]),
        installer_sha256=installer_hash,
        expected_tag="v1.3.17",
    )
    assert validated_manifest["tag"] == "v1.3.17"

    def opener(request, timeout):
        assert timeout > 0
        url = request.full_url
        return FakeResponse(payloads[url], url)

    def runner(command, **options):
        assert command[0:4] == [
            "osslsigncode",
            "verify",
            "-require-leaf-hash",
            "sha1:" + "A" * 40,
        ]
        assert command[4] == "-in"
        assert Path(command[5]).read_bytes() == b"signed-installer"
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
        trusted_signer_thumbprints=frozenset({"A" * 40}),
        manifest_public_key_b64=public_key_b64,
    )
    assert result == {
        "download_enabled": True,
        "verification": {
            "authenticode_status": "valid",
            "publisher": "SignPath Foundation",
            "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
            "signer_thumbprint": "A" * 40,
            "timestamp_status": "valid",
            "update_manifest_status": "valid",
            "update_manifest_url": (
                "https://github.com/Lowestofttim/catalyst-releases/"
                "releases/download/v1.3.17/latest.json"
            ),
            "update_manifest_signature_url": (
                "https://github.com/Lowestofttim/catalyst-releases/"
                "releases/download/v1.3.17/latest.json.sig"
            ),
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
                trusted_signer_thumbprints=frozenset({"A" * 40}),
                manifest_public_key_b64=public_key_b64,
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
            trusted_signer_thumbprints=frozenset({"A" * 40}),
            manifest_public_key_b64=public_key_b64,
        ),
        "Windows release verification failed",
    )

    def redirected_opener(request, timeout):
        return FakeResponse(payloads[request.full_url], "https://evil.example/file")

    expect_failure(
        lambda: verify_windows_release(
            release,
            urlopen=redirected_opener,
            runner=runner,
            trusted_signer_thumbprints=frozenset({"A" * 40}),
            manifest_public_key_b64=public_key_b64,
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

    untrusted_evidence_payloads = dict(payloads)
    untrusted_evidence = copy.deepcopy(VALID_EVIDENCE)
    untrusted_evidence["artifact"]["sha256"] = installer_hash
    untrusted_evidence["signature"]["signer_thumbprint"] = "C" * 40
    untrusted_evidence_payloads[evidence_url] = json.dumps(untrusted_evidence).encode()
    expect_verification_failure(release, untrusted_evidence_payloads)

    manifest_url = release["assets"][3]["url"]
    bad_manifest_payloads = dict(payloads)
    bad_manifest = json.loads(bad_manifest_payloads[manifest_url])
    bad_manifest["platforms"]["windows-x64"]["installer"]["sha256"] = "d" * 64
    bad_manifest_payloads[manifest_url] = json.dumps(bad_manifest).encode()
    expect_verification_failure(release, bad_manifest_payloads)

    bad_signature_payloads = dict(payloads)
    bad_signature_payloads[release["assets"][4]["url"]] = base64.b64encode(b"x" * 64)
    expect_verification_failure(release, bad_signature_payloads)

    expect_failure(
        lambda: verify_windows_release(
            release,
            urlopen=opener,
            runner=runner,
            trusted_signer_thumbprints=frozenset(),
            manifest_public_key_b64=public_key_b64,
        ),
        "Windows release verification failed",
    )

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

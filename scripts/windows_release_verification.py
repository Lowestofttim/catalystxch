#!/usr/bin/env python3
"""Fail-closed verification for public CATalyst Windows release assets."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class ReleaseVerificationError(RuntimeError):
    """Raised when a public Windows release cannot be independently verified."""


UPDATE_MANIFEST_PUBLIC_KEY_B64 = "cyjvFTb0quqOQdl2c0TMwzwF8PBb74qwGztqxLSazBQ="

# SignPath Foundation assigns the production leaf certificate after accepting
# the project. The first signed release must add its independently observed
# SHA-1 thumbprint here through a reviewed website change. An empty allowlist
# deliberately keeps Windows downloads disabled until that has happened.
TRUSTED_SIGNER_THUMBPRINTS: frozenset[str] = frozenset()


def sha256_file(path: Path) -> str:
    """Return the lower-case SHA-256 digest of exact file bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_release_asset(
    release: Mapping[str, object], name: str
) -> Mapping[str, object]:
    """Return the unique named release asset or fail closed."""

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseVerificationError("release assets are missing")
    matches = [
        item
        for item in assets
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ReleaseVerificationError(f"expected one release asset named {name}")
    return matches[0]


def parse_sha256_sidecar(
    text: str, expected_name: str, expected_sha256: str | None = None
) -> str:
    """Parse a single sha256sum-style record for the expected installer."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ReleaseVerificationError("checksum sidecar must contain one record")
    match = re.fullmatch(r"([a-fA-F0-9]{64})[ \t]+\*?(.+)", lines[0])
    if not match or match.group(2) != expected_name:
        raise ReleaseVerificationError("checksum sidecar filename is invalid")
    digest = match.group(1).lower()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ReleaseVerificationError("checksum sidecar checksum does not match")
    return digest


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReleaseVerificationError(f"evidence {field} is missing")
    return value


def _has_publisher_component(subject: str) -> bool:
    return bool(
        re.search(
            r"(?:^|[,/]\s*)(?:CN|O)\s*=\s*SignPath Foundation(?:[,/]|$)",
            subject,
            re.IGNORECASE,
        )
    )


def validate_evidence(
    evidence: Mapping[str, object],
    installer_name: str,
    installer_sha256: str,
    installer_size: int,
    expected_version: str,
) -> dict[str, object]:
    """Validate source-produced evidence against downloaded installer bytes."""

    artifact = _mapping(evidence.get("artifact"), "artifact")
    signature = _mapping(evidence.get("signature"), "signature")
    source = _mapping(evidence.get("source"), "source")
    signpath = _mapping(evidence.get("signpath"), "signpath")
    expected = {
        "schema_version": (evidence.get("schema_version"), 1),
        "artifact name": (artifact.get("name"), installer_name),
        "artifact size": (artifact.get("size_bytes"), installer_size),
        "artifact hash": (artifact.get("sha256"), installer_sha256),
        "Authenticode status": (signature.get("authenticode_status"), "Valid"),
        "publisher": (signature.get("publisher"), "SignPath Foundation"),
        "timestamp status": (signature.get("timestamp_status"), "Valid"),
        "product": (signature.get("product_name"), "CATalyst"),
        "product version": (signature.get("product_version"), expected_version),
        "file version": (
            signature.get("file_version"),
            f"{expected_version}.0",
        ),
        "source repository": (
            source.get("repository"),
            "catalystxch/catalyst-bot",
        ),
        "source tag": (source.get("tag"), f"v{expected_version}"),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ReleaseVerificationError(f"evidence {field} does not match")

    signer_subject = str(signature.get("signer_subject") or "")
    if not _has_publisher_component(signer_subject):
        raise ReleaseVerificationError("evidence signer subject is invalid")
    if not str(signature.get("timestamp_subject") or "").strip():
        raise ReleaseVerificationError("evidence timestamp subject is missing")
    if not re.fullmatch(r"[A-F0-9]{40}", str(signature.get("signer_thumbprint") or "")):
        raise ReleaseVerificationError("evidence signer thumbprint is invalid")
    if not re.fullmatch(
        r"[A-F0-9]{40}", str(signature.get("timestamp_thumbprint") or "")
    ):
        raise ReleaseVerificationError("evidence timestamp thumbprint is invalid")
    if not re.fullmatch(r"[a-f0-9]{40}", str(source.get("commit") or "")):
        raise ReleaseVerificationError("evidence source commit is invalid")

    workflow_url = urlparse(str(source.get("workflow_run_url") or ""))
    workflow_prefix = "/catalystxch/catalyst-bot/actions/runs/"
    run_id = workflow_url.path.removeprefix(workflow_prefix)
    if (
        workflow_url.scheme != "https"
        or workflow_url.netloc != "github.com"
        or not workflow_url.path.startswith(workflow_prefix)
        or not run_id.isdigit()
        or workflow_url.query
        or workflow_url.fragment
    ):
        raise ReleaseVerificationError("evidence workflow URL is invalid")
    for key in (
        "application_signing_request_id",
        "installer_signing_request_id",
    ):
        if not str(signpath.get(key) or "").strip():
            raise ReleaseVerificationError(f"evidence {key} is missing")
    return {
        "signature": dict(signature),
        "source": dict(source),
        "signpath": dict(signpath),
    }


def _canonical_manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_signed_update_manifest(
    manifest: Mapping[str, object],
    signature_bytes: bytes,
    *,
    public_key_b64: str,
    installer_name: str,
    installer_url: str,
    installer_size: int,
    installer_sha256: str,
    expected_tag: str,
) -> dict[str, object]:
    """Verify CATalyst's project key and bind it to exact installer bytes."""

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        signature = base64.b64decode(signature_bytes.strip(), validate=True)
        public_key.verify(signature, _canonical_manifest_bytes(manifest))
    except (InvalidSignature, ValueError, UnicodeError) as exc:
        raise ReleaseVerificationError(
            "CATalyst update manifest signature is invalid"
        ) from exc

    version = expected_tag.removeprefix("v")
    platforms = _mapping(manifest.get("platforms"), "manifest platforms")
    windows = _mapping(platforms.get("windows-x64"), "manifest windows-x64")
    installer = _mapping(windows.get("installer"), "manifest installer")
    expected = {
        "schema": (manifest.get("schema"), 1),
        "app": (manifest.get("app"), "CATalyst"),
        "channel": (manifest.get("channel"), "stable"),
        "version": (manifest.get("version"), version),
        "tag": (manifest.get("tag"), expected_tag),
        "release URL": (
            manifest.get("release_url"),
            f"https://github.com/Lowestofttim/catalyst-releases/releases/tag/{expected_tag}",
        ),
        "installer name": (installer.get("name"), installer_name),
        "installer URL": (installer.get("url"), installer_url),
        "installer size": (installer.get("size"), installer_size),
        "installer hash": (installer.get("sha256"), installer_sha256),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ReleaseVerificationError(f"signed manifest {field} does not match")
    return dict(manifest)


def parse_osslsigncode_output(output: str) -> str:
    """Require osslsigncode success, timestamp, and exact publisher subject."""

    if "Succeeded" not in output or "The signature is timestamped" not in output:
        raise ReleaseVerificationError(
            "osslsigncode did not prove a timestamped signature"
        )
    subjects = re.findall(r"(?m)^\s*Subject:\s*(.+?)\s*$", output)
    matching = [subject for subject in subjects if _has_publisher_component(subject)]
    if len(matching) != 1:
        raise ReleaseVerificationError(
            "osslsigncode publisher is not SignPath Foundation"
        )
    return matching[0].strip()


def _asset_url(asset: Mapping[str, object], expected: str) -> str:
    url = str(asset.get("url") or "")
    if url != expected:
        raise ReleaseVerificationError("release asset URL is not canonical")
    return url


def _download(
    url: str,
    destination: Path,
    *,
    urlopen,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CATalyst-website-release-verifier/1"},
    )
    with urlopen(request, timeout=60) as response:
        final = urlparse(str(response.geturl()))
        if final.scheme != "https" or final.hostname not in {
            "github.com",
            "release-assets.githubusercontent.com",
        }:
            raise ReleaseVerificationError("release asset redirect is not trusted")
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)


def verify_windows_release(
    release: Mapping[str, object],
    temp_root: Path | None = None,
    urlopen=urllib.request.urlopen,
    runner=subprocess.run,
    trusted_signer_thumbprints: frozenset[str] = TRUSTED_SIGNER_THUMBPRINTS,
    manifest_public_key_b64: str = UPDATE_MANIFEST_PUBLIC_KEY_B64,
) -> dict[str, object]:
    """Download and independently verify one public Windows installer."""

    try:
        tag = str(release.get("tagName") or "")
        match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
        if not match:
            raise ReleaseVerificationError("release tag is not semantic")
        version = match.group(1)
        installer_name = f"Catalyst-Setup-{tag}.exe"
        sidecar_name = f"{installer_name}.sha256"
        evidence_name = f"windows-signature-{tag}.json"
        manifest_name = "latest.json"
        manifest_signature_name = "latest.json.sig"
        release_prefix = (
            f"https://github.com/Lowestofttim/catalyst-releases/releases/download/{tag}"
        )

        installer_asset = find_release_asset(release, installer_name)
        sidecar_asset = find_release_asset(release, sidecar_name)
        evidence_asset = find_release_asset(release, evidence_name)
        manifest_asset = find_release_asset(release, manifest_name)
        manifest_signature_asset = find_release_asset(release, manifest_signature_name)
        installer_url = _asset_url(
            installer_asset, f"{release_prefix}/{installer_name}"
        )
        sidecar_url = _asset_url(sidecar_asset, f"{release_prefix}/{sidecar_name}")
        evidence_url = _asset_url(evidence_asset, f"{release_prefix}/{evidence_name}")
        manifest_url = _asset_url(manifest_asset, f"{release_prefix}/{manifest_name}")
        manifest_signature_url = _asset_url(
            manifest_signature_asset,
            f"{release_prefix}/{manifest_signature_name}",
        )

        root = None if temp_root is None else str(temp_root)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            temporary = Path(directory)
            installer_path = temporary / installer_name
            sidecar_path = temporary / sidecar_name
            evidence_path = temporary / evidence_name
            manifest_path = temporary / manifest_name
            manifest_signature_path = temporary / manifest_signature_name
            _download(installer_url, installer_path, urlopen=urlopen)
            _download(sidecar_url, sidecar_path, urlopen=urlopen)
            _download(evidence_url, evidence_path, urlopen=urlopen)
            _download(manifest_url, manifest_path, urlopen=urlopen)
            _download(
                manifest_signature_url,
                manifest_signature_path,
                urlopen=urlopen,
            )

            expected_size = installer_asset.get("size")
            if (
                not isinstance(expected_size, int)
                or expected_size <= 0
                or installer_path.stat().st_size != expected_size
            ):
                raise ReleaseVerificationError("installer size does not match")
            installer_sha256 = sha256_file(installer_path)
            github_digest = str(installer_asset.get("digest") or "")
            if github_digest != f"sha256:{installer_sha256}":
                raise ReleaseVerificationError("GitHub installer digest does not match")
            sidecar_digest = parse_sha256_sidecar(
                sidecar_path.read_text(encoding="utf-8"),
                installer_name,
                expected_sha256=installer_sha256,
            )
            if sidecar_digest != installer_sha256:
                raise ReleaseVerificationError("sidecar digest does not match")

            evidence_bytes = evidence_path.read_bytes()
            evidence = json.loads(evidence_bytes)
            if not isinstance(evidence, Mapping):
                raise ReleaseVerificationError("signature evidence is not an object")
            validated = validate_evidence(
                evidence,
                installer_name,
                installer_sha256,
                expected_size,
                version,
            )

            manifest = json.loads(manifest_path.read_bytes())
            if not isinstance(manifest, Mapping):
                raise ReleaseVerificationError("update manifest is not an object")
            validate_signed_update_manifest(
                manifest,
                manifest_signature_path.read_bytes(),
                public_key_b64=manifest_public_key_b64,
                installer_name=installer_name,
                installer_url=installer_url,
                installer_size=expected_size,
                installer_sha256=installer_sha256,
                expected_tag=tag,
            )

            signature = validated["signature"]
            signer_thumbprint = str(signature["signer_thumbprint"])
            trusted = {
                str(value).strip().upper()
                for value in trusted_signer_thumbprints
                if re.fullmatch(r"[A-Fa-f0-9]{40}", str(value).strip())
            }
            if signer_thumbprint not in trusted:
                raise ReleaseVerificationError(
                    "signer thumbprint is not trusted for CATalyst"
                )
            command = [
                "osslsigncode",
                "verify",
                "-require-leaf-hash",
                f"sha1:{signer_thumbprint}",
                "-in",
                str(installer_path),
            ]
            completed = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                raise ReleaseVerificationError("osslsigncode returned failure")
            signer_subject = parse_osslsigncode_output(completed.stdout)
            return {
                "download_enabled": True,
                "verification": {
                    "authenticode_status": "valid",
                    "publisher": "SignPath Foundation",
                    "signer_subject": signer_subject,
                    "signer_thumbprint": signature["signer_thumbprint"],
                    "timestamp_status": "valid",
                    "update_manifest_status": "valid",
                    "update_manifest_url": manifest_url,
                    "update_manifest_signature_url": manifest_signature_url,
                    "evidence_url": evidence_url,
                    "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                },
            }
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
        UnicodeError,
        json.JSONDecodeError,
        ReleaseVerificationError,
    ) as exc:
        raise ReleaseVerificationError("Windows release verification failed") from exc

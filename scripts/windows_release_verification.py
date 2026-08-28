#!/usr/bin/env python3
"""Fail-closed verification for public CATalyst Windows release assets."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse


class ReleaseVerificationError(RuntimeError):
    """Raised when a public Windows release cannot be independently verified."""


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
            r"(?:^|,\s*)(?:CN|O)=SignPath Foundation(?:,|$)",
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
    if not re.fullmatch(
        r"[A-F0-9]{40}", str(signature.get("signer_thumbprint") or "")
    ):
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


def parse_osslsigncode_output(output: str) -> str:
    """Require osslsigncode success, timestamp, and exact publisher subject."""

    if "Succeeded" not in output or "The signature is timestamped" not in output:
        raise ReleaseVerificationError(
            "osslsigncode did not prove a timestamped signature"
        )
    subjects = re.findall(r"(?m)^Subject:\s*(.+?)\s*$", output)
    matching = [subject for subject in subjects if _has_publisher_component(subject)]
    if len(matching) != 1:
        raise ReleaseVerificationError(
            "osslsigncode publisher is not SignPath Foundation"
        )
    return matching[0].strip()

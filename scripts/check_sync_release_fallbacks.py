#!/usr/bin/env python3
"""Regression check for release-metadata HTML fallback synchronization."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from check_release_metadata import find_stale_literal_versions
from sync_release_metadata import (
    append_platform_downloads,
    build_metadata,
    preserve_generated_at_if_unchanged,
    render_release_fallbacks,
    write_metadata_atomic,
)
from windows_release_verification import ReleaseVerificationError


def main() -> None:
    metadata = {
        "schema_version": 2,
        "downloads_enabled": True,
        "download_status": "available",
        "latest": {
            "version": "v9.8.7",
            "name": "CATalyst <Test> v9.8.7",
            "published_at": "2026-08-25T18:43:48Z",
            "channel": "stable",
            "release_notes": ["First & safest", "Second <fix>"],
            "assets": [
                {
                    "name": "Catalyst-Setup-v9.8.7.exe",
                    "platform": "windows",
                    "kind": "installer",
                    "size_bytes": 28_169_368,
                    "download_url": "https://github.com/example/windows.exe",
                    "sha256": "a" * 64,
                    "download_enabled": True,
                    "verification": {
                        "authenticode_status": "valid",
                        "publisher": "SignPath Foundation",
                        "signer_subject": (
                            "CN=SignPath Foundation, O=SignPath Foundation"
                        ),
                        "signer_thumbprint": "A" * 40,
                        "timestamp_status": "valid",
                        "update_manifest_status": "valid",
                        "update_manifest_url": "https://github.com/example/latest.json",
                        "update_manifest_signature_url": (
                            "https://github.com/example/latest.json.sig"
                        ),
                        "evidence_url": "https://github.com/example/evidence.json",
                        "evidence_sha256": "c" * 64,
                    },
                },
                {
                    "name": "catalyst_v9.8.7_amd64.deb",
                    "platform": "linux",
                    "kind": "installer",
                    "size_bytes": 199_062_594,
                    "download_url": "https://github.com/example/linux.deb",
                    "sha256": "b" * 64,
                    "download_enabled": True,
                },
            ],
        },
    }
    source = """<main>
  <span data-release-eyebrow>old eyebrow</span>
  <span data-release-name>old name</span>
  <span data-release-version>v1.0.0</span>
  <span data-release-status>old status</span>
  <span data-release-meta>old meta</span>
  <span data-release-download-name>old.exe</span>
  <span data-release-download-size>1 MB</span>
  <span data-release-sha256>old-sha</span>
  <span data-release-windows-signature>old-signature</span>
  <span data-release-windows-tag>old-tag</span>
  <span data-release-linux-size>2 MB</span>
  <span data-release-linux-sha256>old-linux-sha</span>
  <aside data-windows-download-notice>
    <strong data-windows-download-notice-title>Windows downloads paused</strong>
    <p data-windows-download-notice-body>old warning</p>
  </aside>
  <ul data-release-notes>
    <li>old note</li>
  </ul>
</main>
"""

    rendered = render_release_fallbacks(source, metadata)

    expected_fragments = [
        "Windows/Linux downloads available - current release v9.8.7",
        "CATalyst &lt;Test&gt; v9.8.7",
        ">v9.8.7</span>",
        "Stable - published 25 Aug 2026 - windows/linux downloads available",
        "Catalyst-Setup-v9.8.7.exe",
        ">26.9 MB</span>",
        ">189.8 MB</span>",
        "a" * 64,
        "Verified publisher: SignPath Foundation",
        ">Verified</span>",
        "b" * 64,
        "<li>First &amp; safest</li>",
        "<li>Second &lt;fix&gt;</li>",
    ]
    for fragment in expected_fragments:
        if fragment not in rendered:
            raise SystemExit(f"missing synchronized fallback: {fragment}")
    for stale in ("v1.0.0", "old note", "old-sha", "old-linux-sha"):
        if stale in rendered:
            raise SystemExit(f"stale fallback remains: {stale}")
    if "<aside data-windows-download-notice hidden>" not in rendered:
        raise SystemExit("verified Windows fallback must hide the temporary pause notice")

    release_note_history = """<main>
  <span data-release-version>v9.8.7</span>
  <ul data-release-notes><li>Fix v9.8.6 startup migration</li></ul>
</main>
"""
    if find_stale_literal_versions(release_note_history, "v9.8.7", {"v9.8.6"}):
        raise SystemExit("historical versions in release notes must not be stale")

    stale_page_copy = """<main>
  <span data-release-version>v9.8.7</span>
  <p>Download CATalyst v9.8.6 today.</p>
</main>
"""
    if find_stale_literal_versions(stale_page_copy, "v9.8.7") != ["v9.8.6"]:
        raise SystemExit("stale versions outside release notes must still be rejected")

    stale_after_void_note_element = """<main>
  <span data-release-version>v9.8.7</span>
  <ul data-release-notes><li>Fix v9.8.6<br>startup migration</li></ul>
  <p>Download CATalyst v9.8.5 today.</p>
</main>
"""
    if find_stale_literal_versions(
        stale_after_void_note_element, "v9.8.7", {"v9.8.6"}
    ) != ["v9.8.5"]:
        raise SystemExit(
            "void elements in release notes must not hide later stale versions"
        )

    stale_note_container_attribute = """<main>
  <span data-release-version>v9.8.7</span>
  <ul data-release-notes aria-label="Release v9.8.6 notes">
    <li>Fix v9.8.6 startup migration</li>
  </ul>
</main>
"""
    if find_stale_literal_versions(
        stale_note_container_attribute, "v9.8.7", {"v9.8.6"}
    ) != ["v9.8.6"]:
        raise SystemExit(
            "stale attributes on release-note containers must still be rejected"
        )

    extra_stale_release_note = """<main>
  <span data-release-version>v9.8.7</span>
  <ul data-release-notes>
    <li>Fix v9.8.6 startup migration</li>
    <li>Obsolete v9.8.5 fallback text</li>
  </ul>
</main>
"""
    if find_stale_literal_versions(extra_stale_release_note, "v9.8.7", {"v9.8.6"}) != [
        "v9.8.5"
    ]:
        raise SystemExit(
            "only historical versions in the configured release notes may be exempt"
        )

    existing = deepcopy(metadata)
    existing["generated_at"] = "2026-08-25T18:00:00Z"
    refreshed = deepcopy(metadata)
    refreshed["generated_at"] = "2026-08-25T19:00:00Z"
    preserve_generated_at_if_unchanged(refreshed, existing)
    if refreshed["generated_at"] != existing["generated_at"]:
        raise SystemExit("unchanged releases must not create hourly timestamp churn")

    changed = deepcopy(metadata)
    changed["generated_at"] = "2026-08-25T20:00:00Z"
    changed["latest"]["version"] = "v9.8.8"
    preserve_generated_at_if_unchanged(changed, existing)
    if changed["generated_at"] != "2026-08-25T20:00:00Z":
        raise SystemExit("changed releases must retain their new generation timestamp")

    release = {
        "tagName": "v9.8.7",
        "name": "CATalyst v9.8.7",
        "publishedAt": "2026-08-25T18:43:48Z",
        "body": "- Signed release",
        "isPrerelease": False,
        "assets": [
            {
                "name": "Catalyst-Setup-v9.8.7.exe",
                "size": 28_169_368,
                "url": (
                    "https://github.com/Lowestofttim/catalyst-releases/"
                    "releases/download/v9.8.7/Catalyst-Setup-v9.8.7.exe"
                ),
                "digest": "sha256:" + "a" * 64,
            }
        ],
    }
    verification = metadata["latest"]["assets"][0]["verification"]
    verified = build_metadata(
        release,
        "Lowestofttim/catalyst-releases",
        True,
        "windows",
        "installer",
        windows_verifier=lambda value: {
            "download_enabled": True,
            "verification": deepcopy(verification),
        },
    )
    expected_windows = {
        "name": "Catalyst-Setup-v9.8.7.exe",
        "platform": "windows",
        "kind": "installer",
        "size_bytes": 28_169_368,
        "download_url": release["assets"][0]["url"],
        "sha256": "a" * 64,
        "download_enabled": True,
        "verification": verification,
    }
    if verified["schema_version"] != 2:
        raise SystemExit("release metadata must use schema version 2")
    if verified["latest"]["assets"] != [expected_windows]:
        raise SystemExit("verified Windows metadata did not preserve the trust chain")

    linux_release = {
        "assets": [
            {
                "name": "catalyst_v9.8.7_amd64.deb",
                "size": 199_062_594,
                "url": "https://github.com/catalystxch/catalyst-bot/releases/download/v9.8.7/catalyst_v9.8.7_amd64.deb",
                "digest": "sha256:" + "b" * 64,
            }
        ]
    }
    append_platform_downloads(verified, linux_release, True)
    linux = next(
        asset for asset in verified["latest"]["assets"] if asset["platform"] == "linux"
    )
    if linux.get("download_enabled") is not True or "verification" in linux:
        raise SystemExit("Linux availability must be independent of Windows signing")

    disabled = deepcopy(verified)
    windows = next(
        asset
        for asset in disabled["latest"]["assets"]
        if asset["platform"] == "windows"
    )
    windows.update(
        {
            "download_url": None,
            "sha256": None,
            "download_enabled": False,
            "verification": {
                "authenticode_status": "unavailable",
                "publisher": None,
                "signer_subject": None,
                "signer_thumbprint": None,
                "timestamp_status": "unavailable",
                "update_manifest_status": "unavailable",
                "update_manifest_url": None,
                "update_manifest_signature_url": None,
                "evidence_url": None,
                "evidence_sha256": None,
            },
        }
    )
    disabled["downloads_enabled"] = True
    disabled["download_status"] = "partial"
    disabled_html = render_release_fallbacks(source, disabled)
    if "Linux download available" not in disabled_html:
        raise SystemExit("disabled Windows must not disable Linux")
    if "Linux download available - current release v9.8.7" not in disabled_html:
        raise SystemExit("Linux-only eyebrow must report the available release")
    if (
        "Windows installer unavailable - signature verification required"
        not in disabled_html
    ):
        raise SystemExit("disabled Windows signature status must be visible")
    if "<aside data-windows-download-notice hidden>" in disabled_html:
        raise SystemExit("disabled Windows fallback must show the temporary pause notice")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "latest.json"
        output.write_bytes(b'{"trusted": true}\n')

        def fail_verification(_release):
            raise ReleaseVerificationError("expected verifier failure")

        failed_metadata = build_metadata(
            release,
            "Lowestofttim/catalyst-releases",
            True,
            "windows",
            "installer",
            windows_verifier=fail_verification,
        )
        failed_windows = failed_metadata["latest"]["assets"][0]
        if failed_windows["download_enabled"] is not False:
            raise SystemExit("failed Windows verification must disable Windows")
        if failed_windows["verification"] != {
            "authenticode_status": "unavailable",
            "publisher": None,
            "signer_subject": None,
            "signer_thumbprint": None,
            "timestamp_status": "unavailable",
            "update_manifest_status": "unavailable",
            "update_manifest_url": None,
            "update_manifest_signature_url": None,
            "evidence_url": None,
            "evidence_sha256": None,
        }:
            raise SystemExit(
                "failed Windows verification used trusted-looking metadata"
            )
        append_platform_downloads(failed_metadata, linux_release, True)
        if failed_metadata["download_status"] != "partial":
            raise SystemExit(
                "Linux must remain available when Windows verification fails"
            )
        write_metadata_atomic(output, failed_metadata)
        written = json.loads(output.read_text(encoding="utf-8"))
        if not any(
            asset.get("platform") == "linux" and asset.get("download_enabled") is True
            for asset in written["latest"]["assets"]
        ):
            raise SystemExit("failed Windows verification removed the Linux release")

        unsigned_metadata = build_metadata(
            release,
            "Lowestofttim/catalyst-releases",
            True,
            "windows",
            "installer",
            allow_unsigned_windows_beta=True,
            windows_verifier=fail_verification,
        )
        unsigned_windows = unsigned_metadata["latest"]["assets"][0]
        if unsigned_windows != {
            "name": "Catalyst-Setup-v9.8.7.exe",
            "platform": "windows",
            "kind": "installer",
            "size_bytes": 28_169_368,
            "download_url": release["assets"][0]["url"],
            "sha256": "a" * 64,
            "download_enabled": True,
            "distribution_status": "unsigned_beta",
            "verification": {
                "authenticode_status": "unsigned",
                "publisher": None,
                "signer_subject": None,
                "signer_thumbprint": None,
                "timestamp_status": "unavailable",
                "update_manifest_status": "unavailable",
                "update_manifest_url": None,
                "update_manifest_signature_url": None,
                "evidence_url": None,
                "evidence_sha256": None,
            },
        }:
            raise SystemExit("explicit unsigned Windows beta metadata is incorrect")
        unsigned_html = render_release_fallbacks(source, unsigned_metadata)
        for expected in (
            "Unsigned beta - expect a Windows SmartScreen warning",
            "Unsigned Windows beta",
            ">Unsigned beta</span>",
            "Windows protected your PC",
            "Do not continue",
        ):
            if expected not in unsigned_html:
                raise SystemExit(f"unsigned Windows fallback is missing: {expected}")
        if "<aside data-windows-download-notice hidden>" in unsigned_html:
            raise SystemExit("unsigned Windows fallback must keep its warning visible")

        invalid_signed_release = deepcopy(release)
        invalid_signed_release["assets"].append(
            {
                "name": "windows-signature-v9.8.7.json",
                "size": 500,
                "url": (
                    "https://github.com/Lowestofttim/catalyst-releases/"
                    "releases/download/v9.8.7/windows-signature-v9.8.7.json"
                ),
                "digest": "sha256:" + "c" * 64,
            }
        )
        invalid_signed_metadata = build_metadata(
            invalid_signed_release,
            "Lowestofttim/catalyst-releases",
            True,
            "windows",
            "installer",
            allow_unsigned_windows_beta=True,
            windows_verifier=fail_verification,
        )
        invalid_signed_windows = invalid_signed_metadata["latest"]["assets"][0]
        if invalid_signed_windows["download_enabled"] is not False:
            raise SystemExit(
                "a release with invalid signing evidence must fail closed instead of falling back to unsigned beta"
            )

        before_replace_failure = output.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("replace failed")):
            try:
                write_metadata_atomic(output, {"value": "new"})
            except OSError:
                pass
            else:
                raise SystemExit("atomic replace failure must propagate")
        if output.read_bytes() != before_replace_failure:
            raise SystemExit("failed atomic replace changed existing metadata")
        leftovers = list(output.parent.glob(f".{output.name}.*.tmp"))
        if leftovers:
            raise SystemExit(f"atomic metadata temp files remain: {leftovers}")

    print("release fallback synchronization check passed")


if __name__ == "__main__":
    main()

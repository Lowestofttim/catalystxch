#!/usr/bin/env python3
"""Validate public release metadata and its website wiring."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "assets" / "release" / "latest.json"
RELEASE_JS = ROOT / "assets" / "release.js"
HTML_FILES = [ROOT / "index.html", ROOT / "docs.html"]
VERSION_RE = re.compile(r"\bv\d+\.\d+\.\d+\b")


def fail(message: str) -> None:
    print(f"release metadata check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_metadata() -> dict:
    if not LATEST_JSON.exists():
        fail(f"missing {LATEST_JSON.relative_to(ROOT)}")
    try:
        data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {LATEST_JSON.relative_to(ROOT)}: {exc}")
    if not isinstance(data, dict):
        fail("metadata root must be an object")
    return data


def validate_metadata(data: dict) -> str:
    required_top = ["schema_version", "source_repo", "generated_at", "downloads_enabled", "latest"]
    for key in required_top:
        if key not in data:
            fail(f"missing top-level field {key!r}")

    if data["source_repo"] != "Lowestofttim/catalyst-releases":
        fail("source_repo must be Lowestofttim/catalyst-releases")

    if not isinstance(data["downloads_enabled"], bool):
        fail("downloads_enabled must be a boolean")

    latest = data["latest"]
    if not isinstance(latest, dict):
        fail("latest must be an object")

    for key in ["version", "name", "published_at", "release_notes", "assets"]:
        if key not in latest:
            fail(f"missing latest.{key}")

    version = latest["version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        fail("latest.version must look like v1.2.3")

    notes = latest["release_notes"]
    if not isinstance(notes, list) or not notes:
        fail("latest.release_notes must be a non-empty list")
    if not all(isinstance(note, str) and note.strip() for note in notes):
        fail("latest.release_notes must contain non-empty strings")

    assets = latest["assets"]
    if not isinstance(assets, list) or not assets:
        fail("latest.assets must be a non-empty list")
    if data["downloads_enabled"] and len(assets) != 1:
        fail("enabled website downloads must expose exactly one Windows installer asset")

    for asset in assets:
        if not isinstance(asset, dict):
            fail("each asset must be an object")
        for key in ["name", "platform", "kind", "size_bytes", "download_url", "sha256"]:
            if key not in asset:
                fail(f"asset is missing {key}")
        if data["downloads_enabled"]:
            if asset["platform"] != "windows" or asset["kind"] != "installer":
                fail("enabled website downloads must expose only the Windows installer")
            if not isinstance(asset["download_url"], str) or not asset["download_url"].startswith(
                "https://github.com/Lowestofttim/catalyst-releases/releases/download/"
            ):
                fail("enabled downloads must use official public CATalyst release URLs")
            if not isinstance(asset["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
                fail("enabled downloads must include a lowercase SHA-256 checksum")
        else:
            if asset["download_url"] is not None:
                fail("download_url must be null while downloads_enabled is false")
            if asset["sha256"] is not None:
                fail("sha256 must be null while downloads_enabled is false")

    return version


def validate_website_wiring(version: str) -> None:
    if not RELEASE_JS.exists():
        fail(f"missing {RELEASE_JS.relative_to(ROOT)}")

    release_js = RELEASE_JS.read_text(encoding="utf-8")
    if "assets/release/latest.json" not in release_js:
        fail("assets/release.js must fetch assets/release/latest.json")
    if ".innerHTML" in release_js:
        fail("assets/release.js must not write release data with innerHTML")
    if "data-download-windows" not in release_js:
        fail("assets/release.js must wire the Windows download button")
    if "https://github.com/Lowestofttim/catalyst-releases/releases/download/" not in release_js:
        fail("assets/release.js must allow only the public CATalyst release download host")

    for html_path in HTML_FILES:
        html = html_path.read_text(encoding="utf-8")
        rel = html_path.relative_to(ROOT)
        if 'src="assets/release.js"' not in html:
            fail(f"{rel} must load assets/release.js")
        if "data-release-version" not in html:
            fail(f"{rel} must contain data-release-version hooks")
        if html_path.name == "index.html" and "data-download-windows" not in html:
            fail("index.html must contain a Windows download link hook")
        if html_path.name == "index.html" and re.search(r"<a\b[^>]*data-download-windows[^>]*\bhref=", html):
            fail("index.html must not hard-code the Windows download href")

        literal_versions = sorted(
            {
                version
                for line in html.splitlines()
                if "data-release" not in line
                for version in VERSION_RE.findall(line)
            }
        )
        stale_versions = [item for item in literal_versions if item != version]
        if stale_versions:
            fail(f"{rel} contains stale literal versions: {', '.join(stale_versions)}")


def main() -> None:
    data = load_metadata()
    version = validate_metadata(data)
    validate_website_wiring(version)
    print(f"release metadata check passed for {version}")


if __name__ == "__main__":
    main()

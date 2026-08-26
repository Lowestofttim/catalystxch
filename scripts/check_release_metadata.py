#!/usr/bin/env python3
"""Validate public release metadata and its website wiring."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "assets" / "release" / "latest.json"
RELEASE_JS = ROOT / "assets" / "release.js"
HTML_FILES = [ROOT / "index.html", ROOT / "docs.html"]
VERSION_RE = re.compile(r"\bv\d+\.\d+\.\d+\b")
HTML_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
PUBLIC_RELEASE_URL_PREFIX = (
    "https://github.com/Lowestofttim/catalyst-releases/releases/download/"
)
BOT_RELEASE_URL_PREFIX = (
    "https://github.com/catalystxch/catalyst-bot/releases/download/"
)
MAC_SOURCE_URL = "https://github.com/catalystxch/catalyst-bot"
DATA_RELEASE_ATTRS = {
    "data-release-download-name",
    "data-release-download-size",
    "data-release-eyebrow",
    "data-release-linux-size",
    "data-release-linux-sha256",
    "data-release-macos-size",
    "data-release-macos-sha256",
    "data-release-meta",
    "data-release-name",
    "data-release-notes",
    "data-release-sha256",
    "data-release-status",
    "data-release-version",
}


def fail(message: str) -> None:
    print(f"release metadata check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class ReleaseFallbackParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records = {attr: [] for attr in DATA_RELEASE_ATTRS}
        self._active = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for frame in self._active:
            frame["depth"] += 1

        attr_names = {name for name, _ in attrs}
        for attr in sorted(DATA_RELEASE_ATTRS & attr_names):
            self._active.append({"attr": attr, "depth": 1, "parts": []})

    def handle_data(self, data: str) -> None:
        for frame in self._active:
            frame["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        del tag
        remaining = []
        for frame in self._active:
            frame["depth"] -= 1
            if frame["depth"] <= 0:
                self.records[frame["attr"]].append(
                    normalize_text("".join(frame["parts"]))
                )
            else:
                remaining.append(frame)
        self._active = remaining


def parse_release_fallbacks(html: str) -> dict[str, list[str]]:
    parser = ReleaseFallbackParser()
    parser.feed(html)
    return parser.records


class VersionLiteralParser(HTMLParser):
    """Collect version literals while ignoring generated release-note content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.versions: set[str] = set()
        self._release_notes_depth = 0

    def _collect(self, value: str | None) -> None:
        if self._release_notes_depth == 0 and value:
            self.versions.update(VERSION_RE.findall(value))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._release_notes_depth:
            if tag not in HTML_VOID_ELEMENTS:
                self._release_notes_depth += 1
            return
        is_release_notes = any(name == "data-release-notes" for name, _ in attrs)
        for name, value in attrs:
            if name != "data-release-notes":
                self._collect(value)
        if is_release_notes:
            if tag not in HTML_VOID_ELEMENTS:
                self._release_notes_depth = 1
            return

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del tag
        if self._release_notes_depth:
            return
        for name, value in attrs:
            if name != "data-release-notes":
                self._collect(value)

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._release_notes_depth:
            self._release_notes_depth -= 1

    def handle_data(self, data: str) -> None:
        self._collect(data)

    def handle_comment(self, data: str) -> None:
        self._collect(data)


def find_stale_literal_versions(html: str, current_version: str) -> list[str]:
    parser = VersionLiteralParser()
    parser.feed(html)
    return sorted(version for version in parser.versions if version != current_version)


def format_date(value: str) -> str:
    if not value:
        return ""
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{date.day} {date.strftime('%b')} {date.year}"


def format_bytes(value: int) -> str:
    if not isinstance(value, int) or value <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    precision = 0 if unit == 0 else 1
    return f"{size:.{precision}f} {units[unit]}"


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
    required_top = [
        "schema_version",
        "source_repo",
        "generated_at",
        "downloads_enabled",
        "latest",
    ]
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
    windows_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and asset.get("platform") == "windows"
        and asset.get("kind") == "installer"
    ]
    if data["downloads_enabled"] and len(windows_assets) != 1:
        fail(
            "enabled website downloads must expose exactly one Windows installer asset"
        )

    for asset in assets:
        if not isinstance(asset, dict):
            fail("each asset must be an object")
        for key in ["name", "platform", "kind", "size_bytes", "download_url", "sha256"]:
            if key not in asset:
                fail(f"asset is missing {key}")
        platform = asset["platform"]
        kind = asset["kind"]
        if platform == "macos":
            fail("website metadata must not expose macOS package download assets")
        if (platform, kind) not in {
            ("windows", "installer"),
            ("linux", "installer"),
            ("linux", "archive"),
        }:
            fail(f"unsupported website download asset: {platform} {kind}")
        if data["downloads_enabled"]:
            expected_prefix = (
                PUBLIC_RELEASE_URL_PREFIX
                if platform == "windows"
                else BOT_RELEASE_URL_PREFIX
            )
            if not isinstance(asset["download_url"], str) or not asset[
                "download_url"
            ].startswith(expected_prefix):
                fail("enabled downloads must use official CATalyst release URLs")
            if not isinstance(asset["sha256"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", asset["sha256"]
            ):
                fail("enabled downloads must include a lowercase SHA-256 checksum")
        else:
            if asset["download_url"] is not None:
                fail("download_url must be null while downloads_enabled is false")
            if asset["sha256"] is not None:
                fail("sha256 must be null while downloads_enabled is false")

    return version


def platform_download_priority(asset: dict, platform: str) -> tuple[int, str]:
    name = str(asset.get("name") or "").lower()
    if platform == "linux":
        if name.endswith(".deb"):
            return (0, name)
        if name.endswith(".appimage"):
            return (1, name)
    return (50, name)


def find_asset(data: dict, platform: str, kind: str) -> dict | None:
    candidates = [
        asset
        for asset in data["latest"]["assets"]
        if asset.get("platform") == platform and asset.get("kind") == kind
    ]
    candidates.sort(key=lambda asset: platform_download_priority(asset, platform))
    return candidates[0] if candidates else None


def find_platform_download(data: dict, platform: str) -> dict | None:
    return find_asset(data, platform, "installer") or find_asset(
        data, platform, "archive"
    )


def validate_fallback_records(
    html_path: Path, html: str, data: dict, version: str
) -> None:
    latest = data["latest"]
    asset = (
        find_asset(data, "windows", "installer") if data["downloads_enabled"] else None
    )
    linux_asset = (
        find_platform_download(data, "linux") if data["downloads_enabled"] else None
    )
    release_date = format_date(latest.get("published_at", ""))
    if asset and linux_asset:
        status = "Windows/Linux downloads available"
    elif asset:
        status = "Windows download available"
    else:
        status = "Public links coming soon"
    channel = "Prerelease" if latest.get("channel") == "prerelease" else "Stable"
    meta = (
        f"{channel} - published {release_date} - {status.lower()}"
        if release_date
        else f"{channel} - {status.lower()}"
    )
    expected = {
        "data-release-version": version,
        "data-release-name": latest["name"],
        "data-release-status": status,
        "data-release-meta": meta,
        "data-release-eyebrow": (
            f"{status} - current release {version}"
            if asset
            else f"Public downloads coming soon - current beta {version}"
        ),
        "data-release-download-name": asset["name"] if asset else "Not available",
        "data-release-download-size": format_bytes(asset["size_bytes"])
        if asset
        else "",
        "data-release-sha256": asset["sha256"] if asset else "Not available",
        "data-release-macos-size": "GitHub source",
        "data-release-linux-size": format_bytes(linux_asset["size_bytes"])
        if linux_asset
        else "",
        "data-release-macos-sha256": "Source only from GitHub",
        "data-release-linux-sha256": linux_asset["sha256"]
        if linux_asset
        else "Not available",
    }

    rel = html_path.relative_to(ROOT)
    fallbacks = parse_release_fallbacks(html)
    for attr, expected_value in expected.items():
        for actual in fallbacks[attr]:
            if actual != expected_value:
                fail(
                    f"{rel} fallback {attr} is {actual!r}, expected {expected_value!r}"
                )

    release_notes = latest["release_notes"]
    for notes_text in fallbacks["data-release-notes"]:
        for note in release_notes:
            if note not in notes_text:
                fail(f"{rel} fallback release notes are missing {note!r}")


def validate_website_wiring(data: dict, version: str) -> None:
    if not RELEASE_JS.exists():
        fail(f"missing {RELEASE_JS.relative_to(ROOT)}")

    release_js = RELEASE_JS.read_text(encoding="utf-8")
    if "assets/release/latest.json" not in release_js:
        fail("assets/release.js must fetch assets/release/latest.json")
    if ".innerHTML" in release_js:
        fail("assets/release.js must not write release data with innerHTML")
    if "data-download-windows" not in release_js:
        fail("assets/release.js must wire the Windows download button")
    if (
        "data-download-macos" not in release_js
        or "data-download-linux" not in release_js
    ):
        fail("assets/release.js must wire macOS source and Linux download buttons")
    if MAC_SOURCE_URL not in release_js:
        fail("assets/release.js must keep macOS pointed at the source repo")
    if PUBLIC_RELEASE_URL_PREFIX not in release_js:
        fail(
            "assets/release.js must allow only the public CATalyst release download host"
        )
    if BOT_RELEASE_URL_PREFIX not in release_js:
        fail(
            "assets/release.js must allow only the public CATalyst bot release host for Linux downloads"
        )

    for html_path in HTML_FILES:
        html = html_path.read_text(encoding="utf-8")
        rel = html_path.relative_to(ROOT)
        if not re.search(r'src="assets/release\.js\?v=[^"]+"', html):
            fail(f"{rel} must load a cache-busted assets/release.js")
        if "data-release-version" not in html:
            fail(f"{rel} must contain data-release-version hooks")
        if html_path.name == "index.html" and "data-download-windows" not in html:
            fail("index.html must contain a Windows download link hook")
        if html_path.name == "index.html" and (
            "data-download-macos" not in html or "data-download-linux" not in html
        ):
            fail("index.html must contain macOS source and Linux download link hooks")
        if html_path.name == "index.html" and MAC_SOURCE_URL not in html:
            fail("index.html must link macOS users to the source repo")
        for attr in ("data-download-windows", "data-download-linux"):
            if html_path.name == "index.html" and re.search(
                rf"<a\b[^>]*{attr}[^>]*\bhref=", html
            ):
                fail(f"index.html must not hard-code the {attr} href")

        stale_versions = find_stale_literal_versions(html, version)
        if stale_versions:
            fail(f"{rel} contains stale literal versions: {', '.join(stale_versions)}")
        validate_fallback_records(html_path, html, data, version)


def main() -> None:
    data = load_metadata()
    version = validate_metadata(data)
    validate_website_wiring(data, version)
    print(f"release metadata check passed for {version}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sync sanitized release metadata from the public CATalyst release repo.

This script uses the local GitHub CLI login. It does not store a token and, by
default, it targets the Windows installer in the public update-channel repo.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from windows_release_verification import (
    ReleaseVerificationError,
    verify_windows_release,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Lowestofttim/catalyst-releases"
DEFAULT_EXPERIMENTAL_REPO = "catalystxch/catalyst-bot"
DEFAULT_OUTPUT = ROOT / "assets" / "release" / "latest.json"
DEFAULT_HTML_FILES = (ROOT / "index.html", ROOT / "docs.html")
GH_FIELDS = "tagName,name,isDraft,isPrerelease,publishedAt,body,assets"


def run_gh(repo: str, tag: str | None) -> dict:
    cmd = ["gh", "release", "view"]
    if tag:
        cmd.append(tag)
    cmd += ["--repo", repo, "--json", GH_FIELDS]

    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        raise SystemExit("gh is not installed or not on PATH")
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise SystemExit(f"gh release view failed: {message}")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"gh returned invalid JSON: {exc}")


def normalize_heading(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    if not match:
        return None
    return re.sub(r"[^a-z0-9]+", " ", match.group(1).lower()).strip()


def clean_bullet(line: str) -> str:
    item = re.sub(r"^\s*[-*]\s+", "", line).strip()
    item = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", item)
    item = re.sub(r"^\[[^\]]+\]\s+", "", item)
    item = re.sub(r"\s+by\s+@[A-Za-z0-9-]+$", "", item)
    item = item.replace("`", "")
    return item


def extract_section_bullets(body: str, wanted_headings: set[str]) -> list[str]:
    current = None
    bullets: list[str] = []
    for line in (body or "").splitlines():
        heading = normalize_heading(line)
        if heading is not None:
            current = heading
            continue
        if current in wanted_headings and re.match(r"^\s*[-*]\s+", line):
            bullet = clean_bullet(line)
            if bullet:
                bullets.append(bullet)
    return bullets


def fallback_notes(body: str) -> list[str]:
    notes: list[str] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^\s*[-*]\s+", stripped):
            stripped = clean_bullet(stripped)
        stripped = stripped.replace("`", "")
        if stripped:
            notes.append(stripped)
        if len(notes) >= 4:
            break
    return notes or ["Release metadata is available; release notes were not provided."]


def classify_platform(name: str) -> str:
    lower = name.lower()
    if "setup" in lower or "windows" in lower or lower.endswith((".exe", ".msi")):
        return "windows"
    if "macos" in lower or "darwin" in lower:
        return "macos"
    if "linux" in lower or lower.endswith((".appimage", ".deb")):
        return "linux"
    return "other"


def classify_kind(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".sha256", ".sig", ".json")):
        return "asset"
    if (
        lower.endswith((".exe", ".msi", ".pkg", ".dmg", ".appimage", ".deb"))
        or "setup" in lower
    ):
        return "installer"
    if lower.endswith((".zip", ".tar.gz", ".tgz")):
        return "archive"
    return "asset"


def sort_asset_key(asset: dict) -> tuple[int, int, int, str]:
    platform_order = {"windows": 0, "macos": 1, "linux": 2, "other": 3}
    kind_order = {"installer": 0, "archive": 1, "asset": 2}
    lower = asset["name"].lower()
    format_order = 50
    if lower.endswith(".dmg"):
        format_order = 0
    elif lower.endswith(".pkg"):
        format_order = 1
    elif lower.endswith(".deb"):
        format_order = 0
    elif lower.endswith(".appimage"):
        format_order = 1
    elif lower.endswith((".zip", ".tar.gz", ".tgz")):
        format_order = 10
    return (
        platform_order.get(asset["platform"], 99),
        kind_order.get(asset["kind"], 99),
        format_order,
        asset["name"].lower(),
    )


def extract_sha256(asset: dict) -> str | None:
    digest = asset.get("digest")
    if not isinstance(digest, str):
        return None
    match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest.strip())
    if not match:
        return None
    return match.group(1).lower()


def should_publish_asset(asset: dict, platform: str, kind: str) -> bool:
    name = asset.get("name")
    if not isinstance(name, str):
        return False
    return classify_platform(name) == platform and classify_kind(name) == kind


def _unavailable_windows_verification() -> dict[str, object]:
    return {
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
    }


def _refresh_download_status(metadata: dict) -> None:
    assets = metadata["latest"]["assets"]
    enabled = sum(asset.get("download_enabled") is True for asset in assets)
    disabled = len(assets) - enabled
    metadata["downloads_enabled"] = enabled > 0
    if enabled and not disabled:
        metadata["download_status"] = "available"
    elif enabled:
        metadata["download_status"] = "partial"
    else:
        metadata["download_status"] = "coming_soon"


def build_metadata(
    release: dict,
    repo: str,
    include_download_urls: bool,
    platform: str,
    kind: str,
    *,
    windows_verifier=verify_windows_release,
) -> dict:
    version = release.get("tagName") or release.get("name")
    if not version:
        raise SystemExit("release is missing tagName")
    if not version.startswith("v"):
        version = f"v{version}"

    body = release.get("body") or ""
    release_notes = extract_section_bullets(
        body, {"what s changed", "whats changed", "changes"}
    )
    verification_notes = extract_section_bullets(body, {"verification"})
    if not release_notes:
        release_notes = fallback_notes(body)

    windows_result = None
    if platform == "windows" and include_download_urls:
        try:
            windows_result = windows_verifier(release)
        except ReleaseVerificationError:
            windows_result = None

    expected_windows_name = f"Catalyst-Setup-{version}.exe"
    assets = []
    for item in release.get("assets") or []:
        if not should_publish_asset(item, platform, kind):
            continue
        name = item.get("name")
        if not name:
            continue
        if platform == "windows" and name != expected_windows_name:
            continue
        sha256 = extract_sha256(item)
        if include_download_urls and not sha256:
            raise SystemExit(f"release asset {name!r} is missing a SHA-256 digest")
        asset = {
            "name": name,
            "platform": classify_platform(name),
            "kind": classify_kind(name),
            "size_bytes": item.get("size") or 0,
            "download_url": item.get("url") if include_download_urls else None,
            "sha256": sha256 if include_download_urls else None,
            "download_enabled": bool(include_download_urls),
        }
        if platform == "windows":
            if windows_result is None:
                asset["download_url"] = None
                asset["sha256"] = None
                asset["download_enabled"] = False
                asset["verification"] = _unavailable_windows_verification()
            else:
                asset["download_enabled"] = (
                    windows_result.get("download_enabled") is True
                )
                asset["verification"] = windows_result["verification"]
        assets.append(asset)
    assets.sort(key=sort_asset_key)
    if not assets:
        raise SystemExit(f"release has no {platform} {kind} asset to publish")

    metadata = {
        "schema_version": 2,
        "source_repo": repo,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "downloads_enabled": False,
        "download_status": "coming_soon",
        "latest": {
            "version": version,
            "name": release.get("name") or version,
            "published_at": release.get("publishedAt"),
            "channel": "prerelease" if release.get("isPrerelease") else "stable",
            "release_notes": release_notes,
            "verification_notes": verification_notes,
            "assets": assets,
        },
    }
    _refresh_download_status(metadata)
    return metadata


def _platform_download_priority(item: dict) -> tuple[int, int, str]:
    name = str(item.get("name") or "")
    lower = name.lower()
    kind = classify_kind(name)
    if kind == "installer":
        kind_priority = 0
    elif kind == "archive":
        kind_priority = 10
    else:
        kind_priority = 99
    format_priority = 50
    if lower.endswith(".dmg"):
        format_priority = 0
    elif lower.endswith(".pkg"):
        format_priority = 1
    elif lower.endswith(".deb"):
        format_priority = 0
    elif lower.endswith(".appimage"):
        format_priority = 1
    elif lower.endswith((".zip", ".tar.gz", ".tgz")):
        format_priority = 10
    return (kind_priority, format_priority, lower)


def append_platform_downloads(
    metadata: dict, release: dict, include_download_urls: bool
) -> None:
    assets = metadata["latest"]["assets"]
    assets[:] = [
        asset for asset in assets if asset.get("platform") not in {"macos", "linux"}
    ]
    seen = {(asset["platform"], asset["kind"], asset["name"]) for asset in assets}
    by_platform = {"linux": []}
    for item in release.get("assets") or []:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        platform = classify_platform(name)
        kind = classify_kind(name)
        if platform != "linux" or kind not in {"installer", "archive"}:
            continue
        by_platform[platform].append(item)

    appended_platforms = set()
    for platform, candidates in by_platform.items():
        if not candidates:
            continue
        candidates.sort(key=_platform_download_priority)
        preferred_kind = classify_kind(str(candidates[0].get("name") or ""))
        selected = [
            item
            for item in candidates
            if classify_kind(str(item.get("name") or "")) == preferred_kind
        ]
        for item in selected:
            name = item.get("name")
            if not isinstance(name, str):
                continue
            kind = classify_kind(name)
            key = (platform, kind, name)
            if key in seen:
                continue
            sha256 = extract_sha256(item)
            if include_download_urls and not sha256:
                raise SystemExit(f"release asset {name!r} is missing a SHA-256 digest")
            assets.append(
                {
                    "name": name,
                    "platform": platform,
                    "kind": kind,
                    "size_bytes": item.get("size") or 0,
                    "download_url": item.get("url") if include_download_urls else None,
                    "sha256": sha256 if include_download_urls else None,
                    "download_enabled": bool(include_download_urls),
                }
            )
            appended_platforms.add(platform)
    assets.sort(key=sort_asset_key)
    if appended_platforms != {"linux"}:
        raise SystemExit("release is missing Linux platform download assets")
    _refresh_download_status(metadata)


def append_experimental_archives(
    metadata: dict, release: dict, include_download_urls: bool
) -> None:
    append_platform_downloads(metadata, release, include_download_urls)


def _format_date(value: str) -> str:
    if not value:
        return ""
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{date.day} {date.strftime('%b')} {date.year}"


def _format_bytes(value: int) -> str:
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


def _find_platform_download(metadata: dict, platform: str) -> dict | None:
    candidates = [
        asset
        for asset in metadata["latest"]["assets"]
        if asset.get("platform") == platform
        and asset.get("kind") in {"installer", "archive"}
        and asset.get("download_enabled") is True
    ]
    candidates.sort(key=_platform_download_priority)
    return candidates[0] if candidates else None


def _replace_release_text(html_text: str, attribute: str, value: str) -> str:
    pattern = re.compile(
        rf"(?P<open><(?P<tag>[A-Za-z][\w:-]*)\b"
        rf"(?=[^>]*\b{re.escape(attribute)}(?:\s|=|/?>))[^>]*>)"
        rf"(?P<content>.*?)"
        rf"(?P<close></(?P=tag)\s*>)",
        re.DOTALL,
    )
    escaped = html.escape(value, quote=False)
    return pattern.sub(
        lambda match: f"{match.group('open')}{escaped}{match.group('close')}",
        html_text,
    )


def _replace_release_notes(html_text: str, notes: list[str]) -> str:
    pattern = re.compile(
        r"(?P<open><(?P<tag>[A-Za-z][\w:-]*)\b"
        r"(?=[^>]*\bdata-release-notes(?:\s|=|/?>))[^>]*>)"
        r"(?P<content>.*?)"
        r"(?P<close></(?P=tag)\s*>)",
        re.DOTALL,
    )

    def replace(match: re.Match) -> str:
        current = match.group("content")
        item_indent_match = re.search(r"\n([ \t]*)<", current)
        closing_indent_match = re.search(r"\n([ \t]*)\Z", current)
        if item_indent_match:
            item_indent = item_indent_match.group(1)
            closing_indent = (
                closing_indent_match.group(1) if closing_indent_match else ""
            )
            items = "\n".join(
                f"{item_indent}<li>{html.escape(note, quote=False)}</li>"
                for note in notes
            )
            content = f"\n{items}\n{closing_indent}"
        else:
            content = "".join(
                f"<li>{html.escape(note, quote=False)}</li>" for note in notes
            )
        return f"{match.group('open')}{content}{match.group('close')}"

    return pattern.sub(replace, html_text)


def render_release_fallbacks(html_text: str, metadata: dict) -> str:
    """Render safe static fallbacks matching the synchronized release metadata."""

    latest = metadata["latest"]
    windows = _find_platform_download(metadata, "windows")
    linux = _find_platform_download(metadata, "linux")
    if windows and linux:
        status = "Windows/Linux downloads available"
    elif windows:
        status = "Windows download available"
    elif linux:
        status = "Linux download available"
    else:
        status = "Public links coming soon"
    channel = "Prerelease" if latest.get("channel") == "prerelease" else "Stable"
    release_date = _format_date(latest.get("published_at", ""))
    meta = (
        f"{channel} - published {release_date} - {status.lower()}"
        if release_date
        else f"{channel} - {status.lower()}"
    )
    values = {
        "data-release-version": latest["version"],
        "data-release-name": latest["name"],
        "data-release-status": status,
        "data-release-meta": meta,
        "data-release-eyebrow": (
            f"{status} - current release {latest['version']}"
            if windows
            else f"Public downloads coming soon - current beta {latest['version']}"
        ),
        "data-release-download-name": windows["name"] if windows else "Not available",
        "data-release-download-size": _format_bytes(windows["size_bytes"])
        if windows
        else "",
        "data-release-sha256": windows["sha256"] if windows else "Not available",
        "data-release-windows-signature": (
            "Verified publisher: SignPath Foundation"
            if windows
            else "Windows installer unavailable - signature verification required"
        ),
        "data-release-macos-size": "GitHub source",
        "data-release-macos-sha256": "Source only from GitHub",
        "data-release-linux-size": _format_bytes(linux["size_bytes"]) if linux else "",
        "data-release-linux-sha256": linux["sha256"] if linux else "Not available",
    }
    rendered = html_text
    for attribute, value in values.items():
        rendered = _replace_release_text(rendered, attribute, value)
    return _replace_release_notes(rendered, latest["release_notes"])


def sync_html_fallbacks(metadata: dict) -> None:
    for path in DEFAULT_HTML_FILES:
        current = path.read_text(encoding="utf-8")
        rendered = render_release_fallbacks(current, metadata)
        if rendered != current:
            path.write_text(rendered, encoding="utf-8")
            print(f"updated {path.relative_to(ROOT)} release fallbacks")


def preserve_generated_at_if_unchanged(metadata: dict, existing: dict) -> None:
    """Avoid no-op commits when a scheduled sync sees the same release again."""

    if not isinstance(existing, dict):
        return
    current_without_time = {
        key: value for key, value in metadata.items() if key != "generated_at"
    }
    existing_without_time = {
        key: value for key, value in existing.items() if key != "generated_at"
    }
    existing_time = existing.get("generated_at")
    if current_without_time == existing_without_time and isinstance(existing_time, str):
        metadata["generated_at"] = existing_time


def write_metadata_atomic(output: Path, metadata: dict) -> None:
    """Atomically replace release metadata without leaving trusted-looking debris."""

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(metadata, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(output)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"source GitHub repo, default: {DEFAULT_REPO}",
    )
    parser.add_argument(
        "--experimental-repo",
        default=DEFAULT_EXPERIMENTAL_REPO,
        help=f"source GitHub repo for Linux platform downloads, default: {DEFAULT_EXPERIMENTAL_REPO}",
    )
    parser.add_argument(
        "--tag", default=None, help="specific release tag; omitted means latest release"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="metadata JSON output path"
    )
    parser.add_argument(
        "--platform",
        default="windows",
        choices=["windows"],
        help="download platform to publish",
    )
    parser.add_argument(
        "--kind",
        default="installer",
        choices=["installer"],
        help="download asset kind to publish",
    )
    parser.add_argument(
        "--include-download-urls",
        action="store_true",
        help="include GitHub asset URLs in JSON; leave off while downloads are coming soon",
    )
    parser.add_argument(
        "--include-experimental-archives",
        action="store_true",
        help="legacy alias for --include-platform-downloads",
    )
    parser.add_argument(
        "--include-platform-downloads",
        action="store_true",
        help="include first-class Linux platform downloads from --experimental-repo, falling back to archives when needed",
    )
    parser.add_argument(
        "--update-html-fallbacks",
        action="store_true",
        help="update index.html and docs.html static fallbacks to match the metadata",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    release = run_gh(args.repo, args.tag)
    if release.get("isDraft"):
        raise SystemExit("refusing to publish metadata for a draft release")

    metadata = build_metadata(
        release, args.repo, args.include_download_urls, args.platform, args.kind
    )
    if args.include_platform_downloads or args.include_experimental_archives:
        platform_release = run_gh(args.experimental_repo, metadata["latest"]["version"])
        if platform_release.get("isDraft"):
            raise SystemExit(
                "refusing to publish metadata for a draft platform release"
            )
        append_platform_downloads(
            metadata, platform_release, args.include_download_urls
        )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = None
        preserve_generated_at_if_unchanged(metadata, existing)
    write_metadata_atomic(output, metadata)
    if args.update_html_fallbacks:
        sync_html_fallbacks(metadata)
    try:
        display_output = output.relative_to(ROOT)
    except ValueError:
        display_output = output
    print(f"wrote {display_output} for {metadata['latest']['version']}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)

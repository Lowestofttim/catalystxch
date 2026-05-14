#!/usr/bin/env python3
"""Sync sanitized release metadata from the public CATalyst release repo.

This script uses the local GitHub CLI login. It does not store a token and, by
default, it targets the Windows installer in the public update-channel repo.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Lowestofttim/catalyst-releases"
DEFAULT_EXPERIMENTAL_REPO = "catalystxch/catalyst-bot"
DEFAULT_OUTPUT = ROOT / "assets" / "release" / "latest.json"
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
    if "linux" in lower:
        return "linux"
    return "other"


def classify_kind(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".sha256", ".sig")) or lower.endswith(".json"):
        return "asset"
    if lower.endswith((".exe", ".msi", ".pkg", ".dmg")) or "setup" in lower:
        return "installer"
    if lower.endswith((".zip", ".tar.gz", ".tgz")):
        return "archive"
    return "asset"


def sort_asset_key(asset: dict) -> tuple[int, int, str]:
    platform_order = {"windows": 0, "macos": 1, "linux": 2, "other": 3}
    kind_order = {"installer": 0, "archive": 1, "asset": 2}
    return (
        platform_order.get(asset["platform"], 99),
        kind_order.get(asset["kind"], 99),
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


def build_metadata(release: dict, repo: str, include_download_urls: bool, platform: str, kind: str) -> dict:
    version = release.get("tagName") or release.get("name")
    if not version:
        raise SystemExit("release is missing tagName")
    if not version.startswith("v"):
        version = f"v{version}"

    body = release.get("body") or ""
    release_notes = extract_section_bullets(body, {"what s changed", "whats changed", "changes"})
    verification_notes = extract_section_bullets(body, {"verification"})
    if not release_notes:
        release_notes = fallback_notes(body)

    assets = []
    for item in release.get("assets") or []:
        if not should_publish_asset(item, platform, kind):
            continue
        name = item.get("name")
        if not name:
            continue
        sha256 = extract_sha256(item)
        if include_download_urls and not sha256:
            raise SystemExit(f"release asset {name!r} is missing a SHA-256 digest")
        assets.append(
            {
                "name": name,
                "platform": classify_platform(name),
                "kind": classify_kind(name),
                "size_bytes": item.get("size") or 0,
                "download_url": item.get("url") if include_download_urls else None,
                "sha256": sha256 if include_download_urls else None,
            }
        )
    assets.sort(key=sort_asset_key)
    if not assets:
        raise SystemExit(f"release has no {platform} {kind} asset to publish")

    downloads_enabled = bool(include_download_urls)

    return {
        "schema_version": 1,
        "source_repo": repo,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "downloads_enabled": downloads_enabled,
        "download_status": "available" if downloads_enabled else "coming_soon",
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


def append_experimental_archives(metadata: dict, release: dict, include_download_urls: bool) -> None:
    assets = metadata["latest"]["assets"]
    seen = {(asset["platform"], asset["kind"], asset["name"]) for asset in assets}
    appended = 0
    for item in release.get("assets") or []:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        platform = classify_platform(name)
        kind = classify_kind(name)
        if platform not in {"macos", "linux"} or kind != "archive":
            continue
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
            }
        )
        appended += 1
    assets.sort(key=sort_asset_key)
    if appended < 2:
        raise SystemExit("experimental release is missing macOS or Linux archive assets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"source GitHub repo, default: {DEFAULT_REPO}")
    parser.add_argument(
        "--experimental-repo",
        default=DEFAULT_EXPERIMENTAL_REPO,
        help=f"source GitHub repo for macOS/Linux archives, default: {DEFAULT_EXPERIMENTAL_REPO}",
    )
    parser.add_argument("--tag", default=None, help="specific release tag; omitted means latest release")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="metadata JSON output path")
    parser.add_argument("--platform", default="windows", choices=["windows"], help="download platform to publish")
    parser.add_argument("--kind", default="installer", choices=["installer"], help="download asset kind to publish")
    parser.add_argument(
        "--include-download-urls",
        action="store_true",
        help="include GitHub asset URLs in JSON; leave off while downloads are coming soon",
    )
    parser.add_argument(
        "--include-experimental-archives",
        action="store_true",
        help="include experimental macOS and Linux archives from --experimental-repo",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    release = run_gh(args.repo, args.tag)
    if release.get("isDraft"):
        raise SystemExit("refusing to publish metadata for a draft release")

    metadata = build_metadata(release, args.repo, args.include_download_urls, args.platform, args.kind)
    if args.include_experimental_archives:
        experimental = run_gh(args.experimental_repo, metadata["latest"]["version"])
        if experimental.get("isDraft"):
            raise SystemExit("refusing to publish metadata for a draft experimental release")
        append_experimental_archives(metadata, experimental, args.include_download_urls)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
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

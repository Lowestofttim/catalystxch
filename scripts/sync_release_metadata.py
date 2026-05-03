#!/usr/bin/env python3
"""Sync sanitized release metadata from the private app repo.

This script uses the local GitHub CLI login. It does not store a token and, by
default, it does not publish download URLs while the website is in coming-soon
mode.
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
DEFAULT_REPO = "Lowestofttim/catalyst-bot"
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


def build_metadata(release: dict, repo: str, include_download_urls: bool) -> dict:
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
        name = item.get("name")
        if not name:
            continue
        assets.append(
            {
                "name": name,
                "platform": classify_platform(name),
                "kind": classify_kind(name),
                "size_bytes": item.get("size") or 0,
                "download_url": item.get("url") if include_download_urls else None,
                "sha256": None,
            }
        )
    assets.sort(key=sort_asset_key)

    return {
        "schema_version": 1,
        "source_repo": repo,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"source GitHub repo, default: {DEFAULT_REPO}")
    parser.add_argument("--tag", default=None, help="specific release tag; omitted means latest release")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="metadata JSON output path")
    parser.add_argument(
        "--include-download-urls",
        action="store_true",
        help="include GitHub asset URLs in JSON; leave off while downloads are coming soon",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    release = run_gh(args.repo, args.tag)
    if release.get("isDraft"):
        raise SystemExit("refusing to publish metadata for a draft release")

    metadata = build_metadata(release, args.repo, args.include_download_urls)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)} for {metadata['latest']['version']}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)

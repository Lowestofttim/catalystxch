#!/usr/bin/env python3
"""Regression check for release-metadata HTML fallback synchronization."""

from __future__ import annotations

from copy import deepcopy

from check_release_metadata import find_stale_literal_versions
from sync_release_metadata import (
    preserve_generated_at_if_unchanged,
    render_release_fallbacks,
)


def main() -> None:
    metadata = {
        "downloads_enabled": True,
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
                    "sha256": "a" * 64,
                },
                {
                    "name": "catalyst_v9.8.7_amd64.deb",
                    "platform": "linux",
                    "kind": "installer",
                    "size_bytes": 199_062_594,
                    "sha256": "b" * 64,
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
  <span data-release-linux-size>2 MB</span>
  <span data-release-linux-sha256>old-linux-sha</span>
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

    release_note_history = """<main>
  <span data-release-version>v9.8.7</span>
  <ul data-release-notes><li>Fix v9.8.6 startup migration</li></ul>
</main>
"""
    if find_stale_literal_versions(release_note_history, "v9.8.7"):
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
        stale_after_void_note_element, "v9.8.7"
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
        stale_note_container_attribute, "v9.8.7"
    ) != ["v9.8.6"]:
        raise SystemExit(
            "stale attributes on release-note containers must still be rejected"
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

    print("release fallback synchronization check passed")


if __name__ == "__main__":
    main()

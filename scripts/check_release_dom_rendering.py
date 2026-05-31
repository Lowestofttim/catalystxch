"""Browser-check the rendered website release panel."""

from __future__ import annotations

import json
import os
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
MAC_SOURCE_URL = "https://github.com/catalystxch/catalyst-bot"


def serve_site() -> tuple[ThreadingHTTPServer, str]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ROOT, **kwargs)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/index.html"


def main() -> None:
    metadata = json.loads((ROOT / "assets" / "release" / "latest.json").read_text(encoding="utf-8"))
    enabled_latest = metadata["latest"]
    enabled_installer = next(
        asset
        for asset in enabled_latest["assets"]
        if asset["platform"] == "windows" and asset["kind"] == "installer"
    )
    disabled_metadata = {
        **metadata,
        "downloads_enabled": False,
        "download_status": "coming_soon",
        "latest": {
            **enabled_latest,
            "assets": [
                {
                    **enabled_installer,
                    "download_url": None,
                    "sha256": None,
                }
            ],
        },
    }

    server = None
    url = os.environ.get("CATALYST_SITE_URL")
    if not url:
        server, url = serve_site()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 900})
                page.goto(url, wait_until="networkidle")
                assert_release_panel(page, metadata)

                disabled_page = browser.new_page(viewport={"width": 390, "height": 900})
                disabled_page.route(
                    "**/assets/release/latest.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(disabled_metadata),
                    ),
                )
                disabled_page.goto(url, wait_until="networkidle")
                assert_release_panel(disabled_page, disabled_metadata)

            finally:
                browser.close()
    finally:
        if server:
            server.shutdown()

    print(f"release DOM rendering check passed for {enabled_latest['version']}")


def find_windows_installer(latest: dict) -> dict | None:
    return next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == "windows" and asset["kind"] == "installer"
        ),
        None,
    )


def find_platform_download(latest: dict, platform: str) -> dict | None:
    return next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == platform and asset["kind"] == "installer"
        ),
        None,
    ) or next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == platform and asset["kind"] == "archive"
        ),
        None,
    )


def assert_release_panel(page, metadata: dict) -> None:
    latest = metadata["latest"]
    installer = find_windows_installer(latest)
    linux = find_platform_download(latest, "linux")
    downloads_available = bool(metadata["downloads_enabled"] and installer and installer["download_url"])
    linux_available = bool(metadata["downloads_enabled"] and linux and linux["download_url"])

    expect(page.locator("[data-release-eyebrow]")).to_contain_text(latest["version"])
    expect(page.locator("#download [data-release-version]")).to_have_text(latest["version"])
    expect(page.locator("#download [data-release-name]")).to_have_text(latest["name"])
    expect(page.locator("#download [data-release-meta]")).to_contain_text(
        "windows/linux downloads available"
        if downloads_available and linux_available
        else "windows download available"
        if downloads_available
        else "public links coming soon"
    )
    download_link = page.locator("[data-download-windows]")
    macos_link = page.locator("[data-download-macos]")
    linux_link = page.locator("[data-download-linux]")
    if downloads_available:
        expect(download_link).not_to_have_attribute("aria-disabled", "true")
        expect(macos_link).not_to_have_attribute("aria-disabled", "true")
        if linux_available:
            expect(linux_link).not_to_have_attribute("aria-disabled", "true")
        else:
            expect(linux_link).to_have_attribute("aria-disabled", "true")
    else:
        expect(download_link).to_have_attribute("aria-disabled", "true")
        expect(macos_link).not_to_have_attribute("aria-disabled", "true")
        expect(linux_link).to_have_attribute("aria-disabled", "true")
    expect(macos_link).to_have_attribute("href", MAC_SOURCE_URL)

    if downloads_available:
        expect(page.locator("#download [data-release-download-name]")).to_have_text(installer["name"])
        expect(page.locator("#download [data-release-sha256]")).to_have_text(installer["sha256"])
        if linux:
            expect(linux_link).to_have_attribute("href", linux["download_url"])
    else:
        expect(page.locator("#download [data-release-download-name]")).to_have_text("Not available")
        expect(page.locator("#download [data-release-sha256]")).to_have_text("Not available")

    notes = page.locator("#download [data-release-notes] li")
    expect(notes).to_have_count(len(latest["release_notes"]))
    for index, note in enumerate(latest["release_notes"]):
        expect(notes.nth(index)).to_have_text(note)


if __name__ == "__main__":
    main()

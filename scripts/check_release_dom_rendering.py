"""Browser-check the rendered website release panel."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MAC_SOURCE_URL = "https://github.com/catalystxch/catalyst-bot"
RELEASE_JS_ASSET = "assets/release.js?v=20260903-v1.3.19"


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
    metadata = json.loads(
        (ROOT / "assets" / "release" / "latest.json").read_text(encoding="utf-8")
    )
    enabled_latest = metadata["latest"]
    enabled_installer = next(
        asset
        for asset in enabled_latest["assets"]
        if asset["platform"] == "windows" and asset["kind"] == "installer"
    )
    installer_name = enabled_installer["name"]
    installer_tag_match = re.fullmatch(
        r"Catalyst-Setup-(v\d+\.\d+\.\d+)\.exe", installer_name
    )
    assert installer_tag_match, f"unexpected Windows installer name: {installer_name}"
    installer_tag = installer_tag_match.group(1)
    release_base = (
        "https://github.com/Lowestofttim/catalyst-releases/releases/"
        f"download/{installer_tag}"
    )
    verified_installer = {
        **enabled_installer,
        "download_url": f"{release_base}/{installer_name}",
        "sha256": "a" * 64,
        "download_enabled": True,
        "distribution_status": None,
        "verification": {
            "authenticode_status": "valid",
            "publisher": "SignPath Foundation",
            "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
            "signer_thumbprint": "A" * 40,
            "timestamp_status": "valid",
            "update_manifest_status": "valid",
            "update_manifest_url": f"{release_base}/latest.json",
            "update_manifest_signature_url": f"{release_base}/latest.json.sig",
            "evidence_url": f"{release_base}/windows-signature-{installer_tag}.json",
            "evidence_sha256": "c" * 64,
        },
    }
    verified_metadata = {
        **metadata,
        "downloads_enabled": True,
        "download_status": "available",
        "latest": {
            **enabled_latest,
            "assets": [
                verified_installer if asset is enabled_installer else asset
                for asset in enabled_latest["assets"]
            ],
        },
    }
    unsigned_installer = {
        **enabled_installer,
        "download_url": f"{release_base}/{installer_name}",
        "sha256": "b" * 64,
        "download_enabled": True,
        "distribution_status": "unsigned_beta",
        "verification": {
            "authenticode_status": "unsigned",
            "publisher": None,
            "signer_subject": None,
            "signer_thumbprint": None,
            "timestamp_status": "unavailable",
            "update_manifest_status": "valid",
            "update_manifest_url": f"{release_base}/latest.json",
            "update_manifest_signature_url": f"{release_base}/latest.json.sig",
            "evidence_url": None,
            "evidence_sha256": None,
        },
    }
    unsigned_metadata = {
        **metadata,
        "downloads_enabled": True,
        "download_status": "available",
        "latest": {
            **enabled_latest,
            "assets": [
                unsigned_installer if asset is enabled_installer else asset
                for asset in enabled_latest["assets"]
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
                assert_release_script_cache_key(page)
                assert_release_panel(page, metadata)

                docs_page = browser.new_page(viewport={"width": 390, "height": 900})
                docs_page.goto(urljoin(url, "docs.html"), wait_until="networkidle")
                assert_release_script_cache_key(docs_page)

                verified_page = browser.new_page(viewport={"width": 390, "height": 900})
                verified_page.route(
                    "**/assets/release/latest.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(verified_metadata),
                    ),
                )
                verified_page.goto(url, wait_until="networkidle")
                assert_release_panel(verified_page, verified_metadata)

                unsigned_page = browser.new_page(viewport={"width": 390, "height": 900})
                unsigned_page.route(
                    "**/assets/release/latest.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(unsigned_metadata),
                    ),
                )
                unsigned_page.goto(url, wait_until="networkidle")
                assert_release_panel(unsigned_page, unsigned_metadata)

            finally:
                browser.close()
    finally:
        if server:
            server.shutdown()

    print(f"release DOM rendering check passed for {enabled_latest['version']}")


def assert_release_script_cache_key(page) -> None:
    expect(page.locator('script[src^="assets/release.js"]')).to_have_attribute(
        "src", RELEASE_JS_ASSET
    )


def find_windows_installer(latest: dict) -> dict | None:
    return next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == "windows"
            and asset["kind"] == "installer"
            and asset.get("download_enabled") is True
            and (
                (
                    asset.get("verification", {}).get("authenticode_status") == "valid"
                    and asset.get("verification", {}).get("publisher") == "SignPath Foundation"
                    and asset.get("verification", {}).get("timestamp_status") == "valid"
                    and asset.get("verification", {}).get("update_manifest_status") == "valid"
                )
                or (
                    asset.get("distribution_status") == "unsigned_beta"
                    and asset.get("verification", {}).get("authenticode_status") == "unsigned"
                    and asset.get("verification", {}).get("publisher") is None
                )
            )
        ),
        None,
    )


def find_platform_download(latest: dict, platform: str) -> dict | None:
    return next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == platform
            and asset["kind"] == "installer"
            and asset.get("download_enabled") is True
        ),
        None,
    ) or next(
        (
            asset
            for asset in latest["assets"]
            if asset["platform"] == platform
            and asset["kind"] == "archive"
            and asset.get("download_enabled") is True
        ),
        None,
    )


def assert_release_panel(page, metadata: dict) -> None:
    latest = metadata["latest"]
    installer = find_windows_installer(latest)
    linux = find_platform_download(latest, "linux")
    downloads_available = bool(installer and installer["download_url"])
    unsigned_beta = bool(
        installer and installer.get("distribution_status") == "unsigned_beta"
    )
    linux_available = bool(linux and linux["download_url"])

    expect(page.locator("[data-release-eyebrow]")).to_contain_text(latest["version"])
    expect(page.locator("#download [data-release-version]")).to_have_text(
        latest["version"]
    )
    expect(page.locator("#download [data-release-name]")).to_have_text(latest["name"])
    expect(page.locator("#download [data-release-meta]")).to_contain_text(
        "windows/linux downloads available"
        if downloads_available and linux_available
        else "windows download available"
        if downloads_available
        else "linux download available"
        if linux_available
        else "public links coming soon"
    )
    download_link = page.locator("[data-download-windows]")
    macos_link = page.locator("[data-download-macos]")
    linux_link = page.locator("[data-download-linux]")
    windows_notice = page.locator("[data-windows-download-notice]")
    expect(windows_notice).to_have_count(1)
    if downloads_available:
        if unsigned_beta:
            expect(windows_notice).to_be_visible()
            expect(page.locator("[data-windows-download-notice-title]")).to_have_text(
                "Unsigned Windows beta"
            )
            expect(page.locator("[data-windows-download-notice-body]")).to_contain_text(
                "Windows protected your PC"
            )
            expect(page.locator("[data-windows-download-notice-body]")).to_contain_text(
                "Do not continue"
            )
        else:
            expect(windows_notice).to_be_hidden()
        expect(download_link).not_to_have_attribute("aria-disabled", "true")
        expect(macos_link).not_to_have_attribute("aria-disabled", "true")
        if linux_available:
            expect(linux_link).not_to_have_attribute("aria-disabled", "true")
        else:
            expect(linux_link).to_have_attribute("aria-disabled", "true")
    else:
        expect(windows_notice).to_be_visible()
        expect(download_link).to_have_attribute("aria-disabled", "true")
        expect(macos_link).not_to_have_attribute("aria-disabled", "true")
        if linux_available:
            expect(linux_link).not_to_have_attribute("aria-disabled", "true")
        else:
            expect(linux_link).to_have_attribute("aria-disabled", "true")
    expect(macos_link).to_have_attribute("href", MAC_SOURCE_URL)

    if downloads_available:
        expect(page.locator("#download [data-release-download-name]")).to_have_text(
            installer["name"]
        )
        expect(page.locator("#download [data-release-sha256]")).to_have_text(
            installer["sha256"]
        )
        if linux:
            expect(linux_link).to_have_attribute("href", linux["download_url"])
    else:
        expect(page.locator("#download [data-release-download-name]")).to_have_text(
            "Not available"
        )
        expect(page.locator("#download [data-release-sha256]")).to_have_text(
            "Not available"
        )
        expect(download_link).not_to_have_attribute("href", re.compile(r".+"))

    expect(page.locator("[data-release-windows-signature]")).to_have_text(
        "Unsigned beta - expect a Windows SmartScreen warning"
        if unsigned_beta
        else "Verified publisher: SignPath Foundation"
        if downloads_available
        else "Windows installer unavailable - signature verification required"
    )
    if linux_available:
        expect(linux_link).to_have_attribute("href", linux["download_url"])

    notes = page.locator("#download [data-release-notes] li")
    expect(notes).to_have_count(len(latest["release_notes"]))
    for index, note in enumerate(latest["release_notes"]):
        expect(notes.nth(index)).to_have_text(note)


if __name__ == "__main__":
    main()

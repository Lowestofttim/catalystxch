#!/usr/bin/env python3
"""Check that release sync respects protected main and redeploys Pages."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sync-release-metadata.yml"


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required = {
        "ref: main": "an explicit trusted main checkout for manual dispatches",
        "persist-credentials: false": "credential isolation during third-party validation",
        "pull-requests: write": "permission to create the protected-branch PR",
        "pages: write": "permission to trigger the Pages rebuild",
        "playwright==1.60.0": "a pinned browser-test dependency",
        "python -m playwright install --with-deps chromium": "the Chromium browser used by the DOM check",
        'node-version: "24"': "a runtime supported by html-validate 11.4.0",
        "html-validate@11.4.0": "a pinned HTML validator",
        "gh auth setup-git": "post-validation Git authentication",
        "automation/sync-release-metadata": "dedicated automation branch",
        "gh pr create": "protected-branch pull request creation",
        "gh pr merge --squash --delete-branch": "automatic protected-branch merge",
        "catalystxch.com/assets/release/latest.json": "public deployment freshness detection",
        "--retry 3": "transient public-site request retrying",
        "Rebuild Pages when the public release is stale": "independently retryable Pages deployment",
        "repos/${{ github.repository }}/pages/builds": "explicit Pages rebuild",
        "sudo apt-get install -y osslsigncode": "the independent Authenticode verifier",
        "python scripts/check_windows_release_verification.py": "pure Windows release verifier regression checks",
        "windows-signature-": "the signed evidence companion asset",
    }
    for marker, purpose in required.items():
        if marker not in workflow:
            raise SystemExit(f"sync workflow is missing {purpose}: {marker}")
    if re.search(r"(?m)^\s*git push\s*$", workflow):
        raise SystemExit("sync workflow must not push directly to protected main")
    if re.search(r"uses:\s*actions/[^@\s]+@v\d+", workflow):
        raise SystemExit("first-party actions must use immutable commit SHAs")
    install_index = workflow.index("Install independent Authenticode verifier")
    sync_index = workflow.index("Sync the latest public release")
    metadata_index = workflow.index("Verify release metadata and website rendering")
    if not install_index < sync_index < metadata_index:
        raise SystemExit("Authenticode tooling, sync, and metadata checks are misordered")
    print("protected-branch release sync workflow check passed")


if __name__ == "__main__":
    main()

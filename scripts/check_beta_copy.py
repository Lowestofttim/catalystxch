"""Keep release copy consistent with Dexie and optional Splash publication."""

import json
from pathlib import Path

from sync_release_metadata import render_release_fallbacks


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    metadata = json.loads((ROOT / "assets/release/latest.json").read_text(encoding="utf-8"))
    homepage = render_release_fallbacks(
        (ROOT / "index.html").read_text(encoding="utf-8"), metadata
    ).lower()
    guide = render_release_fallbacks(
        (ROOT / "beta-guide.html").read_text(encoding="utf-8"), metadata
    ).lower()
    if metadata["latest"]["channel"] == "prerelease":
        if "new dexie only beta testing" not in homepage or "new dexie only beta testing" not in guide:
            raise SystemExit("Both current beta pages must identify the tester beta")
    elif "stable release" not in homepage or "stable release" not in guide:
        raise SystemExit("Both current stable pages must identify the stable release")
    if "optional splash" not in homepage or "optional splash" not in guide:
        raise SystemExit("Both current beta pages must describe Splash as optional")
    if "dexie-only" in homepage or "dexie-only" in guide:
        raise SystemExit("Current release pages must not describe the build as Dexie-only")
    if "peer delivery needs separate verification" not in homepage:
        raise SystemExit("Homepage must not imply local Splash acceptance proves peer delivery")
    if "exact offer rediscovery" not in guide:
        raise SystemExit("Setup guide must require exact offer rediscovery for Splash reach")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

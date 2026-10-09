"""Keep beta copy consistent with Dexie and optional Splash publication."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    homepage = (ROOT / "index.html").read_text(encoding="utf-8").lower()
    guide = (ROOT / "beta-guide.html").read_text(encoding="utf-8").lower()
    if "v1.4 beta" not in homepage or "v1.4 beta" not in guide:
        raise SystemExit("Both current beta pages must identify the v1.4 beta")
    if "optional splash" not in homepage or "optional splash" not in guide:
        raise SystemExit("Both current beta pages must describe Splash as optional")
    if "dexie-only" in homepage or "dexie-only" in guide:
        raise SystemExit("Current beta pages must not describe the build as Dexie-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

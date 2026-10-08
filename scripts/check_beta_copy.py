"""Keep current beta marketing copy consistent with Dexie-only operation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    homepage = (ROOT / "index.html").read_text(encoding="utf-8").lower()
    guide = (ROOT / "beta-guide.html").read_text(encoding="utf-8").lower()
    if "dexie-only beta" not in homepage or "dexie-only beta" not in guide:
        raise SystemExit("Both current beta pages must identify the Dexie-only beta")
    for retired_claim in ("splash p2p broadcast", "visibility beyond dexie"):
        if retired_claim in homepage or retired_claim in guide:
            raise SystemExit(f"Retired feature is advertised in beta copy: {retired_claim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

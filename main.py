"""Run from a fresh checkout without installing a package."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from textpack.cli import main
    raise SystemExit(main())

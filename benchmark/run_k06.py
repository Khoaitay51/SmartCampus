"""Keep the original K06 command and pilot defaults."""

import sys
from pathlib import Path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    from experiment.run_approval import main

    raise SystemExit(main(
        default_manifest=root / "benchmark/k06_cases.csv",
        default_cases=["K06-01", "K06-02"],
    ))

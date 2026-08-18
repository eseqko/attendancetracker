"""CLI wrapper: generate the synthetic demo dataset.

Usage:
    python scripts/generate_sample_data.py --outdir sample_data --seed 42
"""

from __future__ import annotations

import argparse

from attendance_tracker.sample_data import write_demo_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="sample_data")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    written = write_demo_files(args.outdir, seed=args.seed)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()

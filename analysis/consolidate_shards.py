#!/usr/bin/env python3
"""
Merges a results directory's many per-chunk elo_results_<format>_shard*.jsonl
files down to a fixed number of shard files per format (default: 10, matching
results/current's long-standing layout).

Background: remote tournament runs are now split into many small chunks
(e.g. 300 per format) for parallelism across droplets, which is a much finer
grain than the 10-shard-per-format layout every other results/ zone and every
analysis/ script's file-count assumptions were built around. This script
exists to fold a freshly-pulled results/remote/ chunk set back down to that
shape before promoting it to results/current/, rather than promoting 300
files per format directly.

Rows are concatenated in shard-index order and split evenly across the
target file count -- there's no identity tying a row to its original chunk
index, so which output file a row lands in is arbitrary and doesn't matter.

Usage:
    python consolidate_shards.py --results-dir ../results/remote [--target-count 10] [--dry-run]
"""
import argparse
import glob
import os
import re

import results_lib


def natural_shard_key(path):
    m = re.search(r"_shard(\d+)\.jsonl$", path)
    return int(m.group(1)) if m else -1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", required=True, metavar="DIR",
                         help="Directory containing elo_results_<format>_shard*.jsonl files to consolidate in place")
    parser.add_argument("--target-count", type=int, default=10, help="Number of shard files per format to end up with (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="report what would change without touching files")
    args = parser.parse_args()

    results_dir = os.path.abspath(args.results_dir)
    formats = results_lib.discover_formats(results_dir)
    if not formats:
        print(f"No elo_results_*_shard*.jsonl files found under {results_dir}.")
        return

    for fmt in sorted(formats):
        paths = sorted(
            glob.glob(os.path.join(results_dir, f"elo_results_{fmt}_shard*.jsonl")),
            key=natural_shard_key,
        )
        paths = [p for p in paths if ".duplicates_removed" not in p and ".had_error_removed" not in p]
        if len(paths) <= args.target_count:
            print(f"{fmt}: already {len(paths)} file(s), target is {args.target_count} -- skipping.")
            continue

        rows = []
        for p in paths:
            with open(p, "r", encoding="utf-8") as f:
                rows.extend(line for line in f if line.strip())

        print(f"{fmt}: merging {len(paths)} files ({len(rows)} rows) into {args.target_count} file(s).")
        if args.dry_run:
            continue

        buckets = [[] for _ in range(args.target_count)]
        for i, row in enumerate(rows):
            buckets[i % args.target_count].append(row)

        for p in paths:
            os.remove(p)
        for i, bucket in enumerate(buckets):
            out_path = os.path.join(results_dir, f"elo_results_{fmt}_shard{i}.jsonl")
            with open(out_path, "w", encoding="utf-8") as f:
                f.writelines(bucket)

    if args.dry_run:
        print("Dry run -- no files were changed.")


if __name__ == "__main__":
    main()

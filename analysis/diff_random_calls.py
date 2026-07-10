"""Diff random_record.txt against random_replay.txt.

Each file is pairs of lines: a value, followed by a JSON array of the
stack trace at the call site that requested it. The two files are produced by
different call chains (record goes through AI_Benchmark/saveReplay!,
replay goes through watch.rb/watchReplay!), so the outer frames of every
trace always differ even when the RNG call itself is identical. Trim each
trace down to its innermost frames before comparing so real divergences
aren't buried under call-site noise.

Usage:
    python scripts/diff_random_calls.py <record.txt> <replay.txt> [--frames N] [--limit N]
"""

import argparse
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_records(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line != ""]
    for i in range(0, len(lines) - 1, 2):
        value = lines[i]
        trace = json.loads(lines[i + 1])
        records.append((value.strip(), trace))
    return records


def trim(trace, frames):
    return [f.split(":in ", 1)[-1].strip("`'") for f in trace[:frames]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--record_dir",
        type=str,
        default=os.path.join(REPO_ROOT, "vendor", "tectonic-content", "Analysis"),
        help="The directory containing the files to compare",
    )
    ap.add_argument(
        "--record_file",
        type=str,
        default="random_record.txt",
        help="The baseline file to compare against",
    )
    ap.add_argument(
        "--replay_file",
        type=str,
        default="random_replay.txt",
        help="The file to compare against the baseline",
    )
    ap.add_argument(
        "--frames",
        type=int,
        default=3,
        help="innermost stack frames to compare (default 3)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=3,
        help="stop after this many mismatches (default 3)",
    )
    args = ap.parse_args()

    record = load_records(os.path.join(args.record_dir, args.record_file))
    replay = load_records(os.path.join(args.record_dir, args.replay_file))

    print(f"record: {len(record)} calls, replay: {len(replay)} calls")

    mismatches = 0
    for idx, ((rval, rtrace), (pval, ptrace)) in enumerate(zip(record, replay)):
        rsite = trim(rtrace, args.frames)
        psite = trim(ptrace, args.frames)
        if rval != pval or rsite != psite:
            mismatches += 1
            print(f"\n--- call #{idx} ---")
            print(f"  record: value={rval!r} site={rsite}")
            print(f"  replay: value={pval!r} site={psite}")
            if mismatches >= args.limit:
                print(f"\n...stopping after {args.limit} mismatches (--limit)")
                break

    if mismatches == 0:
        common = min(len(record), len(replay))
        print(
            f"no mismatches in first {common} calls (trimmed to {args.frames} frames)"
        )

    if len(record) != len(replay):
        print(
            f"\nlength mismatch: record has {len(record)} calls, replay has {len(replay)} "
            f"(compared only the first {min(len(record), len(replay))})"
        )


if __name__ == "__main__":
    main()

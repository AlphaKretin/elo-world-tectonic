import argparse
import glob
import json
import os

import results_lib

RESULTS_DIR = results_lib.RESULTS_DIR


def process_file(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    timeout, err = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        obj = json.loads(stripped)

        if obj.get("result") == 0:
            timeout.append(line)
        if obj.get("had_error"):
            err.append(line)

    if len(timeout) > 0:
        print(f"  {os.path.basename(path)}: Detected {len(timeout)} timeout row(s)")
    if len(err) > 0:
        print(f"  {os.path.basename(path)}: Detected {len(err)} had_error row(s)")
    return (len(timeout), len(err))


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--results-dir",
        default=RESULTS_DIR,
        metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/current/; use results/local/ or results/remote/ for not-yet-promoted data)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")))
    paths = [p for p in paths if not p.endswith(".had_error_removed.jsonl")]
    if not paths:
        print(f"No elo_results_*_shard*.jsonl files found under {RESULTS_DIR}.")
        return

    total_timeout, total_err = 0, 0
    for path in paths:
        timeout, err = process_file(path)
        total_timeout += timeout
        total_err += err

    print(
        f"Detected {total_timeout} timeout row(s) and {total_err} had_error row(s) total across {len(paths)} file(s)."
    )


if __name__ == "__main__":
    main()

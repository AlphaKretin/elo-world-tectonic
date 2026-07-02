#!/usr/bin/env python3
import argparse
import glob
import json
import os
import numpy as np
import matplotlib.pyplot as plt
import mplcursors

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(REPO_ROOT, "results", "remote")
TECTONIC_DIR = os.path.join(REPO_ROOT, "vendor", "tectonic-content")
CARD_DATA_PATH = os.path.join(TECTONIC_DIR, "Analysis", "trainer_card_data.json")
CARDS_OUT_DIR = os.path.join(ANALYSIS_DIR, "cards")

def discover_formats():
    formats = set()
    for path in glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")):
        name = os.path.basename(path)
        middle = name[len("elo_results_"):-len(".jsonl")]
        formats.add(middle.rsplit("_shard", 1)[0])
    return sorted(formats)


def load_ratings(fmt):
    path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["trainer"]: row for row in rows}


def load_card_data():
    with open(CARD_DATA_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["label"]: row for row in rows}



def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", default=None, help="Format to use (default: first one found)")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    if not os.path.exists(CARD_DATA_PATH):
        raise SystemExit(
            f"{CARD_DATA_PATH} not found -- run the ELO_DUMP_TRAINER_CARD_DATA dump first (see this script's docstring)."
        )

    fmt = args.format or discover_formats()[0]
    ratings_by_label = load_ratings(fmt)
    card_data_by_label = load_card_data()

    # TODO: round up "max party level" to "level cap", get distribution of ratings per cap, list outliers
    ratings_levels = [( np.max([p["level"] for p in card_data_by_label[row["trainer"]]["party"]]),
                       row["rating"], row["trainer"]) for row in ratings_by_label.values()]
    
    fig, ax = plt.subplots()
    scatter = ax.scatter([x for x,_,_ in ratings_levels], [y for _,y,_ in ratings_levels], s=10)
    mplcursors.cursor(scatter, hover=True).connect(
        "add", lambda sel: sel.annotation.set_text(
            f"Level: {ratings_levels[sel.index][0]:.1f}\nELO: {ratings_levels[sel.index][1]:.1f}\nTrainer: {ratings_levels[sel.index][2]}"
        )
    )

    m,b = np.polyfit([x for x,_,_ in ratings_levels], [y for _,y,_ in ratings_levels], 1)
    x = np.linspace(10, 70, 70)
    ax.plot(x, m*x+b, color="red", label=f"y={m:.2f}x+{b:.2f}")
    ax.set_xlabel("Maximum Party Level")
    ax.set_ylabel("ELO Rating")
    ax.set_title(f"ELO Rating vs Maximum Party Level ({fmt})")
    plt.show()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ELO Rating vs. party level, from a format's ratings_<format>.json (see
ratings.py) and results/current/trainer_data.json (needs the
ELO_DUMP_TRAINER_CARD_DATA dump, promoted into results/current -- see
trainer_cards.py's docstring).

One chart: rating vs. each trainer's raw max party level, with a linear fit
(slope/R^2 in the console output and the legend). No outlier flag, drawn
boundary, or derived color/size encoding -- that call is left to whoever's
looking at the chart. Hover tooltips (see add_hover) surface a trainer's
exact residual from the fit on demand instead.

Needs an interactive matplotlib backend for the mplcursors hover tooltips
-- meant to be run and looked at, not piped headless. --output additionally
saves a static PNG (no hover tooltips) for sharing a snapshot.
"""
import argparse
import os

import matplotlib.pyplot as plt
import mplcursors
import numpy as np

import results_lib
from results_lib import TRAINER_DATA_PATH, REPO_ROOT

RESULTS_DIR = results_lib.RESULTS_DIR
TECTONIC_DIR = os.path.join(REPO_ROOT, "vendor", "tectonic-content")

# Palette -- dark surface, structural roles (surfaces/ink/grid), the fit
# line's accent, and the point fill.
FIG_BG = "#0d0d0d"           # page plane
AX_BG = "#1a1a19"            # chart surface
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#c3c2b7"
TEXT_MUTED = "#898781"       # axis/tick ink, same value in both modes
AXIS_LINE = "#383835"        # baseline/spine
COLOR_GRID = "#2c2c2a"       # gridline hairline, dark mode

COLOR_FIT = "#e66767"        # trend line
COLOR_POINT = "#5aa9d6"      # point fill -- distinct hue from the trend line


def build_entries(ratings_by_label, trainer_data_by_label):
    entries = []
    for label, row in ratings_by_label.items():
        card = trainer_data_by_label.get(label)
        if card is None:
            continue
        level = max(p["level"] for p in card["party"])
        entries.append({
            "trainer": label,
            "level": level,
            "rating": row["rating"],
            "tier": row.get("tier"),
        })
    return entries


def fit_trend(entries):
    """OLS fit of rating ~ level. Mutates entries with "resid" (rating minus
    the fit's prediction); returns (slope, intercept, r2)."""
    levels = np.array([e["level"] for e in entries], dtype=float)
    ratings = np.array([e["rating"] for e in entries], dtype=float)
    m, b = np.polyfit(levels, ratings, 1)
    pred = m * levels + b
    resid = ratings - pred
    ss_res = np.sum((ratings - pred) ** 2)
    ss_tot = np.sum((ratings - ratings.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    for e, r in zip(entries, resid):
        e["resid"] = r
    return m, b, r2


def add_hover(pairs):
    """One mplcursors.cursor() per *group* of related artists, not one per
    artist. mplcursors tracks its add/remove (hover-in/hover-out) state per
    Cursor instance -- stacking many independent Cursor objects over
    overlapping points means they don't know about each other, so an old
    annotation can fail to clear when a new one appears, and they pile up
    and get laggy. Passing every artist to a single cursor() call keeps one
    shared instance doing the bookkeeping. `pairs` is (artist, entries)
    tuples; sel.artist tells the callback which entries list to index into."""
    pairs = list(pairs)
    entries_by_artist = {id(artist): entries for artist, entries in pairs}

    def _fmt(sel):
        e = entries_by_artist[id(sel.artist)][sel.index]
        sel.annotation.set_text(
            f"Trainer: {e['trainer']}\nLevel: {e['level']}\n"
            f"ELO: {e['rating']:.1f}\nTier: {e['tier'] or 'unranked'}\n"
            f"Residual: {e['resid']:+.1f} vs trend"
        )

    mplcursors.cursor([artist for artist, _ in pairs], hover=True).connect("add", _fmt)


def style_figure(fig, ax, title, fmt):
    fig.patch.set_facecolor(FIG_BG)
    ax.set_facecolor(AX_BG)
    ax.tick_params(colors=TEXT_MUTED, labelsize=11)
    for spine in ax.spines.values():
        spine.set_color(AXIS_LINE)
    ax.xaxis.label.set_color(TEXT_SECONDARY)
    ax.yaxis.label.set_color(TEXT_SECONDARY)
    ax.xaxis.label.set_fontsize(12)
    ax.yaxis.label.set_fontsize(12)
    ax.set_title(f"{title} ({fmt})", color=TEXT_PRIMARY, fontsize=15)


def plot_level_vs_rating(fig, ax, entries, m, b, r2, fmt):
    levels = np.array([e["level"] for e in entries], dtype=float)
    ratings = np.array([e["rating"] for e in entries], dtype=float)

    scatter = ax.scatter(levels, ratings, s=32, color=COLOR_POINT, alpha=0.75,
                          edgecolors=AX_BG, linewidths=0.5, zorder=3)
    add_hover([(scatter, entries)])

    x = np.linspace(levels.min(), levels.max(), 100)
    ax.plot(x, m * x + b, color=COLOR_FIT, linewidth=2.5, zorder=2,
            label=f"fit: y={m:.2f}x+{b:.2f}, R²={r2:.3f}")
    ax.legend(loc="upper left", fontsize=10, frameon=False, labelcolor=TEXT_SECONDARY)

    ax.set_xlabel("Maximum Party Level")
    ax.set_ylabel("ELO Rating")
    ax.grid(True, color=COLOR_GRID, linewidth=1)
    ax.set_axisbelow(True)
    style_figure(fig, ax, "Rating vs. Max Party Level", fmt)
    fig.tight_layout()


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", default=None, help="Format to use (default: singles, or the first format found if singles isn't present)")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/current/; use results/local/ or results/remote/ for not-yet-promoted data)",
    )
    parser.add_argument(
        "--output", "-o", metavar="PATH",
        help="Also save the figure to PATH (e.g. plot.png). The saved image has no hover tooltips -- "
             "it's a snapshot for sharing, not a substitute for running this interactively.",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    if not os.path.exists(TRAINER_DATA_PATH):
        raise SystemExit(
            f"{TRAINER_DATA_PATH} not found -- run the ELO_DUMP_TRAINER_CARD_DATA dump and promote it "
            "to results/current/trainer_data.json first (see this script's docstring)."
        )

    found_formats = results_lib.discover_formats(RESULTS_DIR)
    fmt = args.format or ("singles" if "singles" in found_formats else found_formats[0])
    ratings_by_label = results_lib.load_ratings(fmt)
    trainer_data_by_label = results_lib.load_trainer_data()

    entries = build_entries(ratings_by_label, trainer_data_by_label)
    m, b, r2 = fit_trend(entries)

    fig, ax = plt.subplots(figsize=(11, 8))
    plot_level_vs_rating(fig, ax, entries, m, b, r2, fmt)

    # R^2, not R², on the console print -- the Windows terminal's default
    # codepage mangles the unicode glyph (matplotlib's own text rendering in
    # the chart legend isn't subject to that, so it keeps the "²" there).
    print(f"[{fmt}] {len(entries)} trainers, fit: rating = {m:.2f} * level + {b:.2f} (R^2={r2:.3f})")

    if args.output:
        fig.savefig(args.output, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"[{fmt}] Saved static snapshot to {args.output} (no hover tooltips in this copy).")

    plt.show()


if __name__ == "__main__":
    main()

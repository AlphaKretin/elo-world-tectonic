#!/usr/bin/env python3
"""
ELO Rating (or rank) vs. party level, from a format's ratings_<format>.json
(see ratings.py) and results/current/trainer_data.json (needs the
ELO_DUMP_TRAINER_CARD_DATA dump, promoted into results/current -- see
trainer_cards.py's docstring).

--y-axis picks what level is plotted against, and (for --trend window/
logistic) what the windowing neighborhood is defined over:
  - rating (default): continuous, windowed by a rating-point radius --radius.
  - rank: discrete 1..N, windowed by a fixed count of ranks --window.

--chart picks the figure:
  - scatter (default): level vs. y-axis, with one or more trend lines
    overlaid. --trend takes a space-separated list (e.g. --trend window
    logistic); each requested mode is drawn in its own line style (see
    TREND_STYLES) so overlapping lines stay distinguishable:
      - ols: a global OLS fit of y-axis ~ level (slope/R^2 in the console
        output and the legend).
      - window: a local windowed average of level over the y-axis
        neighborhood (rating radius or rank count, see above).
      - logistic: a logistic curve fit of level ~ y-axis (scipy.optimize.
        curve_fit) -- the opposite direction from the OLS fit's y-axis ~
        level, matching the windowed curve's directionality, since the
        y-axis is the wide/continuous side and level is coarse/capped.
    ols and window are NOT the same curve in any limit, despite both being
    "a trend line through the same scatter": a plain windowed average is a
    local mean (order-0), which as the radius grows flattens to the
    dataset's global mean level -- a horizontal line -- not the diagonal
    OLS fit; the two only ever agree at the shared centroid point (mean
    level, mean y-axis value), which every OLS line passes through by
    construction.
  - delta: y-axis value vs. a single trend's residual instead of the raw
    scatter. Only the FIRST mode in --trend is used here -- different
    trends' residuals are in different units (ols is y-axis-space; window/
    logistic are level-space) and mixing them on one axis isn't meaningful.

--interactive (only meaningful when "window" is among --trend's modes)
swaps the static windowed curve for a live radius/window-count slider, and
works with either --chart. Any other requested modes (ols, logistic) are
still drawn, as static reference lines alongside the moving one.

No outlier flag, drawn boundary, or derived color/size encoding -- that
call is left to whoever's looking at the chart. Hover tooltips (see
add_hover) surface a trainer's exact residual from each active trend on
demand instead.

Needs an interactive matplotlib backend for the mplcursors hover tooltips
-- meant to be run and looked at, not piped headless. --output additionally
saves a static PNG (no hover tooltips) for sharing a snapshot; it cannot be
combined with --interactive, since there's no single frame to save.
"""
import argparse
import os

import matplotlib.pyplot as plt
import mplcursors
import numpy as np
from matplotlib.widgets import Slider
from scipy.optimize import curve_fit

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

COLOR_POINT = "#5aa9d6"      # point fill -- distinct hue from every trend line below

# Fixed rendering order (also legend order) and per-mode style, so any
# subset drawn together stays visually distinguishable by color AND
# linestyle (not color alone). Add a new entry here for a new --trend mode.
CANONICAL_TREND_ORDER = ["ols", "window", "logistic", "richards"]
TREND_STYLES = {
    "ols":      {"color": "#e66767", "linestyle": "--"},   # red, dashed
    "window":   {"color": "#e6b667", "linestyle": "-"},    # amber, solid
    "logistic": {"color": "#a267e6", "linestyle": ":"},    # purple, dotted
    "richards": {"color": "#67e6a0", "linestyle": "-."},   # teal, dash-dot
}

DEFAULT_RADIUS = 200.0    # rating points on each side -- tuned by eye: noticeably less jagged
                           # than smaller radii without the smoothing artifacts (a vertical-line
                           # degeneracy as the window approaches the whole dataset) that show up
                           # by radius ~1500
DEFAULT_WINDOW = 25        # ranks on each side
MIN_RADIUS = 10.0          # interactive slider lower bound, --y-axis rating
MIN_WINDOW = 1             # interactive slider lower bound, --y-axis rank

Y_AXIS_LABELS = {"rating": "ELO Rating", "rank": "Rank (1 = best)"}

# Level 1 and 70 are the game engine's actual floor and cap -- not just the
# min/max observed in this dataset -- so the richards trend fixes its
# asymptotes here rather than fitting them freely. A free fit found
# high already converging to ~70.3-70.5 on its own (the top of the ladder
# genuinely plateaus near the cap), but low landed at -14 to -54 -- no
# trainer is anywhere near that, and "level -14" isn't a meaningful
# concept even in principle. Comparing the two on this dataset: fixing
# both asymptotes costs R^2 in the fourth decimal place (~0.0005-0.0012),
# while pulling nu (the curve's skew) down substantially -- most visibly
# on the rank axis, from ~5.3 to ~1.3 (nearly the symmetric case) -- which
# suggests a good chunk of that skew was the free fit compensating for an
# impossible low, not a real property of the data.
LEVEL_MIN = 1.0
LEVEL_MAX = 70.0


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
            "rank": row["rank"],
            "tier": row.get("tier"),
        })
    return entries


def compute_deviations_by_rating(entries, radius):
    """For each entry, average max level over everyone within `radius`
    rating points (self excluded, clipped at the ends of the sorted
    ratings). Two-pointer sliding window over a prefix-sum array of
    ratings-sorted levels -- O(n) total since both window edges only
    advance as the trainer index advances. Mutates entries with "peer_avg",
    "peer_count", and "delta" (level - peer_avg)."""
    ordered = sorted(entries, key=lambda e: e["rating"])
    n = len(ordered)
    ratings = [e["rating"] for e in ordered]
    levels = [e["level"] for e in ordered]

    prefix = [0] * (n + 1)
    for i, lv in enumerate(levels):
        prefix[i + 1] = prefix[i] + lv

    lo = 0
    hi = -1  # last index included in the window (inclusive)
    for i in range(n):
        while ratings[lo] < ratings[i] - radius:
            lo += 1
        if hi < i:
            hi = i
        while hi + 1 < n and ratings[hi + 1] <= ratings[i] + radius:
            hi += 1

        count = (hi - lo + 1) - 1  # exclude self
        window_sum = prefix[hi + 1] - prefix[lo] - levels[i]
        e = ordered[i]
        e["peer_avg"] = window_sum / count if count else float("nan")
        e["peer_count"] = count
        e["delta"] = e["level"] - e["peer_avg"] if count else 0.0
    return ordered


def compute_deviations_by_rank(entries, window):
    """entries ordered by rank (assumed contiguous 1..N). For each entry,
    average max level over the `window` ranks on either side (self
    excluded, clipped at the rankings' ends), via a prefix-sum array so
    each trainer's window average is an O(1) lookup instead of an O(window)
    rescan. Mutates entries with "peer_avg", "peer_count", and "delta"
    (level - peer_avg)."""
    ordered = sorted(entries, key=lambda e: e["rank"])
    n = len(ordered)
    levels = [e["level"] for e in ordered]

    prefix = [0] * (n + 1)
    for i, lv in enumerate(levels):
        prefix[i + 1] = prefix[i] + lv

    for i, e in enumerate(ordered):
        lo = max(0, i - window)
        hi = min(n - 1, i + window)
        count = (hi - lo + 1) - 1  # exclude self
        window_sum = prefix[hi + 1] - prefix[lo] - levels[i]
        e["peer_avg"] = window_sum / count
        e["peer_count"] = count
        e["delta"] = e["level"] - e["peer_avg"]
    return ordered


def compute_curve_by_rating(ratings, levels, prefix, radius):
    """Vectorized version of compute_deviations_by_rating, for the live
    slider: for every trainer, the peer average of everyone within
    +/-radius rating points (self excluded). NaN where a trainer has no
    peers in range (only possible at very small radii) -- matplotlib draws
    those as a gap in the line rather than erroring."""
    lo = np.searchsorted(ratings, ratings - radius, side="left")
    hi = np.searchsorted(ratings, ratings + radius, side="right") - 1
    counts = (hi - lo + 1) - 1  # exclude self
    sums = prefix[hi + 1] - prefix[lo] - levels
    with np.errstate(invalid="ignore", divide="ignore"):
        peer_avg = np.where(counts > 0, sums / np.where(counts > 0, counts, 1), np.nan)
    return peer_avg, counts


def compute_curve_by_rank(levels, prefix, window):
    """Vectorized version of compute_deviations_by_rank, for the live
    slider: rank is contiguous 1..N once sorted, so unlike the rating
    version (where values aren't evenly spaced and need searchsorted),
    window bounds here are plain clipped index arithmetic."""
    n = len(levels)
    idx = np.arange(n)
    lo = np.clip(idx - window, 0, n - 1)
    hi = np.clip(idx + window, 0, n - 1)
    counts = (hi - lo + 1) - 1  # exclude self
    sums = prefix[hi + 1] - prefix[lo] - levels
    with np.errstate(invalid="ignore", divide="ignore"):
        peer_avg = np.where(counts > 0, sums / np.where(counts > 0, counts, 1), np.nan)
    return peer_avg, counts


def fit_trend_ols(entries, y_key):
    """OLS fit of y_key ~ level (y_key is "rating" or "rank"). Mutates
    entries with "resid_ols" (y_key value minus the fit's prediction);
    returns (slope, intercept, r2)."""
    levels = np.array([e["level"] for e in entries], dtype=float)
    yvals = np.array([e[y_key] for e in entries], dtype=float)
    m, b = np.polyfit(levels, yvals, 1)
    pred = m * levels + b
    resid = yvals - pred
    ss_res = np.sum((yvals - pred) ** 2)
    ss_tot = np.sum((yvals - yvals.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    for e, r in zip(entries, resid):
        e["resid_ols"] = r
    return m, b, r2


def fit_trend_window(entries, y_key, param):
    """Local windowed average of level over a neighborhood in y_key space
    -- a rating-point radius if y_key == "rating" (compute_deviations_by_
    rating), or a fixed count of ranks if y_key == "rank" (compute_
    deviations_by_rank). Mutates entries with "resid_window" (level minus
    the window's peer average -- NOT y_key minus a prediction, since the
    window predicts level from y_key here, the opposite direction to the
    OLS fit); returns entries sorted by y_key (the order the curve is
    already in)."""
    if y_key == "rating":
        ordered = compute_deviations_by_rating(entries, param)
    else:
        ordered = compute_deviations_by_rank(entries, param)
    for e in ordered:
        e["resid_window"] = e["delta"]
    return ordered


def logistic_curve(x, low, high, k, x0):
    return low + (high - low) / (1 + np.exp(-k * (x - x0)))


def fit_trend_logistic(entries, y_key):
    """Logistic fit of level ~ y_key (scipy.optimize.curve_fit) -- opposite
    direction from the OLS fit, matching the windowed curve's
    directionality. Mutates entries with "resid_logistic" (level minus the
    fit's prediction); returns (popt, r2) where popt = (low, high, k, x0)."""
    yvals = np.array([e[y_key] for e in entries], dtype=float)
    levels = np.array([e["level"] for e in entries], dtype=float)
    p0 = [levels.min(), levels.max(), 0.005, np.median(yvals)]
    popt, _ = curve_fit(logistic_curve, yvals, levels, p0=p0, maxfev=20000)
    pred = logistic_curve(yvals, *popt)
    resid = levels - pred
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((levels - levels.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    for e, r in zip(entries, resid):
        e["resid_logistic"] = r
    return popt, r2


def richards_curve(x, low, high, k, x0, nu):
    return low + (high - low) / (1 + nu * np.exp(-k * (x - x0))) ** (1 / nu)


def fit_trend_richards(entries, y_key):
    """Generalized logistic (Richards) fit of level ~ y_key -- adds one
    shape parameter nu to logistic_curve's four, letting the curve's
    approach to its low and high asymptotes skew independently instead of
    mirroring each other (nu=1 recovers the plain logistic exactly).
    low/high are fixed at LEVEL_MIN/LEVEL_MAX (the game's actual level
    floor/cap, not just this dataset's observed range -- see the comment
    by those constants) rather than fit freely: letting them float let nu
    trade off against an increasingly unrealistic low with barely any R^2
    gain, which both muddies nu's meaning and can wander into physically
    meaningless territory (a fit run without these fixed asymptotes once
    landed on low=-54 for this dataset's --y-axis rank). Seeds curve_fit's
    k/x0 from a quick unweighted logistic fit and nu=1 -- a multi-parameter
    sigmoid is sensitive to its starting point. Mutates entries with
    "resid_richards"; returns (popt, r2) where
    popt = (LEVEL_MIN, LEVEL_MAX, k, x0, nu)."""
    yvals = np.array([e[y_key] for e in entries], dtype=float)
    levels = np.array([e["level"] for e in entries], dtype=float)
    logistic_p0 = [levels.min(), levels.max(), 0.005, np.median(yvals)]
    logistic_popt, _ = curve_fit(logistic_curve, yvals, levels, p0=logistic_p0, maxfev=20000)
    p0 = [logistic_popt[2], logistic_popt[3], 1.0]
    y_span = yvals.max() - yvals.min()
    bounds = ([-1.0, yvals.min() - y_span, 0.02], [1.0, yvals.max() + y_span, 50.0])

    def f(x, k, x0, nu):
        return richards_curve(x, LEVEL_MIN, LEVEL_MAX, k, x0, nu)

    (k, x0, nu), _ = curve_fit(f, yvals, levels, p0=p0, bounds=bounds, maxfev=20000)
    popt = (LEVEL_MIN, LEVEL_MAX, k, x0, nu)
    pred = f(yvals, k, x0, nu)
    resid = levels - pred
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((levels - levels.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    for e, r in zip(entries, resid):
        e["resid_richards"] = r
    return popt, r2


def add_hover(pairs, y_key):
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
    y_label = "ELO" if y_key == "rating" else "Rank"

    def _fmt(sel):
        e = entries_by_artist[id(sel.artist)][sel.index]
        yval = f"{e['rating']:.1f}" if y_key == "rating" else f"#{e['rank']}"
        lines = [
            f"Trainer: {e['trainer']}", f"Level: {e['level']}",
            f"{y_label}: {yval}", f"Tier: {e['tier'] or 'unranked'}",
        ]
        if "resid_ols" in e:
            lines.append(f"Residual (OLS): {e['resid_ols']:+.1f}")
        if "resid_window" in e:
            lines.append(f"Residual (windowed): {e['resid_window']:+.1f}")
        if "resid_logistic" in e:
            lines.append(f"Residual (logistic): {e['resid_logistic']:+.1f}")
        if "resid_richards" in e:
            lines.append(f"Residual (richards): {e['resid_richards']:+.1f}")
        sel.annotation.set_text("\n".join(lines))

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


def plot_scatter(fig, ax, entries, modes, trend_data, y_key, fmt):
    levels = np.array([e["level"] for e in entries], dtype=float)
    yvals = np.array([e[y_key] for e in entries], dtype=float)

    scatter = ax.scatter(levels, yvals, s=32, color=COLOR_POINT, alpha=0.75,
                          edgecolors=AX_BG, linewidths=0.5, zorder=3)
    add_hover([(scatter, entries)], y_key)

    for mode in modes:
        style = TREND_STYLES[mode]
        if mode == "ols":
            m, b, r2 = trend_data["ols"]["m"], trend_data["ols"]["b"], trend_data["ols"]["r2"]
            x = np.linspace(levels.min(), levels.max(), 100)
            ax.plot(x, m * x + b, color=style["color"], linestyle=style["linestyle"],
                    linewidth=2.5, zorder=2, label=f"OLS fit: y={m:.2f}x+{b:.2f}, R²={r2:.3f}")
        elif mode == "window":
            # entries are sorted by y_key (fit_trend_window's order), so
            # this traces the curve without a re-sort.
            curve_x = np.array([e["peer_avg"] for e in entries], dtype=float)
            curve_y = np.array([e[y_key] for e in entries], dtype=float)
            ax.plot(curve_x, curve_y, color=style["color"], linestyle=style["linestyle"],
                    linewidth=2.5, zorder=2, label=f"windowed avg ({trend_data['window']['desc']})")
        elif mode == "logistic":
            low, high, k, x0 = trend_data["logistic"]["params"]
            r2 = trend_data["logistic"]["r2"]
            y = np.linspace(yvals.min(), yvals.max(), 200)
            x = logistic_curve(y, low, high, k, x0)
            ax.plot(x, y, color=style["color"], linestyle=style["linestyle"],
                    linewidth=2.5, zorder=2, label=f"logistic fit (R²={r2:.3f})")
        elif mode == "richards":
            low, high, k, x0, nu = trend_data["richards"]["params"]
            r2 = trend_data["richards"]["r2"]
            y = np.linspace(yvals.min(), yvals.max(), 200)
            x = richards_curve(y, low, high, k, x0, nu)
            ax.plot(x, y, color=style["color"], linestyle=style["linestyle"],
                    linewidth=2.5, zorder=2, label=f"richards fit (ν={nu:.2f}, R²={r2:.3f})")
    ax.legend(loc="upper left", fontsize=10, frameon=False, labelcolor=TEXT_SECONDARY)

    ax.set_xlabel("Maximum Party Level")
    ax.set_ylabel(Y_AXIS_LABELS[y_key])
    if y_key == "rank":
        ax.invert_yaxis()  # rank 1 (best) at the top, matching rating's "higher = better" convention
    ax.grid(True, color=COLOR_GRID, linewidth=1)
    ax.set_axisbelow(True)
    style_figure(fig, ax, "Rating vs. Max Party Level" if y_key == "rating" else "Rank vs. Max Party Level", fmt)
    fig.tight_layout()


def plot_delta(fig, ax, entries, mode, trend_data, y_key, fmt):
    """Single-trend residual chart: x = y_key value, y = that trend's
    residual. Only one trend at a time -- residuals from different trends
    are in different units (ols is y_key-space, window/logistic are
    level-space) and aren't meaningful to overlay on one axis."""
    yvals = np.array([e[y_key] for e in entries], dtype=float)
    resids = np.array([e[f"resid_{mode}"] for e in entries], dtype=float)

    style = TREND_STYLES[mode]
    scatter = ax.scatter(yvals, resids, s=32, color=style["color"], alpha=0.75,
                          edgecolors=AX_BG, linewidths=0.5, zorder=3)
    add_hover([(scatter, entries)], y_key)

    ax.axhline(0, color=AXIS_LINE, linewidth=1, zorder=1)

    # window/logistic/richards residuals are level-space: a lower level
    # than predicted (negative) is the impressive direction, so draw it
    # toward the top. ols's residual is y_key-space: a HIGHER y_key value
    # than the level predicts (positive) is impressive, which is already
    # "up" by default -- no inversion needed there.
    if mode == "window":
        ax.invert_yaxis()
        impressive, unit, label_source = "lower", "level", f"windowed avg ({trend_data['window']['desc']})"
    elif mode == "logistic":
        ax.invert_yaxis()
        impressive, unit, label_source = "lower", "level", "logistic fit"
    elif mode == "richards":
        ax.invert_yaxis()
        nu = trend_data["richards"]["params"][4]
        impressive, unit, label_source = "lower", "level", f"richards fit (ν={nu:.2f})"
    else:
        impressive, unit, label_source = "higher", Y_AXIS_LABELS[y_key].split()[-1].lower(), "OLS fit"

    if y_key == "rank":
        ax.invert_xaxis()  # rank 1 (best) on the right
    ax.set_xlabel(Y_AXIS_LABELS[y_key])
    ax.set_ylabel(f"{unit.capitalize()} residual vs. {label_source} ({impressive} = more impressive)")
    ax.grid(True, color=COLOR_GRID, linewidth=1)
    ax.set_axisbelow(True)
    style_figure(fig, ax, f"Residual vs. {label_source}", fmt)
    fig.tight_layout()


def run_interactive(entries, modes, chart, y_key, initial_param, fmt, static_trend_data):
    """Live radius/window slider for the "window" trend (see
    compute_curve_by_rating / compute_curve_by_rank) -- vectorized so
    dragging the slider redraws instantly instead of only on release. Any
    other requested modes (ols, logistic) are static, drawn once from
    static_trend_data. chart == "scatter" redraws the windowed curve
    (level vs y_key); chart == "delta" redraws the windowed residual
    (y_key vs level-residual) -- the caller guarantees modes[0] == "window"
    when chart == "delta"."""
    ordered = sorted(entries, key=lambda e: e[y_key])
    yvals = np.array([e[y_key] for e in ordered], dtype=float)
    levels = np.array([e["level"] for e in ordered], dtype=float)
    prefix = np.concatenate([[0.0], np.cumsum(levels)])

    if y_key == "rating":
        min_param, max_param = MIN_RADIUS, yvals.max() - yvals.min()
        compute = lambda p: compute_curve_by_rating(yvals, levels, prefix, p)
        slider_label, fmt_param = "Radius", (lambda p: f"±{p:.0f} rating")
    else:
        min_param, max_param = MIN_WINDOW, len(ordered) - 1
        compute = lambda p: compute_curve_by_rank(levels, prefix, int(round(p)))
        slider_label, fmt_param = "Window", (lambda p: f"±{int(round(p))} ranks")

    def apply_param(param):
        peer_avg, counts = compute(param)
        for e, pa, c in zip(ordered, peer_avg, counts):
            e["peer_avg"] = pa
            e["peer_count"] = c
            e["resid_window"] = e["level"] - pa
        return peer_avg, counts

    fig, ax = plt.subplots(figsize=(11, 8))
    fig.subplots_adjust(bottom=0.18)  # room for the slider; no fig.tight_layout() after this
    ax.set_facecolor(AX_BG)
    ax.tick_params(colors=TEXT_MUTED, labelsize=11)
    for spine in ax.spines.values():
        spine.set_color(AXIS_LINE)

    window_style = TREND_STYLES["window"]

    if chart == "scatter":
        title_base = "Rating vs. Max Party Level" if y_key == "rating" else "Rank vs. Max Party Level"
        scatter = ax.scatter(levels, yvals, s=32, color=COLOR_POINT, alpha=0.75,
                              edgecolors=AX_BG, linewidths=0.5, zorder=3)
        add_hover([(scatter, ordered)], y_key)

        for mode in modes:
            if mode == "window":
                continue  # slider-driven, drawn below
            style = TREND_STYLES[mode]
            if mode == "ols":
                m, b, r2 = static_trend_data["ols"]["m"], static_trend_data["ols"]["b"], static_trend_data["ols"]["r2"]
                x = np.linspace(levels.min(), levels.max(), 100)
                ax.plot(x, m * x + b, color=style["color"], linestyle=style["linestyle"],
                        linewidth=2.5, zorder=2, label=f"OLS fit: y={m:.2f}x+{b:.2f}, R²={r2:.3f}")
            elif mode == "logistic":
                low, high, k, x0 = static_trend_data["logistic"]["params"]
                r2 = static_trend_data["logistic"]["r2"]
                y = np.linspace(yvals.min(), yvals.max(), 200)
                x = logistic_curve(y, low, high, k, x0)
                ax.plot(x, y, color=style["color"], linestyle=style["linestyle"],
                        linewidth=2.5, zorder=2, label=f"logistic fit (R²={r2:.3f})")
            elif mode == "richards":
                low, high, k, x0, nu = static_trend_data["richards"]["params"]
                r2 = static_trend_data["richards"]["r2"]
                y = np.linspace(yvals.min(), yvals.max(), 200)
                x = richards_curve(y, low, high, k, x0, nu)
                ax.plot(x, y, color=style["color"], linestyle=style["linestyle"],
                        linewidth=2.5, zorder=2, label=f"richards fit (ν={nu:.2f}, R²={r2:.3f})")

        peer_avg, counts0 = apply_param(initial_param)
        (artist,) = ax.plot(peer_avg, yvals, color=window_style["color"], linestyle=window_style["linestyle"],
                             linewidth=2.5, zorder=2, label="windowed avg")

        def redraw(param):
            peer_avg, counts = apply_param(param)
            artist.set_xdata(peer_avg)
            return counts

        ax.set_xlabel("Maximum Party Level")
        ax.set_ylabel(Y_AXIS_LABELS[y_key])
        if y_key == "rank":
            ax.invert_yaxis()
        ax.legend(loc="upper left", fontsize=10, frameon=False, labelcolor=TEXT_SECONDARY)
    else:
        title_base = "Residual vs. Windowed Average"
        _, counts0 = apply_param(initial_param)
        resids = np.array([e["resid_window"] for e in ordered], dtype=float)
        artist = ax.scatter(yvals, resids, s=32, color=window_style["color"], alpha=0.75,
                             edgecolors=AX_BG, linewidths=0.5, zorder=3)
        add_hover([(artist, ordered)], y_key)
        ax.axhline(0, color=AXIS_LINE, linewidth=1, zorder=1)
        ax.invert_yaxis()  # negative (lower level than peers) is impressive
        if y_key == "rank":
            ax.invert_xaxis()

        def redraw(param):
            _, counts = apply_param(param)
            resids = np.array([e["resid_window"] for e in ordered], dtype=float)
            artist.set_offsets(np.column_stack([yvals, resids]))
            return counts

        ax.set_xlabel(Y_AXIS_LABELS[y_key])
        ax.set_ylabel("Level residual vs. windowed avg (lower = more impressive)")

    ax.grid(True, color=COLOR_GRID, linewidth=1)
    ax.set_axisbelow(True)
    style_figure(fig, ax, title_base, fmt)
    title = ax.title

    def update_title(param, counts):
        avg_peers = np.nanmean(counts) if len(counts) else float("nan")
        title.set_text(f"{title_base} ({fmt}) -- windowed {fmt_param(param)}, avg {avg_peers:.1f} peers/window")

    update_title(initial_param, counts0)

    slider_ax = fig.add_axes([0.15, 0.05, 0.7, 0.03])
    slider_ax.set_facecolor(AX_BG)
    slider = Slider(slider_ax, slider_label, min_param, max_param, valinit=initial_param,
                     color=window_style["color"], initcolor="none")
    slider.label.set_color(TEXT_SECONDARY)
    slider.valtext.set_color(TEXT_SECONDARY)

    def on_change(param):
        counts = redraw(param)
        update_title(param, counts)
        fig.canvas.draw_idle()

    slider.on_changed(on_change)

    print(f"[{fmt}] interactive {chart} mode -- drag the slider (initial {fmt_param(initial_param)})")
    plt.show()


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", default=None, help="Format to use (default: singles, or the first format found if singles isn't present)")
    parser.add_argument(
        "--y-axis", choices=["rating", "rank"], default="rating",
        help="Metric to plot level against, and to window by for --trend window/logistic: "
             "'rating' (continuous, windowed by a rating-point radius -- see --radius) or "
             "'rank' (discrete, windowed by a fixed count of ranks -- see --window). Default: rating",
    )
    parser.add_argument(
        "--chart", choices=["scatter", "delta"], default="scatter",
        help="'scatter' plots level vs. --y-axis with trend line(s) overlaid; 'delta' plots "
             "--y-axis vs. a single trend's residual instead (only the first mode in --trend is "
             "used, since different trends' residuals are in different units). Default: scatter",
    )
    parser.add_argument(
        "--trend", nargs="+", choices=["ols", "window", "logistic", "richards"], default=["richards"], metavar="MODE",
        help="One or more trend lines, e.g. --trend window logistic (each drawn in its own "
             "color/linestyle -- see TREND_STYLES): 'ols' is a global linear fit (slope/R² in the "
             "legend); 'window' is a local windowed average of level over --y-axis's neighborhood "
             "(--radius or --window); 'logistic' fits a logistic curve of level ~ --y-axis; "
             "'richards' is a generalized logistic (one extra shape parameter ν, letting the two "
             "asymptotic approaches skew independently instead of mirroring each other) -- tracks "
             "the windowed curve closely on this dataset, hence the default. With --chart delta, "
             "only the first listed mode is used. Default: richards",
    )
    parser.add_argument(
        "--radius", type=float, default=DEFAULT_RADIUS, metavar="POINTS",
        help=f"Rating points considered on each side of a trainer when windowing by rating "
             f"(--y-axis rating), used when 'window' is among --trend's modes, and as the "
             f"slider's initial value with --interactive there (default: {DEFAULT_RADIUS:g})",
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW, metavar="N",
        help=f"Ranks considered on each side of a trainer when windowing by rank (--y-axis rank), "
             f"used when 'window' is among --trend's modes, and as the slider's initial value "
             f"with --interactive there (default: {DEFAULT_WINDOW})",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="When 'window' is among --trend's modes, show a live radius/window slider instead of "
             "a static curve; any other requested modes are still drawn as static reference lines. "
             "No effect if 'window' isn't requested. Cannot be combined with --output -- there's "
             "no single frame to save.",
    )
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

    # Canonical (not argument) order, so rendering/legend order is stable
    # regardless of how the modes were listed on the command line, and
    # duplicates collapse.
    modes = [m for m in CANONICAL_TREND_ORDER if m in args.trend]

    if args.chart == "delta":
        if not modes:
            raise SystemExit("--chart delta needs at least one --trend mode.")
        if len(modes) > 1:
            print(f"--chart delta only plots one trend at a time; using '{modes[0]}' (first of {modes}), ignoring the rest.")
        modes = modes[:1]
    delta_mode = modes[0] if args.chart == "delta" else None

    if args.interactive and "window" not in modes:
        print(f"--interactive has no effect without 'window' in --trend {' '.join(modes)}; showing a static chart.")
        args.interactive = False
    if args.interactive and args.output:
        raise SystemExit("--interactive cannot be combined with --output -- there's no single frame "
                          "to save. Drop --interactive for a snapshot, or run without --output.")

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
    y_key = args.y_axis
    window_param = args.radius if y_key == "rating" else args.window
    window_desc = f"±{args.radius:g} rating" if y_key == "rating" else f"±{args.window} ranks"

    trend_data = {}
    if "ols" in modes:
        m, b, r2 = fit_trend_ols(entries, y_key)
        trend_data["ols"] = {"m": m, "b": b, "r2": r2}
        # R^2, not R², on the console print -- the Windows terminal's default
        # codepage mangles the unicode glyph (matplotlib's own text rendering
        # in the chart legend isn't subject to that, so it keeps "²" there).
        print(f"[{fmt}] {len(entries)} trainers, OLS fit: {y_key} = {m:.2f} * level + {b:.2f} (R^2={r2:.3f})")
    if "logistic" in modes:
        popt, r2 = fit_trend_logistic(entries, y_key)
        trend_data["logistic"] = {"params": popt, "r2": r2}
        low, high, k, x0 = popt
        print(f"[{fmt}] {len(entries)} trainers, logistic fit: level = {low:.2f} + "
              f"({high:.2f}-{low:.2f})/(1+exp(-{k:.5f}*({y_key}-{x0:.1f}))) (R^2={r2:.3f})")
    if "richards" in modes:
        popt, r2 = fit_trend_richards(entries, y_key)
        trend_data["richards"] = {"params": popt, "r2": r2}
        low, high, k, x0, nu = popt
        print(f"[{fmt}] {len(entries)} trainers, richards fit: level = {low:.2f} + "
              f"({high:.2f}-{low:.2f})/(1+{nu:.3f}*exp(-{k:.5f}*({y_key}-{x0:.1f})))^(1/{nu:.3f}) (R^2={r2:.3f})")

    if args.interactive:
        run_interactive(entries, modes, args.chart, y_key, window_param, fmt, static_trend_data=trend_data)
        return

    if "window" in modes:
        entries = fit_trend_window(entries, y_key, window_param)
        trend_data["window"] = {"desc": window_desc}
        avg_peers = sum(e["peer_count"] for e in entries) / len(entries)
        print(f"[{fmt}] {len(entries)} trainers, windowed avg: {window_desc}, avg {avg_peers:.1f} peers/window")

    fig, ax = plt.subplots(figsize=(11, 8))
    if args.chart == "scatter":
        plot_scatter(fig, ax, entries, modes, trend_data, y_key, fmt)
    else:
        plot_delta(fig, ax, entries, delta_mode, trend_data, y_key, fmt)

    if args.output:
        fig.savefig(args.output, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"[{fmt}] Saved static snapshot to {args.output} (no hover tooltips in this copy).")

    plt.show()


if __name__ == "__main__":
    main()

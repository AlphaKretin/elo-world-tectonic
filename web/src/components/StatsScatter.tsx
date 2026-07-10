import { useMemo, useState } from "react";
import type { ScatterPoint } from "../types";
import { CurseIcon } from "./CurseIcon";
import "./StatsScatter.css";

interface Props {
  points: ScatterPoint[];
  xLabel: string;
  yLabel: string;
  // Draws an "equal in both" reference line on a shared X/Y domain --
  // only meaningful when both axes are the same metric (e.g. rating in
  // format A vs rating in format B), so the caller decides when to pass it.
  showDiagonal?: boolean;
  showTrendline?: boolean;
  // Label of the point matched by the Stats page's search bar (first
  // trainer whose name contains the query) -- drawn with a highlight ring
  // and treated as hovered so its tooltip shows without the mouse over it.
  highlightLabel?: string | null;
}

interface Trendline {
  slope: number;
  intercept: number;
  r2: number;
}

function fitTrendline(points: ScatterPoint[]): Trendline | null {
  const n = points.length;
  if (n < 2) return null;
  const xMean = points.reduce((s, p) => s + p.x, 0) / n;
  const yMean = points.reduce((s, p) => s + p.y, 0) / n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (const p of points) {
    const dx = p.x - xMean;
    const dy = p.y - yMean;
    sxy += dx * dy;
    sxx += dx * dx;
    syy += dy * dy;
  }
  if (sxx === 0) return null;
  const slope = sxy / sxx;
  const intercept = yMean - slope * xMean;
  const r2 = syy === 0 ? 1 : (sxy * sxy) / (sxx * syy);
  return { slope, intercept, r2 };
}

// Clips the infinite line y = slope*x + intercept to the [xMin,xMax] x
// [yMin,yMax] box, since a steep fit can otherwise shoot far past the
// plotted data at the box's x extremes.
function clipTrendline(
  t: Trendline,
  xMin: number,
  xMax: number,
  yMin: number,
  yMax: number,
): { x1: number; y1: number; x2: number; y2: number } | null {
  if (t.slope === 0) {
    if (t.intercept < yMin || t.intercept > yMax) return null;
    return { x1: xMin, y1: t.intercept, x2: xMax, y2: t.intercept };
  }
  const xAtYMin = (yMin - t.intercept) / t.slope;
  const xAtYMax = (yMax - t.intercept) / t.slope;
  const xLoFromY = Math.min(xAtYMin, xAtYMax);
  const xHiFromY = Math.max(xAtYMin, xAtYMax);
  const xLo = Math.max(xMin, xLoFromY);
  const xHi = Math.min(xMax, xHiFromY);
  if (xLo >= xHi) return null;
  return { x1: xLo, y1: t.slope * xLo + t.intercept, x2: xHi, y2: t.slope * xHi + t.intercept };
}

const WIDTH = 960;
const HEIGHT = 640;
const MARGIN = { top: 16, right: 16, bottom: 60, left: 72 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;

function niceTicks(min: number, max: number, count = 5): number[] {
  const span = max - min || 1;
  const step = span / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

function fmtTick(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function fmtCoef(v: number): string {
  return v.toFixed(v !== 0 && Math.abs(v) < 1 ? 4 : 2);
}

export function StatsScatter({ points, xLabel, yLabel, showDiagonal, showTrendline, highlightLabel }: Props) {
  // Sticks to the last-hovered point instead of clearing on mouse-leave, so
  // the tooltip stays put while reading rather than vanishing between
  // points -- see onMouseEnter below, there's deliberately no onMouseLeave.
  const [hovered, setHovered] = useState<ScatterPoint | null>(null);

  // The mouse takes priority once it's touched the chart; until then, a
  // search match stands in so the tooltip surfaces the found trainer
  // without requiring a hover.
  const effectiveHovered = hovered ?? points.find((p) => p.label === highlightLabel) ?? null;

  const trendline = useMemo(() => (showTrendline ? fitTrendline(points) : null), [points, showTrendline]);

  const { xMin, xMax, yMin, yMax, xTicks, yTicks } = useMemo(() => {
    if (points.length === 0) {
      return { xMin: 0, xMax: 1, yMin: 0, yMax: 1, xTicks: [0, 1], yTicks: [0, 1] };
    }
    let xlo = Infinity;
    let xhi = -Infinity;
    let ylo = Infinity;
    let yhi = -Infinity;
    for (const p of points) {
      xlo = Math.min(xlo, p.x);
      xhi = Math.max(xhi, p.x);
      ylo = Math.min(ylo, p.y);
      yhi = Math.max(yhi, p.y);
    }
    if (showDiagonal) {
      // Shared domain across both axes so the diagonal is a true y=x line.
      const lo = Math.min(xlo, ylo);
      const hi = Math.max(xhi, yhi);
      const pad = (hi - lo) * 0.08 || 1;
      const min = lo - pad;
      const max = hi + pad;
      return { xMin: min, xMax: max, yMin: min, yMax: max, xTicks: niceTicks(min, max), yTicks: niceTicks(min, max) };
    }
    const xpad = (xhi - xlo) * 0.08 || 1;
    const ypad = (yhi - ylo) * 0.08 || 1;
    const xMin = xlo - xpad;
    const xMax = xhi + xpad;
    const yMin = ylo - ypad;
    const yMax = yhi + ypad;
    return { xMin, xMax, yMin, yMax, xTicks: niceTicks(xMin, xMax), yTicks: niceTicks(yMin, yMax) };
  }, [points, showDiagonal]);

  function x(v: number): number {
    return MARGIN.left + ((v - xMin) / (xMax - xMin)) * PLOT_W;
  }
  function y(v: number): number {
    return MARGIN.top + PLOT_H - ((v - yMin) / (yMax - yMin)) * PLOT_H;
  }

  // Anchors the tooltip to whichever horizontal side of the point has room,
  // instead of always centering -- centering a wide tooltip on a point near
  // the plot's right edge pushed it past the container and forced aggressive
  // word-wrap rather than letting it grow toward the middle of the chart.
  const hoveredPos = effectiveHovered
    ? (() => {
        const leftPct = (x(effectiveHovered.x) / WIDTH) * 100;
        const topPct = (y(effectiveHovered.y) / HEIGHT) * 100;
        const align: "left" | "center" | "right" = leftPct > 70 ? "right" : leftPct < 30 ? "left" : "center";
        return { leftPct, topPct, align };
      })()
    : null;

  return (
    <div className="stats-scatter">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Scatter plot of ${xLabel} vs ${yLabel}`}>
        {xTicks.map((t) => (
          <line key={`vgrid-${t}`} className="scatter-grid" x1={x(t)} x2={x(t)} y1={MARGIN.top} y2={MARGIN.top + PLOT_H} />
        ))}
        {yTicks.map((t) => (
          <line
            key={`hgrid-${t}`}
            className="scatter-grid"
            x1={MARGIN.left}
            x2={WIDTH - MARGIN.right}
            y1={y(t)}
            y2={y(t)}
          />
        ))}
        {yTicks.map((t) => (
          <text key={`ytick-${t}`} className="scatter-tick" x={MARGIN.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
            {fmtTick(t)}
          </text>
        ))}
        {xTicks.map((t) => (
          <text key={`xtick-${t}`} className="scatter-tick" x={x(t)} y={MARGIN.top + PLOT_H + 16} textAnchor="middle">
            {fmtTick(t)}
          </text>
        ))}

        {showDiagonal && (
          <line className="scatter-diagonal" x1={x(xMin)} y1={y(xMin)} x2={x(xMax)} y2={y(xMax)} />
        )}

        {trendline &&
          (() => {
            const seg = clipTrendline(trendline, xMin, xMax, yMin, yMax);
            if (!seg) return null;
            return (
              <line className="scatter-trendline" x1={x(seg.x1)} y1={y(seg.y1)} x2={x(seg.x2)} y2={y(seg.y2)} />
            );
          })()}

        {points.map((p) => {
          const isHovered = effectiveHovered?.label === p.label;
          const isHighlighted = highlightLabel === p.label;
          return (
            <circle
              key={p.label}
              className={`scatter-point scatter-point-neutral${isHighlighted ? " scatter-point-highlighted" : ""}`}
              cx={x(p.x)}
              cy={y(p.y)}
              r={isHovered ? 7 : isHighlighted ? 6 : 4}
              onMouseEnter={() => setHovered(p)}
            />
          );
        })}

        <text className="scatter-axis-label" x={MARGIN.left + PLOT_W / 2} y={HEIGHT - 6} textAnchor="middle">
          {xLabel}
        </text>
        <text
          className="scatter-axis-label"
          x={-(MARGIN.top + PLOT_H / 2)}
          y={14}
          textAnchor="middle"
          transform="rotate(-90)"
        >
          {yLabel}
        </text>
      </svg>

      {(showDiagonal || trendline) && (
        <div className="scatter-legend">
          {showDiagonal && (
            <span className="scatter-legend-item">
              <span className="scatter-legend-line" /> Equal in both
            </span>
          )}
          {trendline && (
            <span className="scatter-legend-item">
              <span className="scatter-legend-line scatter-legend-line-trend" /> Linear trend: y ={" "}
              {fmtCoef(trendline.slope)}x {trendline.intercept >= 0 ? "+" : "-"} {fmtCoef(Math.abs(trendline.intercept))}{" "}
              (R² = {trendline.r2.toFixed(3)})
            </span>
          )}
        </div>
      )}

      {effectiveHovered && hoveredPos && (
        <div
          className={`scatter-tooltip scatter-tooltip-${hoveredPos.align}`}
          style={{ left: `${hoveredPos.leftPct}%`, top: `${hoveredPos.topPct}%` }}
        >
          <strong className="trainer-name">
            {effectiveHovered.cursed && <CurseIcon title="Curse-rolled variant of this trainer" />}
            {effectiveHovered.trainer}
          </strong>
          <div>
            {xLabel}: {fmtTick(effectiveHovered.x)}
          </div>
          <div>
            {yLabel}: {fmtTick(effectiveHovered.y)}
          </div>
        </div>
      )}
    </div>
  );
}

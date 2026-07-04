import { useEffect, useMemo, useState } from "react";
import { FormatPicker } from "../components/FormatPicker";
import { StatsScatter } from "../components/StatsScatter";
import { fetchLeaderboard, fetchTeamLevels, formatKey } from "../lib/dataClient";
import type { BattleType, CurseVariant, LeaderboardRow, ScatterPoint, TeamLevels } from "../types";
import "./StatsPage.css";

type MetricKey = "rating" | "rank" | "winRate" | "avgLevel" | "maxLevel";

interface MetricOption {
  key: MetricKey;
  label: string;
  needsFormat: boolean;
}

const METRICS: MetricOption[] = [
  { key: "avgLevel", label: "Avg team level", needsFormat: false },
  { key: "maxLevel", label: "Max team level", needsFormat: false },
  { key: "rating", label: "Rating", needsFormat: true },
  { key: "rank", label: "Rank", needsFormat: true },
  { key: "winRate", label: "Win rate", needsFormat: true },
];

interface AxisConfig {
  metric: MetricKey;
  battleType: BattleType;
  curseVariant: CurseVariant;
}

function metricOption(key: MetricKey): MetricOption {
  return METRICS.find((m) => m.key === key)!;
}

function formatShortLabel(battleType: BattleType, curseVariant: CurseVariant): string {
  const bt = battleType === "singles" ? "Singles" : "Doubles";
  const cv = curseVariant === "cursed" ? "Cursed" : curseVariant === "uncursed" ? "Uncursed" : "Cursed-excluded";
  return `${bt} / ${cv}`;
}

function axisLabel(axis: AxisConfig): string {
  const opt = metricOption(axis.metric);
  if (!opt.needsFormat) return opt.label;
  return `${formatShortLabel(axis.battleType, axis.curseVariant)} ${opt.label.toLowerCase()}`;
}

function metricValue(
  axis: AxisConfig,
  label: string,
  leaderboards: Record<string, LeaderboardRow[]>,
  teamLevels: TeamLevels | null,
): number | undefined {
  if (axis.metric === "avgLevel") return teamLevels?.[label]?.avgLevel;
  if (axis.metric === "maxLevel") return teamLevels?.[label]?.maxLevel;
  const rows = leaderboards[formatKey(axis.battleType, axis.curseVariant)];
  const row = rows?.find((r) => r.label === label);
  if (!row) return undefined;
  if (axis.metric === "rating") return row.rating;
  if (axis.metric === "rank") return row.rank;
  return row.wldFractions.win;
}

interface AxisPickerProps {
  title: string;
  axis: AxisConfig;
  onChange: (axis: AxisConfig) => void;
}

function AxisPicker({ title, axis, onChange }: AxisPickerProps) {
  return (
    <div className="stats-axis-picker">
      <span className="stats-axis-title">{title}</span>
      <select
        value={axis.metric}
        onChange={(e) => onChange({ ...axis, metric: e.target.value as MetricKey })}
      >
        {METRICS.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
          </option>
        ))}
      </select>
      {metricOption(axis.metric).needsFormat && (
        <FormatPicker
          battleType={axis.battleType}
          curseVariant={axis.curseVariant}
          onChange={(bt, cv) => onChange({ ...axis, battleType: bt, curseVariant: cv })}
        />
      )}
    </div>
  );
}

export function StatsPage() {
  const [axisX, setAxisX] = useState<AxisConfig>({ metric: "maxLevel", battleType: "singles", curseVariant: "cursed" });
  const [axisY, setAxisY] = useState<AxisConfig>({ metric: "rating", battleType: "singles", curseVariant: "cursed" });
  const [showTrendline, setShowTrendline] = useState(false);

  const [teamLevels, setTeamLevels] = useState<TeamLevels | null>(null);
  const [leaderboards, setLeaderboards] = useState<Record<string, LeaderboardRow[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTeamLevels()
      .then(setTeamLevels)
      .catch((err) => setError(String(err)));
  }, []);

  const neededFormats = useMemo(() => {
    const set = new Set<string>();
    if (metricOption(axisX.metric).needsFormat) set.add(formatKey(axisX.battleType, axisX.curseVariant));
    if (metricOption(axisY.metric).needsFormat) set.add(formatKey(axisY.battleType, axisY.curseVariant));
    return [...set];
  }, [axisX, axisY]);

  useEffect(() => {
    let cancelled = false;
    Promise.all(neededFormats.map((fmt) => fetchLeaderboard(fmt).then((rows) => [fmt, rows] as const)))
      .then((entries) => {
        if (!cancelled) setLeaderboards((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neededFormats.join(",")]);

  const ready =
    teamLevels !== null && neededFormats.every((fmt) => leaderboards[fmt] !== undefined);

  const points = useMemo<ScatterPoint[] | null>(() => {
    if (!ready) return null;

    const xFmtRows = metricOption(axisX.metric).needsFormat
      ? leaderboards[formatKey(axisX.battleType, axisX.curseVariant)]
      : null;
    const yFmtRows = metricOption(axisY.metric).needsFormat
      ? leaderboards[formatKey(axisY.battleType, axisY.curseVariant)]
      : null;
    const nameSource = xFmtRows ?? yFmtRows;

    const labelSet = nameSource
      ? nameSource.map((r) => r.label)
      : Object.keys(teamLevels ?? {});

    const nameByLabel = new Map(nameSource?.map((r) => [r.label, r.trainer]) ?? []);

    const out: ScatterPoint[] = [];
    for (const label of labelSet) {
      const x = metricValue(axisX, label, leaderboards, teamLevels);
      const y = metricValue(axisY, label, leaderboards, teamLevels);
      if (x === undefined || y === undefined) continue;
      out.push({ label, trainer: nameByLabel.get(label) ?? label, x, y });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, axisX, axisY, leaderboards, teamLevels]);

  return (
    <div className="page">
      <h1>Stats</h1>
      <div className="stats-picker-row">
        <AxisPicker title="X axis" axis={axisX} onChange={setAxisX} />
        <AxisPicker title="Y axis" axis={axisY} onChange={setAxisY} />
        <label className="stats-trendline-toggle">
          <input type="checkbox" checked={showTrendline} onChange={(e) => setShowTrendline(e.target.checked)} />
          Linear trendline
        </label>
      </div>

      {error && <p className="error">Failed to load data: {error}</p>}
      {!error && !points && <p>Loading...</p>}
      {points && points.length === 0 && <p>No trainers have data for both axes.</p>}
      {points && points.length > 0 && (
        <>
          <StatsScatter
            points={points}
            xLabel={axisLabel(axisX)}
            yLabel={axisLabel(axisY)}
            showDiagonal={axisX.metric === axisY.metric}
            showTrendline={showTrendline}
          />
          <p className="leaderboard-count">{points.length} trainers plotted</p>
        </>
      )}
    </div>
  );
}

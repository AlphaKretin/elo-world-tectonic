import { useMemo, useState } from "react";
import { TIER_ORDER } from "../constants/cardConstants";
import type { LeaderboardRow } from "../types";
import { CurseIcon } from "./CurseIcon";
import "./LeaderboardTable.css";

type SortKey = "rank" | "rating" | "wins" | "losses" | "draws" | "battles" | "tier" | "winRate" | "avgRounds" | "maxRounds";
type CurseFilter = "all" | "cursed" | "uncursed";

interface Props {
  rows: LeaderboardRow[];
  onSelect: (label: string) => void;
}

export function LeaderboardTable({ rows, onSelect }: Props) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [tierFilter, setTierFilter] = useState<Set<string>>(new Set());
  const [curseFilter, setCurseFilter] = useState<CurseFilter>("all");

  const tiers = useMemo(() => {
    const seen = new Set<string>();
    for (const r of rows) {
      if (r.tier) seen.add(r.tier);
    }
    return TIER_ORDER.filter((t) => seen.has(t));
  }, [rows]);

  function tierRank(tier: string | null): number {
    if (!tier) return TIER_ORDER.length;
    const i = TIER_ORDER.indexOf(tier);
    return i === -1 ? TIER_ORDER.length : i;
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();

    const base = rows.filter((r) => {
      if (q && !r.trainer.toLowerCase().includes(q)) return false;
      if (tierFilter.size > 0 && !(r.tier && tierFilter.has(r.tier))) return false;
      if (curseFilter === "cursed" && !r.cursed) return false;
      if (curseFilter === "uncursed" && r.cursed) return false;
      return true;
    });

    const sorted = [...base].sort((a, b) => {
      const av = sortKey === "winRate" ? a.wldFractions.win : sortKey === "tier" ? tierRank(a.tier) : (a[sortKey] ?? "");
      const bv = sortKey === "winRate" ? b.wldFractions.win : sortKey === "tier" ? tierRank(b.tier) : (b[sortKey] ?? "");
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [rows, search, sortKey, sortAsc, tierFilter, curseFilter]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(key === "rank" || key === "tier");
    }
  }

  function toggleTier(tier: string) {
    setTierFilter((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier);
      else next.add(tier);
      return next;
    });
  }

  function clearFilters() {
    setTierFilter(new Set());
    setCurseFilter("all");
  }

  const filtersActive = tierFilter.size > 0 || curseFilter !== "all";

  function sortIndicator(key: SortKey) {
    if (key !== sortKey) return "";
    return sortAsc ? " ^" : " v";
  }

  return (
    <div className="leaderboard">
      <div className="leaderboard-controls">
        <input
          className="leaderboard-search"
          type="search"
          placeholder="Search trainers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="leaderboard-curse-filter" role="group" aria-label="Curse filter">
          {(["all", "cursed", "uncursed"] as CurseFilter[]).map((opt) => (
            <button
              key={opt}
              type="button"
              className={opt === curseFilter ? "active" : ""}
              onClick={() => setCurseFilter(opt)}
            >
              {opt === "all" ? "All" : opt === "cursed" ? "Cursed" : "Uncursed"}
            </button>
          ))}
        </div>
        {filtersActive && (
          <button type="button" className="leaderboard-clear-filters" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>
      {tiers.length > 0 && (
        <div className="leaderboard-tier-filter" role="group" aria-label="Tier filter">
          {tiers.map((tier) => (
            <button
              key={tier}
              type="button"
              className={tierFilter.has(tier) ? "active" : ""}
              onClick={() => toggleTier(tier)}
            >
              {tier}
            </button>
          ))}
        </div>
      )}
      <div className="leaderboard-table-wrap">
        <table className="leaderboard-table">
          <thead>
            <tr>
              <th onClick={() => toggleSort("rank")}>Rank{sortIndicator("rank")}</th>
              <th>Trainer</th>
              <th onClick={() => toggleSort("tier")}>Tier{sortIndicator("tier")}</th>
              <th onClick={() => toggleSort("rating")}>Rating{sortIndicator("rating")}</th>
              <th onClick={() => toggleSort("wins")}>W{sortIndicator("wins")}</th>
              <th onClick={() => toggleSort("losses")}>L{sortIndicator("losses")}</th>
              <th onClick={() => toggleSort("draws")}>D{sortIndicator("draws")}</th>
              <th onClick={() => toggleSort("battles")}>Battles{sortIndicator("battles")}</th>
              <th onClick={() => toggleSort("winRate")}>Win%{sortIndicator("winRate")}</th>
              <th onClick={() => toggleSort("avgRounds")}>Avg rounds{sortIndicator("avgRounds")}</th>
              <th onClick={() => toggleSort("maxRounds")}>Max rounds{sortIndicator("maxRounds")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.label} onClick={() => onSelect(row.label)}>
                <td>{row.rank}</td>
                <td>
                  <span className="trainer-name">
                    {row.cursed && <CurseIcon title="Curse-rolled variant of this fight" />}
                    {row.trainer}
                  </span>
                </td>
                <td>{row.tier ?? "--"}</td>
                <td>{row.rating.toFixed(1)}</td>
                <td>{row.wins}</td>
                <td>{row.losses}</td>
                <td>{row.draws}</td>
                <td>{row.battles}</td>
                <td>{(row.wldFractions.win * 100).toFixed(0)}%</td>
                <td>{row.avgRounds.toFixed(1)}</td>
                <td>{row.maxRounds}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="leaderboard-count">
        {filtered.length} of {rows.length} trainers
      </p>
    </div>
  );
}

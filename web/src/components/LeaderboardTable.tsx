import { useMemo, useState } from "react";
import type { LeaderboardRow } from "../types";
import { RemoteSprite } from "./RemoteSprite";
import "./LeaderboardTable.css";

type SortKey = "rank" | "rating" | "wins" | "losses" | "draws" | "battles" | "tier";

interface Props {
  rows: LeaderboardRow[];
  onSelect: (label: string) => void;
}

export function LeaderboardTable({ rows, onSelect }: Props) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortAsc, setSortAsc] = useState(true);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q ? rows.filter((r) => r.trainer.toLowerCase().includes(q)) : rows;
    const sorted = [...base].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [rows, search, sortKey, sortAsc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(key === "rank");
    }
  }

  function sortIndicator(key: SortKey) {
    if (key !== sortKey) return "";
    return sortAsc ? " ^" : " v";
  }

  return (
    <div className="leaderboard">
      <input
        className="leaderboard-search"
        type="search"
        placeholder="Search trainers..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
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
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.label} onClick={() => onSelect(row.label)}>
                <td>{row.rank}</td>
                <td>
                  <span className="trainer-name">
                    {row.cursed && (
                      <RemoteSprite
                        kind="Items"
                        name="TAROTAMULET_ACTIVE"
                        className="trainer-curse-icon"
                        alt="Cursed"
                        title="Curse-rolled variant of this fight"
                      />
                    )}
                    {row.trainer}
                  </span>
                </td>
                <td>{row.tier ?? "--"}</td>
                <td>{row.rating.toFixed(1)}</td>
                <td>{row.wins}</td>
                <td>{row.losses}</td>
                <td>{row.draws}</td>
                <td>{row.battles}</td>
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

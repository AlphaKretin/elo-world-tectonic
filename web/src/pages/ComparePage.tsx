import { useEffect, useMemo, useState } from "react";
import { CurseIcon } from "../components/CurseIcon";
import { FormatPicker } from "../components/FormatPicker";
import { usePageTitle } from "../hooks/usePageTitle";
import { fetchLeaderboard, formatKey } from "../lib/dataClient";
import { TrainerModalContent } from "./TrainerModal";
import type { BattleType, CurseVariant, FilterVariant, JoinedRow, LeaderboardRow } from "../types";
import "./ComparePage.css";

type SortKey = "trainer" | "rankA" | "ratingA" | "rankB" | "ratingB" | "rankDelta" | "ratingDelta";

export function ComparePage() {
  usePageTitle("Compare", "Compare Pokémon Tectonic trainer rankings and ratings across two tournament formats side by side.");
  const [modalLabel, setModalLabel] = useState<string | null>(null);
  const [battleTypeA, setBattleTypeA] = useState<BattleType>("singles");
  const [curseVariantA, setCurseVariantA] = useState<CurseVariant>("cursed");
  const [filterA, setFilterA] = useState<FilterVariant>("none");
  const [battleTypeB, setBattleTypeB] = useState<BattleType>("singles");
  const [curseVariantB, setCurseVariantB] = useState<CurseVariant>("uncursed");
  const [filterB, setFilterB] = useState<FilterVariant>("none");

  const [rowsA, setRowsA] = useState<LeaderboardRow[] | null>(null);
  const [rowsB, setRowsB] = useState<LeaderboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rankDelta");
  const [sortAsc, setSortAsc] = useState(false);

  const fmtA = formatKey(battleTypeA, curseVariantA, filterA);
  const fmtB = formatKey(battleTypeB, curseVariantB, filterB);

  useEffect(() => {
    let cancelled = false;
    setRowsA(null);
    setError(null);
    fetchLeaderboard(fmtA)
      .then((data) => {
        if (!cancelled) setRowsA(data);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fmtA]);

  useEffect(() => {
    let cancelled = false;
    setRowsB(null);
    setError(null);
    fetchLeaderboard(fmtB)
      .then((data) => {
        if (!cancelled) setRowsB(data);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fmtB]);

  const joined = useMemo<JoinedRow[] | null>(() => {
    if (!rowsA || !rowsB) return null;
    const byLabelB = new Map(rowsB.map((r) => [r.label, r]));
    // cursed is a property of the fight variant itself (see
    // analysis/trainer_cards.py's is_curse_variant), not of the format's
    // curse-variant filter, so it's identical for the same label in both A
    // and B -- one flag per row, not per side.
    const shared: { label: string; trainer: string; cursed: boolean; ratingA: number; ratingB: number }[] = [];
    for (const a of rowsA) {
      const b = byLabelB.get(a.label);
      if (!b) continue;
      shared.push({ label: a.label, trainer: a.trainer, cursed: a.cursed, ratingA: a.rating, ratingB: b.rating });
    }
    // Re-rank within just the shared subset rather than reusing each
    // format's own full-leaderboard rank -- otherwise a trainer missing
    // from the other format inflates every rank below it, making the rank
    // delta look bigger than the actual rating movement warrants.
    const rankByLabelA = new Map(
      [...shared].sort((x, y) => y.ratingA - x.ratingA).map((r, i) => [r.label, i + 1]),
    );
    const rankByLabelB = new Map(
      [...shared].sort((x, y) => y.ratingB - x.ratingB).map((r, i) => [r.label, i + 1]),
    );
    return shared.map((r) => ({
      ...r,
      rankA: rankByLabelA.get(r.label)!,
      rankB: rankByLabelB.get(r.label)!,
    }));
  }, [rowsA, rowsB]);

  const filtered = useMemo(() => {
    if (!joined) return null;
    const q = search.trim().toLowerCase();
    const base = q ? joined.filter((r) => r.trainer.toLowerCase().includes(q)) : joined;
    const sorted = [...base].sort((a, b) => {
      const av =
        sortKey === "rankDelta" ? a.rankB - a.rankA
        : sortKey === "ratingDelta" ? a.ratingB - a.ratingA
        : a[sortKey];
      const bv =
        sortKey === "rankDelta" ? b.rankB - b.rankA
        : sortKey === "ratingDelta" ? b.ratingB - b.ratingA
        : b[sortKey];
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [joined, search, sortKey, sortAsc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(key === "trainer");
    }
  }

  function sortIndicator(key: SortKey) {
    if (key !== sortKey) return "";
    return sortAsc ? " ^" : " v";
  }

  const sameFormat = fmtA === fmtB;
  // A cursed/uncursed pair of the SAME battle type + filter is fit
  // together against a shared battle-graph anchor (see analysis/ratings.py's
  // compute_anchored_uncursed_pair) instead of each independently to zero,
  // so rating_delta is a real quantity for exactly this combination --
  // still not for any other pair (e.g. singles vs doubles), where each
  // side's zero-point is wherever its own independent fit happened to
  // settle. See project_ratings_convergence_and_anchored_comparison memory
  // / 2026-07-08 session for the full reasoning.
  const isAnchoredPair =
    !sameFormat && battleTypeA === battleTypeB && filterA === filterB && curseVariantA !== curseVariantB;

  return (
    <div className="page">
      <h1>Compare formats</h1>
      <div className="compare-picker-row">
        <div className="compare-picker-col">
          <span className="compare-picker-label">Format A</span>
          <FormatPicker
            battleType={battleTypeA}
            curseVariant={curseVariantA}
            filter={filterA}
            onChange={(bt, cv, f) => {
              setBattleTypeA(bt);
              setCurseVariantA(cv);
              setFilterA(f);
            }}
          />
        </div>
        <div className="compare-picker-col">
          <span className="compare-picker-label">Format B</span>
          <FormatPicker
            battleType={battleTypeB}
            curseVariant={curseVariantB}
            filter={filterB}
            onChange={(bt, cv, f) => {
              setBattleTypeB(bt);
              setCurseVariantB(cv);
              setFilterB(f);
            }}
          />
        </div>
      </div>

      {error && <p className="error">Failed to load leaderboard: {error}</p>}
      {sameFormat && <p className="compare-hint">Pick two different formats to compare.</p>}
      {!error && !sameFormat && !filtered && <p>Loading...</p>}
      {!sameFormat && filtered && !isAnchoredPair && (
        <p className="compare-hint">
          Ratings aren't directly comparable across these two formats -- compare by rank change.
        </p>
      )}

      {!sameFormat && filtered && (
        <>
          <div className="compare-table-controls">
            <input
              className="leaderboard-search"
              type="search"
              placeholder="Search trainers..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="leaderboard-table-wrap">
            <table className="leaderboard-table">
              <thead>
                <tr>
                  <th onClick={() => toggleSort("trainer")}>Trainer{sortIndicator("trainer")}</th>
                  <th onClick={() => toggleSort("rankA")}>Rank A{sortIndicator("rankA")}</th>
                  <th onClick={() => toggleSort("ratingA")}>Rating A{sortIndicator("ratingA")}</th>
                  <th onClick={() => toggleSort("rankB")}>Rank B{sortIndicator("rankB")}</th>
                  <th onClick={() => toggleSort("ratingB")}>Rating B{sortIndicator("ratingB")}</th>
                  <th onClick={() => toggleSort("rankDelta")}>Δ Rank (B - A){sortIndicator("rankDelta")}</th>
                  {isAnchoredPair && (
                    <th onClick={() => toggleSort("ratingDelta")}>
                      Δ Rating (B - A){sortIndicator("ratingDelta")}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => {
                  const rankDelta = row.rankB - row.rankA;
                  const ratingDelta = row.ratingB - row.ratingA;
                  return (
                    <tr key={row.label} onClick={() => setModalLabel(row.label)}>
                      <td>
                        <span className="trainer-name">
                          {row.cursed && <CurseIcon title="Curse-rolled variant of this fight" />}
                          {row.trainer}
                        </span>
                      </td>
                      <td>{row.rankA}</td>
                      <td>{row.ratingA.toFixed(1)}</td>
                      <td>{row.rankB}</td>
                      <td>{row.ratingB.toFixed(1)}</td>
                      <td className={rankDelta < 0 ? "compare-delta-pos" : rankDelta > 0 ? "compare-delta-neg" : ""}>
                        {rankDelta > 0 ? "+" : ""}
                        {rankDelta}
                      </td>
                      {isAnchoredPair && (
                        <td
                          className={
                            ratingDelta > 0 ? "compare-delta-pos" : ratingDelta < 0 ? "compare-delta-neg" : ""
                          }
                        >
                          {ratingDelta > 0 ? "+" : ""}
                          {ratingDelta.toFixed(1)}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="leaderboard-count">
            {filtered.length} trainers in both formats
          </p>
        </>
      )}

      {modalLabel && (
        <TrainerModalContent
          battleType={battleTypeA}
          curseVariant={curseVariantA}
          filter={filterA}
          label={modalLabel}
          onClose={() => setModalLabel(null)}
          onOpenTrainer={setModalLabel}
        />
      )}
    </div>
  );
}

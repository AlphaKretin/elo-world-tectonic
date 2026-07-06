import { useEffect, useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router-dom";
import { FormatPicker } from "../components/FormatPicker";
import { LeaderboardTable } from "../components/LeaderboardTable";
import { fetchLeaderboard, fetchMeta, formatKey } from "../lib/dataClient";
import { isValidFormat, nearestValidFormat } from "../lib/formatValidity";
import type { BattleType, CurseVariant, FilterVariant, LeaderboardRow } from "../types";

const VALID_BATTLE_TYPES: BattleType[] = ["singles", "doubles"];
const VALID_CURSE_VARIANTS: CurseVariant[] = ["cursed", "uncursed"];
const VALID_FILTERS: FilterVariant[] = ["none", "cursed_excluded", "level70_only"];

export function LeaderboardPage() {
  const params = useParams();
  const navigate = useNavigate();
  const battleType = VALID_BATTLE_TYPES.includes(params.battleType as BattleType)
    ? (params.battleType as BattleType)
    : "singles";
  const curseVariant = VALID_CURSE_VARIANTS.includes(params.curseVariant as CurseVariant)
    ? (params.curseVariant as CurseVariant)
    : "cursed";
  const filter = VALID_FILTERS.includes(params.filter as FilterVariant)
    ? (params.filter as FilterVariant)
    : "none";

  const [rows, setRows] = useState<LeaderboardRow[] | null>(null);
  const [availableFormats, setAvailableFormats] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fmt = formatKey(battleType, curseVariant, filter);

  useEffect(() => {
    fetchMeta()
      .then((meta) => setAvailableFormats(meta.availableFormats))
      .catch((err) => setError(String(err)));
  }, []);

  // Backup handler for a bad combination reached by hand (typed/bookmarked
  // URL) rather than through the picker, which already prevents picking
  // one -- redirects to the nearest valid combination instead of letting
  // the fetch below 404.
  useEffect(() => {
    if (!availableFormats) return;
    if (isValidFormat(availableFormats, battleType, curseVariant, filter)) return;
    const [nextBattleType, nextCurseVariant, nextFilter] = nearestValidFormat(availableFormats, battleType, curseVariant, filter);
    navigate(`/${nextBattleType}/${nextCurseVariant}/${nextFilter}`, { replace: true });
  }, [availableFormats, battleType, curseVariant, filter, navigate]);

  useEffect(() => {
    if (availableFormats && !isValidFormat(availableFormats, battleType, curseVariant, filter)) return;
    let cancelled = false;
    setRows(null);
    setError(null);
    fetchLeaderboard(fmt)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fmt, availableFormats, battleType, curseVariant, filter]);

  function handleFormatChange(nextBattleType: BattleType, nextCurseVariant: CurseVariant, nextFilter: FilterVariant) {
    navigate(`/${nextBattleType}/${nextCurseVariant}/${nextFilter}`);
  }

  function handleSelect(label: string) {
    navigate(`/${battleType}/${curseVariant}/${filter}/${encodeURIComponent(label)}`);
  }

  return (
    <div className="page">
      <h1>ELO World: Tectonic -- Leaderboard</h1>
      <FormatPicker battleType={battleType} curseVariant={curseVariant} filter={filter} onChange={handleFormatChange} />
      {error && <p className="error">Failed to load leaderboard: {error}</p>}
      {!error && !rows && <p>Loading...</p>}
      {rows && <LeaderboardTable rows={rows} onSelect={handleSelect} />}
      <Outlet />
    </div>
  );
}

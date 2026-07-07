import { formatKey } from "./dataClient";
import type { BattleType, CurseVariant, FilterVariant } from "../types";

// Whether battleType/curseVariant/filter has a generated dataset, per
// meta.json's availableFormats (itself derived from analysis/
// export_web_data.py's FORMAT_SPECS) -- this is the same list the site
// build actually exports from, so a combination can't look valid here
// while 404ing at fetch time, or vice versa.
export function isValidFormat(
  availableFormats: string[],
  battleType: BattleType,
  curseVariant: CurseVariant,
  filter: FilterVariant,
): boolean {
  return availableFormats.includes(formatKey(battleType, curseVariant, filter));
}

// Where to land when the current combo turns out invalid (typed/bookmarked
// URL, or an axis change made the existing pairing on another axis stop
// working).
export function nearestValidFormat(
  availableFormats: string[],
  battleType: BattleType,
  curseVariant: CurseVariant,
  filter: FilterVariant,
): [BattleType, CurseVariant, FilterVariant] {
  if (isValidFormat(availableFormats, battleType, curseVariant, filter)) return [battleType, curseVariant, filter];
  // export_web_data.py skips publishing an _uncursed variant of a filter
  // whose whole trainer cohort has no cursed trainer (it'd be a
  // byte-identical duplicate of the plain cursed default -- see
  // results_lib.filter_has_cursed_population, e.g. developer_only). Try
  // the cursed variant of the SAME filter before giving up the filter
  // entirely, since dropping curseVariant back to the unmodified default
  // is less surprising than silently discarding the filter the user chose.
  if (curseVariant === "uncursed" && isValidFormat(availableFormats, battleType, "cursed", filter)) {
    return [battleType, "cursed", filter];
  }
  // Otherwise drop the filter back to "none" -- silently discarding a
  // filter is less surprising than silently changing battle type.
  return [battleType, curseVariant, "none"];
}

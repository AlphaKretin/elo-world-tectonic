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
// working) -- drops the filter back to "none" first, since silently
// discarding a filter is less surprising than silently changing curse
// variant or battle type.
export function nearestValidFormat(
  availableFormats: string[],
  battleType: BattleType,
  curseVariant: CurseVariant,
  filter: FilterVariant,
): [BattleType, CurseVariant, FilterVariant] {
  if (isValidFormat(availableFormats, battleType, curseVariant, filter)) return [battleType, curseVariant, filter];
  return [battleType, curseVariant, "none"];
}

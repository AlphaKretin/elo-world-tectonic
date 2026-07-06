import type { BattleType, CurseVariant, FilterVariant, FormatMeta, LeaderboardRow, TeamLevels, TrainerStatic } from "../types";

// The backend's format string is battleType, optionally with "_uncursed"
// (a genuinely different battle-results dataset), optionally with a
// results_lib.FILTERS name appended (a post-hoc row filter over whichever
// dataset that already is) -- see analysis/export_web_data.py's FORMATS
// list. "cursed"/"none" are each the no-suffix default for their factor.
export function formatKey(battleType: BattleType, curseVariant: CurseVariant, filter: FilterVariant): string {
  let key: string = battleType;
  if (curseVariant === "uncursed") key += "_uncursed";
  if (filter !== "none") key += `_${filter}`;
  return key;
}

function dataUrl(path: string): string {
  return `${import.meta.env.BASE_URL}data/${path}`;
}

const jsonCache = new Map<string, Promise<unknown>>();

function fetchJsonCached<T>(url: string): Promise<T> {
  if (!jsonCache.has(url)) {
    jsonCache.set(
      url,
      fetch(url).then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
        return res.json();
      }),
    );
  }
  return jsonCache.get(url) as Promise<T>;
}

export function fetchLeaderboard(fmt: string): Promise<LeaderboardRow[]> {
  return fetchJsonCached(dataUrl(`${fmt}/leaderboard.json`));
}

// Dataset-wide layout decisions (moveset grid columns, sprite scale) are
// identical across every format -- one shared meta.json, not one per format.
export function fetchMeta(): Promise<FormatMeta> {
  return fetchJsonCached(dataUrl("meta.json"));
}

// Format-independent team level (avg/max party level) per trainer -- one
// shared file, same reasoning as fetchMeta above (see export_team_levels
// in analysis/export_web_data.py).
export function fetchTeamLevels(): Promise<TeamLevels> {
  return fetchJsonCached(dataUrl("team_levels.json"));
}

function safeFilename(label: string): string {
  return label.replaceAll(":", "_").replaceAll("#", "_v");
}

// Static (format-independent) trainer data -- identity, party, tribe
// bonuses -- lives in one shared file per trainer, not duplicated per
// format (see analysis/export_web_data.py's static_trainer_payload).
export function fetchTrainerStatic(label: string): Promise<TrainerStatic> {
  return fetchJsonCached(dataUrl(`trainers/${safeFilename(label)}.json`));
}

export async function fetchLeaderboardRow(fmt: string, label: string): Promise<LeaderboardRow | undefined> {
  const rows = await fetchLeaderboard(fmt);
  return rows.find((r) => r.label === label);
}

export function assetUrl(path: string): string {
  return `${import.meta.env.BASE_URL}assets/${path}`;
}

// Non-shiny Pokemon/Trainer/Item sprites are hotlinked from Luna's own
// tectonic-tools Sirv CDN (same species/trainer_type/item identifiers as
// vendor/tectonic-content, confirmed by inspecting that repo directly) --
// she owns both the CDN and the repo, so this isn't a hotlinking-etiquette
// concern, and it avoids committing ~1200 near-duplicate sprite files to
// this repo. Falls back to the CDN's own GitHub-raw mirror on error (same
// two-tier fallback tectonic-tools' own ImageFallback component uses).
const SIRV_ROOT = "https://tectonictools.sirv.com/Images/public";
const GITHUB_RAW_ROOT = "https://raw.githubusercontent.com/AlphaKretin/tectonic-tools/refs/heads/main/public";

export function remoteSpriteUrl(kind: "Pokemon" | "Trainers" | "Items", name: string): string {
  return `${SIRV_ROOT}/${kind}/${name}.png`;
}

export function remoteSpriteFallbackUrl(kind: "Pokemon" | "Trainers" | "Items", name: string): string {
  return `${GITHUB_RAW_ROOT}/${kind}/${name}.png`;
}

export type BattleType = "singles" | "doubles";
// Whether curse effects were rolled as-is or re-battled/stripped -- a real
// difference in underlying battle results, unlike FilterVariant below.
export type CurseVariant = "cursed" | "uncursed";
// A post-hoc row filter applied on top of a battleType/curseVariant's
// results (see analysis/results_lib.py's FILTERS registry) -- doesn't
// change what was battled, only which battles count toward the rating fit.
export type FilterVariant = "none" | "cursed_excluded" | "level70_only" | "developer_only";

export interface OpponentRef {
  label: string;
  display: string;
  cursed: boolean;
}

export interface BestWorstEntry {
  rating: number;
  opponentRank: number | null;
  seed: number;
  opponent: OpponentRef;
}

export interface WldFractions {
  win: number;
  draw: number;
  loss: number;
}

// Everything about a trainer's result that VARIES by format -- rank/rating/
// record/best-worst. Paired with the trainer's static payload (see
// TrainerStatic below) by `label`, which is shared across both.
export interface LeaderboardRow {
  label: string;
  trainer: string;
  cursed: boolean;
  rating: number;
  se: number;
  ciLow: number;
  ciHigh: number;
  wins: number;
  losses: number;
  draws: number;
  battles: number;
  rank: number;
  overlap: number | null;
  tier: string | null;
  tierColor: [number, number, number] | null;
  wldFractions: WldFractions;
  bestWin: BestWorstEntry | null;
  worstLoss: BestWorstEntry | null;
  // Avg/max length (in rounds) of this trainer's battles in this format --
  // see analysis/export_web_data.py's round_stats_by_label.
  avgRounds: number;
  maxRounds: number;
}

// Per-trainer format-independent team level summary (avg/max of party
// levels), keyed by label -- see analysis/export_web_data.py's
// export_team_levels. One file covering every trainer, so the Stats page
// can plot team level against any format's ratings without fetching each
// trainer's static payload individually.
export interface TeamLevelEntry {
  avgLevel: number;
  maxLevel: number;
  cursed: boolean;
}

export type TeamLevels = Record<string, TeamLevelEntry>;

export interface FormatMeta {
  moveGridColumns: 1 | 2;
  maxNativeSpriteDim: number;
  spriteScale: number;
  // formatKey()-shaped strings the site has data for (see
  // analysis/export_web_data.py's FORMATS/FORMAT_SPECS) -- the single
  // source of truth for which battleType/curseVariant/filter combinations
  // are selectable, so the picker doesn't hand-maintain its own copy.
  availableFormats: string[];
}

export interface TribeBonus {
  tribeId: string;
  count: number;
  threshold: number;
  name: string;
}

export interface MoveInfo {
  name: string;
  type: string;
}

export interface HeldItem {
  id: string;
  name: string;
}

export interface PartyMember {
  species: string;
  speciesDisplay: string;
  level: number;
  shiny: boolean;
  nickname: string | null;
  tribes: string[];
  heldItems: HeldItem[];
  moves: MoveInfo[];
}

export interface IdentityRef {
  trainerType: string;
  realName: string;
}

// The static (format-independent) half of a trainer's card -- identity,
// party, curse-authoring, tribe bonuses. Combine with a LeaderboardRow
// (same `label`) for the format-dependent half (rank/rating/record/
// best-worst) to render a full TrainerCard.
// Row shape produced by joining two leaderboard formats by trainer `label`
// (see pages/ComparePage.tsx) -- shared with components/RatingScatter.tsx.
export interface JoinedRow {
  label: string;
  trainer: string;
  cursed: boolean;
  rankA: number;
  ratingA: number;
  rankB: number;
  ratingB: number;
}

// Generic point for the Stats page's axis-picker scatter (components/
// StatsScatter.tsx) -- x/y can be any chosen metric (rating, win rate,
// team level...), unlike JoinedRow's fixed rating-vs-rating shape.
export interface ScatterPoint {
  label: string;
  trainer: string;
  cursed: boolean;
  x: number;
  y: number;
}

export interface TrainerStatic {
  label: string;
  title: string;
  trainerType: string;
  identities: IdentityRef[];
  trueNames: string[];
  isCursed: boolean;
  avgLevel: number;
  maxLevel: number;
  tribeBonuses: TribeBonus[];
  party: PartyMember[];
}

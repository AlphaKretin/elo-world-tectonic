// Mirrors analysis/card_constants.py (TYPE_COLORS) and the hand-tuned
// identity-peek offsets in analysis/trainer_cards.py -- kept as a manual
// sync point per the website build plan (§2), not auto-generated, since
// these rarely change. Tier colors are NOT duplicated here: they travel
// with each card payload as `tierColor` from the Python export instead,
// since that's already computed server-side per trainer.

export const TYPE_COLORS: Record<string, [number, number, number]> = {
  NORMAL: [130, 130, 130],
  FIGHTING: [228, 144, 33],
  FLYING: [116, 170, 208],
  POISON: [147, 84, 203],
  GROUND: [164, 115, 60],
  ROCK: [169, 164, 129],
  BUG: [159, 159, 40],
  GHOST: [111, 69, 112],
  STEEL: [119, 178, 203],
  FIRE: [228, 97, 62],
  WATER: [48, 153, 225],
  GRASS: [67, 152, 55],
  ELECTRIC: [223, 188, 40],
  PSYCHIC: [233, 108, 140],
  ICE: [71, 200, 200],
  DRAGON: [87, 111, 188],
  DARK: [79, 71, 71],
  FAIRY: [225, 140, 225],
  QMARKS: [68, 68, 68],
  MUTANT: [162, 114, 146],
};

// Mutant has its own icon; anything else without dedicated art (Flex) falls
// back to the "unknown" glyph, same as trainer_cards.py's TYPE_ICON_FALLBACK.
export const TYPE_ICON_FILES: Record<string, string> = {
  NORMAL: "Normal.svg", FIGHTING: "Fighting.svg", FLYING: "Flying.svg",
  POISON: "Poison.svg", GROUND: "Ground.svg", ROCK: "Rock.svg",
  BUG: "Bug.svg", GHOST: "Ghost.svg", STEEL: "Steel.svg",
  FIRE: "Fire.svg", WATER: "Water.svg", GRASS: "Grass.svg",
  ELECTRIC: "Electric.svg", PSYCHIC: "Psychic.svg", ICE: "Ice.svg",
  DRAGON: "Dragon.svg", DARK: "Dark.svg", FAIRY: "Fairy.svg",
  QMARKS: "QMarks.svg", MUTANT: "Mutant.svg",
};
export const TYPE_ICON_FALLBACK = "QMarks.svg";

// High -> low, mirroring analysis/card_constants.py's TIER_COLORS keys
// (defined low -> high there) -- used for tier chip ordering and sorting on
// the leaderboard, since plain string sort puts "A-" before "A+" and "S"
// before "S+".
export const TIER_ORDER = [
  "S+", "S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F",
];

export function readableTextColor([r, g, b]: [number, number, number]): string {
  const luminance = 0.299 * r + 0.587 * g + 0.114 * b;
  return luminance > 140 ? "#141a2e" : "#ffffff";
}

export function rgb([r, g, b]: [number, number, number]): string {
  return `rgb(${r}, ${g}, ${b})`;
}

// Design-space x-offset (as a fraction of portrait width) for a masked
// villain's identity peek -- ported from trainer_cards.py's
// IDENTITY_OFFSET_* constants (there: pixels on a 260px-wide portrait box
// at design scale). Expressed here as a fraction of portrait width so it
// scales with whatever CSS size the portrait box actually renders at.
const PORTRAIT_DESIGN_SIZE = 260;
export const IDENTITY_OFFSET_SINGLE = 70 / PORTRAIT_DESIGN_SIZE;
const IDENTITY_OFFSET_DOUBLE_FAR_RIGHT = 100 / PORTRAIT_DESIGN_SIZE;
const IDENTITY_OFFSET_DOUBLE_GAP = -4 / PORTRAIT_DESIGN_SIZE;

// Hand-tuned per mask geometry, not derived (see trainer_cards.py's own
// IMOGENE_OFFSETS comment) -- Imogene A peeks into the gap between the two
// hoods, Imogene B gets the full far-right treatment.
const IMOGENE_OFFSETS: Record<string, number> = {
  TRAINER_Imogene_A: IDENTITY_OFFSET_DOUBLE_GAP,
  TRAINER_Imogene_B: IDENTITY_OFFSET_DOUBLE_FAR_RIGHT,
};

export function identityOffsets(
  identities: { trainerType: string; realName: string }[],
): { trainerType: string; realName: string; offsetFraction: number }[] {
  const types = new Set(identities.map((i) => i.trainerType));
  const imogeneTypes = new Set(Object.keys(IMOGENE_OFFSETS));
  const isImogenePair =
    types.size === imogeneTypes.size && [...types].every((t) => imogeneTypes.has(t));
  if (isImogenePair) {
    return identities.map((i) => ({ ...i, offsetFraction: IMOGENE_OFFSETS[i.trainerType] }));
  }
  return identities.map((i) => ({ ...i, offsetFraction: IDENTITY_OFFSET_SINGLE }));
}

import type { BattleType, CurseVariant, FilterVariant } from "../types";
import "./FormatPicker.css";

const BATTLE_TYPES: { value: BattleType; label: string }[] = [
  { value: "singles", label: "Singles" },
  { value: "doubles", label: "Doubles" },
];

const CURSE_VARIANTS: { value: CurseVariant; label: string; hint: string }[] = [
  { value: "cursed", label: "Cursed", hint: "Base tournament, curses active as rolled" },
  { value: "uncursed", label: "Uncursed", hint: "Curse effects re-battled and stripped" },
];

const FILTER_VARIANTS: { value: FilterVariant; label: string; hint: string }[] = [
  { value: "none", label: "None", hint: "Every battle counts toward the fit" },
  { value: "cursed_excluded", label: "Cursed-excluded", hint: "Cursed battles dropped from the fit entirely" },
  { value: "level70_only", label: "Level 70 only", hint: "Only battles between two 6-Pokemon, all-level-70 trainers" },
];

interface Props {
  battleType: BattleType;
  curseVariant: CurseVariant;
  filter: FilterVariant;
  onChange: (battleType: BattleType, curseVariant: CurseVariant, filter: FilterVariant) => void;
}

export function FormatPicker({ battleType, curseVariant, filter, onChange }: Props) {
  return (
    <div className="format-picker">
      <div className="format-picker-group" role="group" aria-label="Battle type">
        {BATTLE_TYPES.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={opt.value === battleType ? "active" : ""}
            onClick={() => onChange(opt.value, curseVariant, filter)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="format-picker-group" role="group" aria-label="Curse variant">
        {CURSE_VARIANTS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={opt.value === curseVariant ? "active" : ""}
            title={opt.hint}
            onClick={() => onChange(battleType, opt.value, filter)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="format-picker-group" role="group" aria-label="Filter">
        {FILTER_VARIANTS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={opt.value === filter ? "active" : ""}
            title={opt.hint}
            onClick={() => onChange(battleType, curseVariant, opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

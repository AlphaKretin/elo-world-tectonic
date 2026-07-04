import type { BattleType, CurseVariant } from "../types";
import "./FormatPicker.css";

const BATTLE_TYPES: { value: BattleType; label: string }[] = [
  { value: "singles", label: "Singles" },
  { value: "doubles", label: "Doubles" },
];

const CURSE_VARIANTS: { value: CurseVariant; label: string; hint: string }[] = [
  { value: "cursed", label: "Cursed", hint: "Base tournament, curses active as rolled" },
  { value: "uncursed", label: "Uncursed", hint: "Curse effects re-battled and stripped" },
  { value: "cursed_excluded", label: "Cursed-excluded", hint: "Cursed battles dropped from the fit entirely" },
];

interface Props {
  battleType: BattleType;
  curseVariant: CurseVariant;
  onChange: (battleType: BattleType, curseVariant: CurseVariant) => void;
}

export function FormatPicker({ battleType, curseVariant, onChange }: Props) {
  return (
    <div className="format-picker">
      <div className="format-picker-group" role="group" aria-label="Battle type">
        {BATTLE_TYPES.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={opt.value === battleType ? "active" : ""}
            onClick={() => onChange(opt.value, curseVariant)}
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
            onClick={() => onChange(battleType, opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

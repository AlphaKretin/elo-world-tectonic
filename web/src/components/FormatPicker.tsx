import { useEffect, useState } from "react";
import { fetchMeta } from "../lib/dataClient";
import { isValidFormat } from "../lib/formatValidity";
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
  { value: "developer_only", label: "Developers only", hint: "Only battles between two developer-labeled trainers" },
];

interface Props {
  battleType: BattleType;
  curseVariant: CurseVariant;
  filter: FilterVariant;
  onChange: (battleType: BattleType, curseVariant: CurseVariant, filter: FilterVariant) => void;
}

export function FormatPicker({ battleType, curseVariant, filter, onChange }: Props) {
  // null until loaded -- treated as "every combo valid" below so the picker
  // doesn't flash all-disabled on first render. fetchMeta() is cached, so
  // multiple FormatPicker instances on one page (e.g. ComparePage's A/B
  // pickers) share a single fetch.
  const [availableFormats, setAvailableFormats] = useState<string[] | null>(null);
  useEffect(() => {
    fetchMeta()
      .then((meta) => setAvailableFormats(meta.availableFormats))
      .catch(() => {});
  }, []);
  const isValid = (bt: BattleType, cv: CurseVariant, f: FilterVariant) =>
    availableFormats === null || isValidFormat(availableFormats, bt, cv, f);

  return (
    <div className="format-picker">
      <div className="format-picker-group" role="group" aria-label="Battle type">
        {BATTLE_TYPES.map((opt) => {
          const valid = isValid(opt.value, curseVariant, filter);
          return (
            <button
              key={opt.value}
              type="button"
              className={opt.value === battleType ? "active" : ""}
              disabled={!valid}
              title={valid ? undefined : "No data for this combination"}
              onClick={() => onChange(opt.value, curseVariant, filter)}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <div className="format-picker-group" role="group" aria-label="Curse variant">
        {CURSE_VARIANTS.map((opt) => {
          const valid = isValid(battleType, opt.value, filter);
          return (
            <button
              key={opt.value}
              type="button"
              className={opt.value === curseVariant ? "active" : ""}
              disabled={!valid}
              title={valid ? opt.hint : "No data for this combination"}
              onClick={() => onChange(battleType, opt.value, filter)}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <div className="format-picker-group" role="group" aria-label="Filter">
        {FILTER_VARIANTS.map((opt) => {
          const valid = isValid(battleType, curseVariant, opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              className={opt.value === filter ? "active" : ""}
              disabled={!valid}
              title={valid ? opt.hint : "No data for this combination"}
              onClick={() => onChange(battleType, curseVariant, opt.value)}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

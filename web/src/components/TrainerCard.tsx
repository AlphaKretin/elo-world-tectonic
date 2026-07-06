import { forwardRef } from "react";
import { identityOffsets, readableTextColor, rgb, TYPE_COLORS, TYPE_ICON_FALLBACK, TYPE_ICON_FILES } from "../constants/cardConstants";
import { assetUrl } from "../lib/dataClient";
import type { BestWorstEntry, FormatMeta, LeaderboardRow, TrainerStatic, WldFractions } from "../types";
import { CroppedTrainerSprite } from "./CroppedTrainerSprite";
import { RemoteSprite } from "./RemoteSprite";
import "./TrainerCard.css";

// Pixel art scales by a fixed integer multiple of native size, never fit-to-
// box -- see trainer_cards.py's own SPRITE_SCALE/ITEM_ICON_SCALE comments
// for why (it preserves true relative scale between Pokemon/items). Halved
// from the PNG renderer's own constants (Luna's request: the Pokemon sprite
// and held-item icon read as oversized on the web card; the trainer
// portrait/curse badge above them were already sized correctly and are
// untouched).
const POKEMON_SPRITE_SCALE_FACTOR = 0.5;
const ITEM_ICON_SCALE = 1;

interface Props {
  trainer: TrainerStatic;
  row: LeaderboardRow;
  meta: FormatMeta;
  onOpenTrainer?: (label: string) => void;
}

function TierBadge({ tier, color }: { tier: string | null; color: [number, number, number] | null }) {
  if (!tier || !color) return null;
  return (
    <div className="tier-badge" style={{ background: rgb(color), color: readableTextColor(color) }}>
      {tier}
    </div>
  );
}

function WldBar({ wldFractions }: { wldFractions: WldFractions }) {
  const segments: { key: "win" | "draw" | "loss"; className: string }[] = [
    { key: "win", className: "wld-win" },
    { key: "draw", className: "wld-draw" },
    { key: "loss", className: "wld-loss" },
  ];
  return (
    <div className="wld-bar">
      {segments
        .filter((s) => wldFractions[s.key] > 0)
        .map((s) => (
          <div key={s.key} className={`wld-segment ${s.className}`} style={{ flexGrow: wldFractions[s.key] }} />
        ))}
    </div>
  );
}

function MoveCapsule({ move }: { move: { name: string; type: string } }) {
  const color = TYPE_COLORS[move.type] ?? TYPE_COLORS.QMARKS;
  const iconFile = TYPE_ICON_FILES[move.type] ?? TYPE_ICON_FALLBACK;
  return (
    <div className="move-capsule" style={{ background: rgb(color), color: readableTextColor(color) }}>
      <span className="move-capsule-icon" style={{ background: rgb(color) }}>
        <img src={assetUrl(`types/${iconFile}`)} alt={move.type} />
      </span>
      <span className="move-capsule-name">{move.name}</span>
    </div>
  );
}

function opponentLine(prefix: string, entry: BestWorstEntry | null, onOpenTrainer?: (label: string) => void) {
  if (!entry) {
    return <p className="card-line dim">{prefix}: --</p>;
  }
  const { opponent, rating, opponentRank, seed } = entry;
  return (
    <p className="card-line">
      {prefix}:{" "}
      {opponent.cursed && (
        <RemoteSprite kind="Items" name="TAROTAMULET_ACTIVE" className="inline-badge" alt="cursed" title="Cursed opponent" />
      )}
      {onOpenTrainer ? (
        <button type="button" className="link-button" onClick={() => onOpenTrainer(opponent.label)}>
          {opponent.display}
        </button>
      ) : (
        opponent.display
      )}{" "}
      ({opponentRank !== null ? `#${opponentRank}, ` : ""}
      {rating.toFixed(0)})
      <span className="seed">Seed: {seed}</span>
    </p>
  );
}

export const TrainerCard = forwardRef<HTMLDivElement, Props>(function TrainerCard(
  { trainer, row, meta, onOpenTrainer },
  ref,
) {
  const portraitBox = Math.max(120, meta.maxNativeSpriteDim * meta.spriteScale * 0.6);
  const pokemonSpriteScale = meta.spriteScale * POKEMON_SPRITE_SCALE_FACTOR;
  const spriteBox = meta.maxNativeSpriteDim * pokemonSpriteScale;
  const offsets = identityOffsets(trainer.identities);

  return (
    <div className="trainer-card" ref={ref}>
      <div className="card-header">
        <TierBadge tier={row.tier} color={row.tierColor} />
        {trainer.isCursed && (
          <RemoteSprite kind="Items" name="TAROTAMULET_ACTIVE" className="curse-badge" alt="Cursed trainer" />
        )}
        <div className="header-body">
          <div className="portrait-wrap" style={{ width: portraitBox, height: portraitBox }}>
            {offsets.map(({ trainerType, offsetFraction }) => (
              <CroppedTrainerSprite
                key={trainerType}
                name={trainerType}
                boxSize={portraitBox}
                className="identity-sprite"
                alt=""
                style={{ left: `${50 + offsetFraction * 100}%` }}
              />
            ))}
            <CroppedTrainerSprite name={trainer.trainerType} boxSize={portraitBox} className="portrait-sprite" alt={trainer.title} />
          </div>
          <div className="header-text">
            <h2 className="card-title">{trainer.title}</h2>
            <p className="rank-line">
              #{row.rank} overall &middot; {row.rating.toFixed(1)} Elo
              {trainer.trueNames.length > 0 && <> &middot; ({trainer.trueNames.join(", ")})</>}
            </p>
            <p className="record-line">
              {row.wins}W - {row.draws}D - {row.losses}L &nbsp; ({row.battles} battles)
            </p>
            <WldBar wldFractions={row.wldFractions} />
            {trainer.tribeBonuses.length > 0 && (
              <p className="card-line">
                <img className="inline-badge" src={assetUrl("badges/tribe.png")} alt="Tribal bonus" />
                {trainer.tribeBonuses.map((t) => t.name).join(", ")}
              </p>
            )}
            {opponentLine("Best win", row.bestWin, onOpenTrainer)}
            {opponentLine("Worst loss", row.worstLoss, onOpenTrainer)}
          </div>
        </div>
      </div>

      <div className="party-grid">
        {trainer.party.map((member, i) => (
          <div key={i} className="party-cell">
            <div className="cell-heading">
              <p className="cell-label">
                {member.speciesDisplay} Lv.{member.level}
              </p>
              {member.nickname && <p className="cell-nickname">{member.nickname}</p>}
            </div>
            <div className="cell-sprite-wrap" style={{ width: spriteBox, height: spriteBox }}>
              {member.shiny ? (
                <img
                  className="cell-sprite"
                  src={assetUrl(`pokemon_shiny/${member.species}.png`)}
                  alt={member.speciesDisplay}
                  style={{ transform: `scale(${pokemonSpriteScale})` }}
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <RemoteSprite
                  kind="Pokemon"
                  name={member.species}
                  className="cell-sprite"
                  alt={member.speciesDisplay}
                  style={{ transform: `scale(${pokemonSpriteScale})` }}
                />
              )}
              <div className="held-items">
                {member.heldItems.map((item, idx) => (
                  <RemoteSprite
                    key={idx}
                    kind="Items"
                    name={item.id}
                    className="held-item-icon"
                    alt={item.name}
                    title={item.name}
                    style={{ transform: `scale(${ITEM_ICON_SCALE})` }}
                  />
                ))}
              </div>
            </div>
            <div className={`move-grid move-grid-${meta.moveGridColumns}`}>
              {member.moves.map((move, idx) => (
                <MoveCapsule key={idx} move={move} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

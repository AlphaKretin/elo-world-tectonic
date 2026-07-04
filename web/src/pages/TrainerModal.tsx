import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toPng } from "html-to-image";
import { TrainerCard } from "../components/TrainerCard";
import { fetchLeaderboardRow, fetchMeta, fetchTrainerStatic, formatKey } from "../lib/dataClient";
import type { BattleType, CurseVariant, FormatMeta, LeaderboardRow, TrainerStatic } from "../types";
import "./TrainerModal.css";

export function TrainerModal() {
  const params = useParams();
  const navigate = useNavigate();
  const battleType = params.battleType as BattleType;
  const curseVariant = params.curseVariant as CurseVariant;
  const label = decodeURIComponent(params.label ?? "");
  const fmt = formatKey(battleType, curseVariant);

  const [trainer, setTrainer] = useState<TrainerStatic | null>(null);
  const [row, setRow] = useState<LeaderboardRow | null>(null);
  const [meta, setMeta] = useState<FormatMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  function close() {
    navigate(`/${battleType}/${curseVariant}`);
  }

  useEffect(() => {
    let cancelled = false;
    setTrainer(null);
    setRow(null);
    setError(null);
    Promise.all([fetchTrainerStatic(label), fetchLeaderboardRow(fmt, label), fetchMeta()])
      .then(([trainerData, rowData, metaData]) => {
        if (cancelled) return;
        if (!rowData) {
          setError(`No ${fmt} result for this trainer`);
          return;
        }
        setTrainer(trainerData);
        setRow(rowData);
        setMeta(metaData);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fmt, label]);

  // Lock background scroll while the modal is open, and let Escape close it
  // the same way clicking the backdrop does.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [battleType, curseVariant]);

  async function handleDownload() {
    if (!cardRef.current || !trainer) return;
    const dataUrl = await toPng(cardRef.current, { pixelRatio: 2 });
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = `${trainer.label.replaceAll(":", "_").replaceAll("#", "_v")}.png`;
    a.click();
  }

  function handleOpenTrainer(nextLabel: string) {
    navigate(`/${battleType}/${curseVariant}/${encodeURIComponent(nextLabel)}`);
  }

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {error && <p className="error">Failed to load trainer: {error}</p>}
        {!error && !trainer && <p className="modal-loading">Loading...</p>}
        {trainer && row && meta && (
          <>
            <TrainerCard trainer={trainer} row={row} meta={meta} onOpenTrainer={handleOpenTrainer} ref={cardRef} />
            <button type="button" className="download-button" onClick={handleDownload}>
              Download as PNG
            </button>
          </>
        )}
      </div>
    </div>
  );
}

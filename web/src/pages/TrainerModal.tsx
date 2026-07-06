import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toPng } from "html-to-image";
import { TrainerCard } from "../components/TrainerCard";
import { fetchLeaderboardRow, fetchMeta, fetchTrainerStatic, formatKey } from "../lib/dataClient";
import type { BattleType, CurseVariant, FilterVariant, FormatMeta, LeaderboardRow, TrainerStatic } from "../types";
import "./TrainerModal.css";

interface TrainerModalContentProps {
  battleType: BattleType;
  curseVariant: CurseVariant;
  filter: FilterVariant;
  label: string;
  onClose: () => void;
  onOpenTrainer: (label: string) => void;
}

// Presentational modal, driven entirely by props so it can be mounted either
// as a route (TrainerModal below, for the Leaderboard page) or directly from
// page-local state (see ComparePage) without navigating away and losing that
// page's filters/settings.
export function TrainerModalContent({ battleType, curseVariant, filter, label, onClose, onOpenTrainer }: TrainerModalContentProps) {
  const fmt = formatKey(battleType, curseVariant, filter);

  const [trainer, setTrainer] = useState<TrainerStatic | null>(null);
  const [row, setRow] = useState<LeaderboardRow | null>(null);
  const [meta, setMeta] = useState<FormatMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

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
      if (e.key === "Escape") onClose();
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

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {error && <p className="error">Failed to load trainer: {error}</p>}
        {!error && !trainer && <p className="modal-loading">Loading...</p>}
        {trainer && row && meta && (
          <>
            <button type="button" className="download-button" onClick={handleDownload}>
              Download as PNG
            </button>
            <TrainerCard trainer={trainer} row={row} meta={meta} onOpenTrainer={onOpenTrainer} ref={cardRef} />
          </>
        )}
      </div>
    </div>
  );
}

// Route-mounted wrapper for the Leaderboard page's nested /:label route --
// derives props from the URL and closes/navigates via the router.
export function TrainerModal() {
  const params = useParams();
  const navigate = useNavigate();
  const battleType = params.battleType as BattleType;
  const curseVariant = params.curseVariant as CurseVariant;
  const filter = params.filter as FilterVariant;
  const label = decodeURIComponent(params.label ?? "");

  function close() {
    navigate(`/${battleType}/${curseVariant}/${filter}`);
  }

  function openTrainer(nextLabel: string) {
    navigate(`/${battleType}/${curseVariant}/${filter}/${encodeURIComponent(nextLabel)}`);
  }

  return (
    <TrainerModalContent
      battleType={battleType}
      curseVariant={curseVariant}
      filter={filter}
      label={label}
      onClose={close}
      onOpenTrainer={openTrainer}
    />
  );
}

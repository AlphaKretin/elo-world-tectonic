import { useState } from "react";
import { remoteSpriteFallbackUrl, remoteSpriteUrl } from "../lib/dataClient";
import { computeOpaqueBbox, type SpriteBbox } from "../lib/spriteBbox";

interface Props {
  name: string;
  alt: string;
  boxSize: number;
  className?: string;
  style?: React.CSSProperties;
}

// Trainer portrait / masked-villain identity peek, trimmed to the sprite's
// opaque bounding box and fit-to-box (same as Python's trim_transparent +
// fit_image) instead of a plain <img> scaled to the raw, inconsistently-
// padded canvas. See RemoteSprite for the plain (uncropped) version used by
// Pokemon/item sprites, which don't have this padding problem.
export function CroppedTrainerSprite({ name, alt, boxSize, className, style }: Props) {
  const [tier, setTier] = useState<"sirv" | "github" | "hidden">("sirv");
  const [bbox, setBbox] = useState<SpriteBbox | null>(null);

  if (tier === "hidden") return null;
  const src = tier === "sirv" ? remoteSpriteUrl("Trainers", name) : remoteSpriteFallbackUrl("Trainers", name);

  function handleLoad(e: React.SyntheticEvent<HTMLImageElement>) {
    try {
      setBbox(computeOpaqueBbox(e.currentTarget));
    } catch {
      // Cross-origin canvas read blocked -- shouldn't happen (both hosts send
      // permissive CORS headers) but fail open rather than hiding the
      // portrait entirely.
    }
  }

  function handleError() {
    setTier((t) => (t === "sirv" ? "github" : "hidden"));
  }

  if (!bbox) {
    // Loaded invisibly to measure first, so nothing flashes the untrimmed
    // sprite before the crop is known.
    return (
      <img
        src={src}
        alt=""
        crossOrigin="anonymous"
        style={{ display: "none" }}
        onLoad={handleLoad}
        onError={handleError}
      />
    );
  }

  const scale = Math.min(boxSize / bbox.width, boxSize / bbox.height);
  const renderedW = bbox.width * scale;
  const renderedH = bbox.height * scale;

  return (
    <div className={className} style={{ ...style, width: renderedW, height: renderedH, overflow: "hidden" }}>
      <img
        src={src}
        alt={alt}
        crossOrigin="anonymous"
        onError={handleError}
        style={{
          position: "absolute",
          left: -bbox.left * scale,
          top: -bbox.top * scale,
          width: bbox.naturalWidth * scale,
          height: bbox.naturalHeight * scale,
          imageRendering: "pixelated",
        }}
      />
    </div>
  );
}

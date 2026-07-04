import { useState } from "react";
import { remoteSpriteFallbackUrl, remoteSpriteUrl } from "../lib/dataClient";

interface Props {
  kind: "Pokemon" | "Trainers" | "Items";
  name: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  title?: string;
}

// Two-tier fallback (Sirv CDN -> tectonic-tools' own GitHub-raw mirror ->
// hide) matching the fallback order tectonic-tools' own ImageFallback
// component uses -- see web/src/lib/dataClient.ts's remoteSpriteUrl docs
// for why hotlinking these is fine (Luna owns both hosts).
export function RemoteSprite({ kind, name, alt, className, style, title }: Props) {
  const [tier, setTier] = useState<"sirv" | "github" | "hidden">("sirv");
  if (tier === "hidden") return null;
  const src = tier === "sirv" ? remoteSpriteUrl(kind, name) : remoteSpriteFallbackUrl(kind, name);
  return (
    <img
      className={className}
      style={style}
      src={src}
      alt={alt}
      title={title}
      crossOrigin="anonymous"
      onError={() => setTier((t) => (t === "sirv" ? "github" : "hidden"))}
    />
  );
}

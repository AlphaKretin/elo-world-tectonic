export interface SpriteBbox {
  left: number;
  top: number;
  width: number;
  height: number;
  naturalWidth: number;
  naturalHeight: number;
}

// Trainer sprite canvases have inconsistent transparent padding (mirrors
// trainer_cards.py's own trim_transparent()/getbbox() -- see that function's
// docstring), so a raw <img> fit-to-box makes the visible figure read as
// small and off-center. Computed client-side via canvas alpha scanning
// rather than precomputed server-side, since it only runs once per opened
// card (one portrait + up to two identity peeks) and needs no export step.
export function computeOpaqueBbox(img: HTMLImageElement): SpriteBbox {
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return { left: 0, top: 0, width: w, height: h, naturalWidth: w, naturalHeight: h };
  ctx.drawImage(img, 0, 0);
  const { data } = ctx.getImageData(0, 0, w, h);

  let minX = w;
  let minY = h;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const alpha = data[(y * w + x) * 4 + 3];
      if (alpha > 8) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < 0) {
    return { left: 0, top: 0, width: w, height: h, naturalWidth: w, naturalHeight: h };
  }
  return { left: minX, top: minY, width: maxX - minX + 1, height: maxY - minY + 1, naturalWidth: w, naturalHeight: h };
}

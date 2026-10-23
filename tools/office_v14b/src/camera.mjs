/** Pure camera math; intentionally independent of PixiJS and the browser. */
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const positive = (v, fallback) => Number.isFinite(v) && v > 0 ? v : fallback;

/**
 * Fit every room on the virtual building plate. Zoom is relative to fit,
 * so screen resize or layout changes do not leave the building as a tiny strip.
 */
export function cameraForCampus(layout, viewportWidth, viewportHeight, zoom = 1, department = '') {
  const w = positive(viewportWidth, 1);
  const h = positive(viewportHeight, 1);
  const worldW = positive(layout?.width, 1);
  const worldH = positive(layout?.height, 1);
  const desiredZoom = clamp(positive(zoom, 1), 0.5, 3);
  const fit = Math.min(0.92 * w / worldW, 0.90 * h / worldH);
  const scale = clamp(fit * desiredZoom, 0.025, 2.5);
  const focusRoom = department && layout?.rooms?.find(r => r.code === department);
  const cx = focusRoom ? focusRoom.x + focusRoom.width / 2 : worldW / 2;
  const cy = focusRoom ? focusRoom.y + focusRoom.height / 2 : worldH / 2;
  return {
    x: w / 2 - cx * scale,
    y: h / 2 - cy * scale,
    scale,
    fittedWidth: worldW * scale,
    fittedHeight: worldH * scale,
  };
}

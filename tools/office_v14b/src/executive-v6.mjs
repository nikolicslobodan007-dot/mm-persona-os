/** PR-B6 — Layered illustration pilot. Pure, read-only and deterministic.
 * Runtime images must be declared by Django {% static %}; no CDN or arbitrary URLs.
 * Avatars remain linked to actual Django department membership through B5.
 */
import {isExecutivePilotRoom, premiumAvatarKey} from './executive-pilot.mjs';

export const B6_ASSETS = Object.freeze([
  'executive-overview-v6', 'executive-detail-v6', 'executive-foreground-v6',
  'ivana-v6', 'tamas-v6',
]);
const ALLOWED = new Set(B6_ASSETS);

export function safeB6AssetURL(key, supplied, currentOrigin) {
  if (!ALLOWED.has(key) || typeof supplied !== 'string' || !supplied) return null;
  try {
    const base = new URL(currentOrigin);
    const url = new URL(supplied, base.href);
    if (!['http:', 'https:'].includes(base.protocol) || url.origin !== base.origin ||
      url.username || url.password || url.search || url.hash) return null;
    // ManifestStaticFilesStorage may insert a hexadecimal digest before .png.
    const filename = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`^/static/console/office-premium-b6/${filename}(?:\\.[0-9a-f]{8,})?\\.png$`, 'i');
    return pattern.test(url.pathname) ? url.href : null;
  } catch { return null; }
}

export async function loadB6Textures(loader, entries, currentOrigin) {
  const result = new Map();
  if (typeof loader !== 'function' || !Array.isArray(entries)) return result;
  const allowed = new Map();
  for (const entry of entries) {
    if (!entry || allowed.has(entry.key)) continue;
    const url = safeB6AssetURL(entry.key, entry.url, currentOrigin);
    if (url) allowed.set(entry.key, url);
  }
  const requests = [...allowed];
  const finished = await Promise.allSettled(requests.map(([,url]) => loader(url)));
  finished.forEach((response,i) => {
    if (response.status === 'fulfilled' && response.value) result.set(requests[i][0], response.value);
  });
  return result;
}

export function b6RoomAsset(room, focusDepartment='') {
  if (!isExecutivePilotRoom(room)) return null;
  return focusDepartment === room.code ? 'executive-detail-v6' : 'executive-overview-v6';
}

export function b6RoomReady(room, textures, focusDepartment='') {
  const key=b6RoomAsset(room,focusDepartment);
  return Boolean(key && textures instanceof Map && textures.has(key));
}

/** No numeric-ID guesses, no status or runtime-based character selection. */
export function b6AvatarKey(agent,room) {
  const b5=premiumAvatarKey(agent,room);
  return b5 === 'ivana-avatar' ? 'ivana-v6' : b5 === 'tamas-avatar' ? 'tamas-v6' : null;
}

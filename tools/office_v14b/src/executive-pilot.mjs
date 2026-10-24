/** PR-B5 Executive Office: allowlisted, read-only premium graphics.
 * Identity is resolved ONLY from the live, filtered V1.2 Agent register.
 * This module makes no guesses about numeric public_id values or dossier traits.
 */
export const B5_ASSETS = Object.freeze([
  'executive-room-overview',
  'executive-room-detail',
  'executive-room-furniture',
  'executive-room-foreground',
  'executive-room-light',
  'ivana-avatar',
  'tamas-avatar',
]);
const allowed = new Set(B5_ASSETS);
const PILOT_NAMES = Object.freeze({
  'ivana đurić': 'ivana-avatar',
  'tamás kovács': 'tamas-avatar',
});
const norm = x => String(x ?? '').normalize('NFC').trim().replace(/\s+/g,' ').toLocaleLowerCase('sr');
/** Require an actual Django department named Uprava. No synthetic department. */
export function isExecutivePilotRoom(room) {
  if (!room || room.theme !== 'executive') return false;
  return norm(room.name) === 'uprava' || norm(room.code) === 'uprava';
}
/** Only agents whose actual Assignment places them in the room may be premium. */
export function premiumAvatarKey(agent, room) {
  if (!isExecutivePilotRoom(room) || !agent || !Array.isArray(room.people)) return null;
  if (typeof agent.public_id !== 'string' || !/^P-\d{5,20}$/.test(agent.public_id)) return null;
  if (!room.people.some(p => p.public_id === agent.public_id)) return null;
  return PILOT_NAMES[norm(agent.display_name).replace(/\s*\(ai\)$/u,'')] || null;
}
export function executiveViewAsset(room, focusDepartment) {
  return isExecutivePilotRoom(room) && focusDepartment === room.code
    ? 'executive-room-detail' : 'executive-room-overview';
}
/** Reject CDN URLs, credentials, query strings, fragments and other asset classes. */
export function safeB5AssetURL(key, supplied, currentOrigin) {
  if (!allowed.has(key) || typeof supplied !== 'string' || !supplied) return null;
  try {
    const origin = new URL(currentOrigin);
    const url = new URL(supplied, origin);
    if (!['http:','https:'].includes(origin.protocol) || url.origin !== origin.origin || url.username || url.password || url.search || url.hash) return null;
    if (!new RegExp(`^/static/console/office-premium-b5/${key}(?:\\.[a-f0-9]{8,})?\\.png$`, 'i').test(url.pathname)) return null;
    return url.href;
  } catch { return null; }
}
/** Async loading is partial: a missing asset never prevents normal Office operation. */
export async function loadB5Textures(loader, entries, currentOrigin) {
  const out = new Map();
  if (typeof loader !== 'function' || !Array.isArray(entries)) return out;
  const validated = new Map();
  for (const entry of entries) {
    if (!entry || validated.has(entry.key)) continue;
    const safe = safeB5AssetURL(entry.key, entry.url, currentOrigin);
    if (safe) validated.set(entry.key, safe);
  }
  const requests = [...validated];
  const results = await Promise.allSettled(requests.map(([,url]) => loader(url)));
  results.forEach((r,i) => { if (r.status === 'fulfilled' && r.value) out.set(requests[i][0],r.value); });
  return out;
}
/** No room image => existing PR-B4 visual layer, not partly broken B5 art. */
export function b5RoomReady(room, textures, focusDepartment) {
  if (!isExecutivePilotRoom(room) || !(textures instanceof Map)) return false;
  return textures.has(executiveViewAsset(room, focusDepartment));
}

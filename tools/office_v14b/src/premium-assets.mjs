/** V1.4B.4 / PR-B4: premium empty-office backgrounds.
 * Asset URLs are resolved by Django's {% static %} in HTML, so hashed ManifestStorage
 * paths work. No external URLs, API calls, identities, plans or model mutations.
 */
export const ROOM_PREMIUM_THEMES = Object.freeze([
  'executive','creative','finance','procurement','research','support',
  'quality','logistics','sales','technology','general',
]);
const ALLOWED = new Set(ROOM_PREMIUM_THEMES);
export function roomAssetFile(theme) {
  return ALLOWED.has(theme) ? `room-${theme}.png` : 'room-general.png';
}
/** Accept only a matching same-origin asset, optionally fingerprinted by Django. */
export function safePremiumAssetURL(theme, suppliedURL, currentOrigin) {
  if (!ALLOWED.has(theme) || typeof suppliedURL !== 'string' || !suppliedURL) return null;
  try {
    const origin = new URL(currentOrigin);
    const url = new URL(suppliedURL, origin.href);
    const safeName = roomAssetFile(theme).replace('.png','');
    const expected = new RegExp(`/console/office-premium/${safeName}(?:\\.[0-9a-f]{8,})?\\.png$`, 'i');
    if (url.origin !== origin.origin || !expected.test(url.pathname)) return null;
    return url.href;
  } catch { return null; }
}
/** Return Map(theme, PIXI.Texture), ignoring failed files and unsafe URLs. */
export async function loadPremiumRoomAssets(loader, entries, currentOrigin) {
  const loaded = new Map();
  if (typeof loader !== 'function' || !Array.isArray(entries)) return loaded;
  const byTheme = new Map();
  for (const {theme, url} of entries) {
    if (!ALLOWED.has(theme) || byTheme.has(theme)) continue;
    const safe = safePremiumAssetURL(theme,url,currentOrigin);
    if (safe) byTheme.set(theme,safe);
  }
  const items = [...byTheme];
  const results = await Promise.allSettled(items.map(([,url])=>loader(url)));
  results.forEach((result,i)=>{
    if (result.status === 'fulfilled' && result.value) loaded.set(items[i][0],result.value);
  });
  return loaded;
}

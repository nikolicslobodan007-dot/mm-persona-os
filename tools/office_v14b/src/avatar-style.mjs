/** V1.4B.2 — provisional, deterministic visual style. No portraits or dossier attributes. */
const JACKETS = Object.freeze([
  0x376786, 0x73566f, 0x376e68, 0x7c6853, 0x525f95, 0x89535a,
  0x50748a, 0x725f88, 0x637147, 0x556b7a, 0x86694d,
]);
const HAIR = Object.freeze([0x292b33, 0x564237, 0x8a6250, 0x423d4a, 0x755e4a, 0x353c4a]);
const SKIN = Object.freeze([0xf1caa8, 0xd9a988, 0xe4bc9c, 0xc99277]);
const ACCENTS = Object.freeze([0x70d8c7, 0xf2c57a, 0x87a9ef, 0xeaa9a9]);
const PUBLIC_ID = /^P-(\d{5,20})$/;
/** Public ID is the ONLY identity input. These are stylized placeholders, NOT portrait likenesses. */
export function avatarStyleFor(publicId) {
  const match = typeof publicId === 'string' && PUBLIC_ID.exec(publicId);
  if (!match) return null;
  const n = Number(BigInt(match[1]) % 100000n);
  return {
    jacket: JACKETS[n % JACKETS.length],
    hair: HAIR[Math.floor(n / JACKETS.length) % HAIR.length],
    skin: SKIN[Math.floor(n / 3) % SKIN.length],
    accent: ACCENTS[n % ACCENTS.length],
    hairShape: Math.floor(n / 2) % 5,
    outfit: n % 3,
    glasses: n % 7 === 0,
    pin: n % 4 === 0,
  };
}
/** Reversible LOD: name labels are hidden only in the distant map, never identity or hit targets. */
export function shouldShowNameAtScale(scale, focused = false, selected = false) {
  return Boolean(focused || selected || (Number.isFinite(scale) && scale >= 0.68));
}

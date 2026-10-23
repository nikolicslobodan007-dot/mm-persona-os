/** Virtual Office V1.4B.3 / PR-B3 — room design tokens.
 * Decorative metadata only. Not agent state, work progress or private dossiers.
 * All colours are integer RGB values, resolved from a bounded fixed palette.
 */
const THEMES = Object.freeze({
  executive: Object.freeze({floor:0x483a30, grain:0x8a6850, wall:0x8a735c, wallDeep:0x342d2d, accent:0xe2b578, glow:0xffcb87, sofa:0xa98461, furniture:0x845a3e, feature:'library', surface:'wood'}),
  creative: Object.freeze({floor:0x293d42, grain:0x59706d, wall:0x527779, wallDeep:0x263944, accent:0x65d6c4, glow:0xffc68b, sofa:0x507e85, furniture:0x966e53, feature:'moodboard', surface:'wood'}),
  finance: Object.freeze({floor:0x324452, grain:0x718498, wall:0x607b8c, wallDeep:0x263748, accent:0x91c5f1, glow:0xffca8c, sofa:0x73869b, furniture:0x756152, feature:'charts', surface:'tile'}),
  procurement: Object.freeze({floor:0x403b35, grain:0x8f795f, wall:0x95836a, wallDeep:0x39362e, accent:0xe8c48d, glow:0xffb76a, sofa:0x877260, furniture:0x8b6445, feature:'samples', surface:'wood'}),
  research: Object.freeze({floor:0x303d4e, grain:0x75879a, wall:0x637f96, wallDeep:0x2c3b51, accent:0xb9b1f2, glow:0xf4c3a0, sofa:0x6d729c, furniture:0x76675f, feature:'research', surface:'tile'}),
  support: Object.freeze({floor:0x2c4748, grain:0x6a9990, wall:0x5a8b87, wallDeep:0x263f44, accent:0x7ee5b6, glow:0xffd09e, sofa:0x588d86, furniture:0x776b5c, feature:'support', surface:'wood'}),
  quality: Object.freeze({floor:0x303c49, grain:0x667b8e, wall:0x6d8595, wallDeep:0x2c3744, accent:0xc1d4f4, glow:0xfbd4a6, sofa:0x747f8c, furniture:0x796759, feature:'checklist', surface:'tile'}),
  logistics: Object.freeze({floor:0x3b3b3b, grain:0x7b817d, wall:0x808b85, wallDeep:0x313a39, accent:0xe0c18c, glow:0xffc888, sofa:0x788178, furniture:0x8c7354, feature:'logistics', surface:'tile'}),
  sales: Object.freeze({floor:0x344254, grain:0x667f96, wall:0x66839c, wallDeep:0x2a3748, accent:0x8acbf1, glow:0xffd39b, sofa:0x6788a2, furniture:0x7c6458, feature:'sales', surface:'wood'}),
  technology: Object.freeze({floor:0x293b49, grain:0x63839a, wall:0x617f9b, wallDeep:0x253548, accent:0x69d5e2, glow:0x9fe5ff, sofa:0x657b9a, furniture:0x5e666a, feature:'servers', surface:'tile'}),
  general: Object.freeze({floor:0x374353, grain:0x77869b, wall:0x617a8c, wallDeep:0x2a3a4c, accent:0x87bedf, glow:0xffce96, sofa:0x72869c, furniture:0x796956, feature:'noticeboard', surface:'wood'}),
});

export const ROOM_THEME_NAMES = Object.freeze(Object.keys(THEMES));
export function roomMaterial(kind) { return THEMES[kind] || THEMES.general; }

/** Only a public, stable department code participates in decor variants. */
export function roomVariant(code) {
  const value=String(code ?? '').slice(0,32);
  let hash=2166136261;
  for(let i=0;i<value.length;i++){hash=Math.imul(hash ^ value.charCodeAt(i),16777619)>>>0;}
  return {plantOffset:hash % 3, lampOffset:(hash >>> 4) % 3, shelfOffset:(hash >>> 7) % 4};
}

export function roomVisualSpec(room) {
  return {
    theme: roomMaterial(room?.theme),
    feature: roomMaterial(room?.theme).feature,
    variant: roomVariant(room?.code),
    width: Number.isFinite(room?.width) ? room.width : 530,
    height: Number.isFinite(room?.height) ? room.height : 344,
  };
}

/** PR-B7 — view policy, pure geometry; no agent data, status, DOM or Pixi dependency. */
const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));
/** Target readable department labels at different camera scales.
 * Never overflow into the AI count at the right side of the room header.
 */
export function departmentLabelScale(rawWidth, roomWidth, cameraScale, focused=false) {
  const rw=Number.isFinite(rawWidth)&&rawWidth>0?rawWidth:1;
  const width=Number.isFinite(roomWidth)&&roomWidth>0?roomWidth:530;
  const scale=Number.isFinite(cameraScale)&&cameraScale>0?cameraScale:1;
  const target=focused?15:13;
  const desired=clamp(target/(17*scale),0.52,4);
  const fitted=(width-140)/rw;
  return Math.max(0.25, Math.min(desired, Math.max(0.25,fitted)));
}
/** Zoomed-in display shows agent names; distant overview relies on inspector/list. */
export function roomHitArea(room) {
  if (!room || !Number.isFinite(room.width) || !Number.isFinite(room.height) ||
      room.width <= 0 || room.height <= 0) return null;
  return {x:room.x+3,y:room.y+40,width:Math.max(1,room.width-6),
    height:Math.max(1,room.height-44)};
}

/** Web Korporacija V1.4B / PR-B1.
 * Progressive enhancement: pure frontend; no new Django API or model writes.
 * Bundled *locally* using esbuild with pinned pixi.js. No CDN/inline scripts.
 */
import 'pixi.js/unsafe-eval';  // CSP: non-eval sync (script-src 'self', bez unsafe-eval)
import {Application, Container, Graphics, Text, TextStyle} from 'pixi.js';
import {layoutCampus} from './layout.mjs';

const ROOT_ID = 'officeScene';
const HOST_ID = 'officeSceneHost';
const PALETTE = {
  executive:{floor:0x3d3938,walls:0x90734b,accent:0xe4b36e,desk:0x98714e},
  creative:{floor:0x293948,walls:0x456a7e,accent:0x62d0cd,desk:0x936d51},
  finance:{floor:0x263949,walls:0x446780,accent:0x88b9f1,desk:0x7b655b},
  procurement:{floor:0x413b32,walls:0x947a57,accent:0xeab985,desk:0x936b42},
  research:{floor:0x303b44,walls:0x687c88,accent:0xb9a0e6,desk:0x736456},
  support:{floor:0x263d3d,walls:0x58827d,accent:0x7ce0b9,desk:0x776653},
  quality:{floor:0x303949,walls:0x6a7690,accent:0xb7c9f1,desk:0x675c63},
  general:{floor:0x303a4a,walls:0x60748a,accent:0x75b7dd,desk:0x776355},
};
const FONT = 'Arial, sans-serif';
const clamp = (v,a,b)=>Math.min(b,Math.max(a,v));
const gRect=(x,y,w,h,color,r=0,alpha=1)=>{
  const g=new Graphics();
  if(r)g.roundRect(x,y,w,h,r);else g.rect(x,y,w,h);
  g.fill({color,alpha});return g;
};
const gLine=(a,b,c,d,color,width=2,alpha=1)=>new Graphics().moveTo(a,b).lineTo(c,d).stroke({color,width,alpha});
const gCircle=(x,y,r,color,alpha=1)=>new Graphics().circle(x,y,r).fill({color,alpha});
function addText(parent,value,x,y,size=14,color=0xeaf2ff,weight='normal',anchorX=0){
  const t=new Text({text:String(value),style:new TextStyle({fontFamily:FONT,fontSize:size,fill:color,fontWeight:weight})});
  t.x=x;t.y=y;t.anchor.set(anchorX,0.5);parent.addChild(t);return t;
}
function furnishing(parent,room,theme){
  const {x,y,width:w,height:h}=room;
  // Lower-left sofa, department-specific furniture and plants. These do not imply work.
  const group = new Container();parent.addChild(group);
  group.addChild(gRect(x+18,y+h-83,120,25,theme.desk,9));
  group.addChild(gRect(x+24,y+h-100,110,22,0x4d6079,9));
  group.addChild(gRect(x+29,y+h-57,90,13,0x172437,4));
  group.addChild(gRect(x+w-116,y+h-93,96,13,0x202b36,3));
  for(const dx of [36,w-39]){
    const px=x+dx,py=y+h-29;
    group.addChild(gCircle(px,py+3,17,0x101c28,.45));
    group.addChild(gRect(px-9,py-7,18,15,0x97785c,3));
    for(const shift of [-9,0,9]) group.addChild(gCircle(px+shift,py-17-(shift===0?6:0),12,0x34796b));
  }
  if(room.theme==='creative'){
    group.addChild(gRect(x+w-145,y+58,106,77,0x1c2b39,3));
    group.addChild(gRect(x+w-137,y+67,90,60,0x395b78,2));
    group.addChild(gRect(x+w-121,y+84,48,3,0xf6c37f,1));
    group.addChild(gRect(x+w-121,y+96,58,3,0x62d0cd,1));
  }else if(room.theme==='finance'){
    group.addChild(gRect(x+w-150,y+53,118,91,0x203141,3));
    for(let k=0;k<4;k++)group.addChild(gLine(x+w-140,y+71+k*16,x+w-54,y+71+k*16,0x60859d,2));
  }else if(room.theme==='executive'){
    group.addChild(gRect(x+w-154,y+60,116,69,0x8b6a45,9));
    group.addChild(gRect(x+w-143,y+68,94,52,0xa78a5c,5));
  }else if(room.theme==='procurement'){
    for(let k=0;k<3;k++){group.addChild(gRect(x+w-141+k*29,y+69,25,37,0x907857,3));group.addChild(gRect(x+w-137+k*29,y+73,17,3,0xcdb68b,1));}
  }else{
    group.addChild(gRect(x+w-133,y+55,96,61,0x213c53,4));
    group.addChild(gRect(x+w-122,y+68,74,38,0x50748a,2));
  }
}
function drawRoom(parent,room,running,selected,onAgent,onDepartment){
  const theme=PALETTE[room.theme]||PALETTE.general;
  const {x,y,width:w,height:h}=room;
  const item=new Container();parent.addChild(item);
  item.addChild(gRect(x+13,y+13,w,h,0x000813,22,.42));
  item.addChild(gRect(x,y,w,h,theme.floor,13));
  // Quiet top-down flooring, wall parapet, windows; no fake motion.
  for(let px=x+28;px<x+w;px+=38)item.addChild(gLine(px,y+53,px,y+h-12,0xa6bac1,1,.055));
  for(let py=y+56;py<y+h;py+=38)item.addChild(gLine(x+14,py,x+w-14,py,0xa6bac1,1,.055));
  item.addChild(gRect(x,y,w,39,0x0f2134,7));
  item.addChild(gRect(x,y+39,w,9,theme.walls,1));
  item.addChild(gRect(x,y+38,15,h-38,0x23394a,2));
  item.addChild(gRect(x+w-15,y+38,15,h-38,0x23394a,2));
  item.addChild(gRect(x,y+h-12,w,12,0x172837,2));
  item.addChild(gRect(x+180,y+40,140,7,0xddce9d,2,.65));
  item.addChild(gRect(x+w-89,y+22,51,43,0x27425a,3));
  item.addChild(gRect(x+w-83,y+28,39,30,0x9dc4d8,2,.75));
  item.addChild(gRect(x+w-73,y+31,3,24,0x26475d,0));
  // Decorative corridor entrance at front center.
  item.addChild(gRect(x+w/2-42,y+h-13,84,14,0x648799,2));
  const title=room.name.length>34?room.name.slice(0,31)+'…':room.name;
  addText(item,title,x+22,y+22,17,0xf3fbff,'bold');
  addText(item,`${room.people.length} AI`,x+w-117,y+22,12,theme.accent,'bold');
  furnishing(item,room,theme);
  for(const agent of room.people) drawAgent(item,agent,theme,selected===agent.public_id,running.has(agent.public_id),onAgent);
  // Clickable room label / tile header, separate from agents.
  const hotspot=gRect(x+2,y+2,w-4,37,0xffffff,4,.001);hotspot.eventMode='static';hotspot.cursor='pointer';
  hotspot.on('pointertap',()=>onDepartment(room.code));item.addChild(hotspot);
}
function initials(name){const s=String(name||'?').split(' ').filter(Boolean);return s.length>1?(s[0][0]+s[1][0]).toUpperCase():s[0][0].toUpperCase();}
function drawAgent(parent,a,theme,selected,isRunning,onAgent){
  const {x,y}=a;
  const c=new Container();parent.addChild(c);
  if(selected){c.addChild(gCircle(x,y+6,52,0x73dded,.14));c.addChild(new Graphics().circle(x,y+6,53).stroke({color:0x87f0e1,width:2.5,alpha:.94}));}
  c.addChild(gCircle(x,y+26,36,0x091827,.46));
  // Desk + monitor, before body. Neither shows activity without RUNNING.
  c.addChild(gRect(x-40,y-38,80,21,theme.desk,5));
  c.addChild(gRect(x-17,y-66,34,29,0x101f2e,3));
  c.addChild(gRect(x-13,y-62,26,20,isRunning?0x55d7c4:0x537e96,2));
  c.addChild(gRect(x-3,y-38,6,10,0x23303a,1));
  // Shaded figurine body, legs and head; no use of private dossier or photo bytes.
  c.addChild(gRect(x-18,y+14,13,26,0x17283c,5));c.addChild(gRect(x+5,y+14,13,26,0x17283c,5));
  c.addChild(gRect(x-29,y-2,58,36,0x304b75,15));
  c.addChild(gRect(x-20,y-10,40,47,0x5079a5,15));
  c.addChild(gRect(x-23,y-10,46,10,theme.accent,6,.47));
  c.addChild(gCircle(x,y-28,23,0x1f293b));
  c.addChild(gCircle(x,y-30,20,0xe9b995));
  c.addChild(new Graphics().arc(x,y-36,19,3.2,6.15).stroke({color:0x3f2c29,width:7}));
  // Initials establish identity without copying private reference portraits to static files.
  addText(c,initials(a.display_name),x,y-30,12,0x1c293b,'bold',.5);
  const badge=gRect(x-66,y+51,132,25,0x0a192e,8,.9);c.addChild(badge);
  const name=a.display_name.length>17?a.display_name.slice(0,15)+'…':a.display_name;
  addText(c,name,x,y+63,12,0xf1f6ff,'bold',.5);
  if(isRunning){c.addChild(gCircle(x+31,y-60,8,0x5fe9ac));addText(c,'RUNNING',x+41,y-60,10,0x6df5b3,'bold');}
  const hit=gRect(x-65,y-77,130,157,0xffffff,8,.001);hit.eventMode='static';hit.cursor='pointer';
  hit.on('pointertap',(event)=>{event.stopPropagation();onAgent(a.public_id);});c.addChild(hit);
}
function backdrop(world,layout){
  world.addChild(gRect(0,0,layout.width,layout.height,0x0b1a29));
  for(let i=0;i<layout.width;i+=46)world.addChild(gLine(i,0,i,layout.height,0x8ca5b9,1,.045));
  for(let i=0;i<layout.height;i+=46)world.addChild(gLine(0,i,layout.width,i,0x8ca5b9,1,.045));
  // Shared hallways: all rooms sit on one building plate (not separate independent cards).
  for(let row=0;row<layout.rooms.length;row+=2){
    const room=layout.rooms[row], y=room.y+room.height+11;
    world.addChild(gRect(28,y,layout.width-56,50,0x3d5265,9,.8));
    for(let xx=44;xx<layout.width-45;xx+=82)world.addChild(gLine(xx,y+42,xx+28,y+42,0x9fb8ca,2,.24));
  }
}
function fitCamera(camera,app,layout,zoom,roomFocus){
  const viewportW=app.screen.width, viewportH=app.screen.height;
  const scale=clamp(Math.min(viewportW/layout.width,viewportH/layout.height)*zoom,.22,2.1);
  camera.scale.set(scale);
  const focus=roomFocus ? layout.rooms.find(r=>r.code===roomFocus) : null;
  const cx=focus?focus.x+focus.width/2:layout.width/2;
  const cy=focus?focus.y+focus.height/2:layout.height/2;
  camera.x=viewportW/2-cx*scale;
  camera.y=viewportH/2-cy*scale;
}

(async()=>{
  const root=document.getElementById(ROOT_ID),host=document.getElementById(HOST_ID),fallback=document.getElementById('departments');
  if(!root||!host||!fallback)return;
  let app=null;
  try{
    app=new Application();
    await app.init({resizeTo:host,backgroundColor:0x091625,antialias:true,autoDensity:true,
      resolution:Math.min(window.devicePixelRatio||1,2),preference:'webgl',autoStart:false});
    app.canvas.setAttribute('aria-label','Grafička mapa kancelarija Web Korporacije');
    app.canvas.setAttribute('role','img');
    host.appendChild(app.canvas);
  }catch(e){console.warn('Office scene unavailable; accessible DOM view stays active.',e);root.hidden=true;return;}
  const camera=new Container();app.stage.addChild(camera);
  let data=null,graphMode=true,currentLayout=null;
  let drag=null;
  const toggle=document.createElement('button');toggle.type='button';toggle.className='wk-button secondary';
  toggle.textContent='Lista prostorija';toggle.setAttribute('aria-pressed','true');
  const tools=document.querySelector('.wk-canvas-tools');if(tools)tools.appendChild(toggle);
  function updateMode(){root.hidden=!graphMode;fallback.hidden=graphMode;toggle.textContent=graphMode?'Lista prostorija':'Grafički prikaz';toggle.setAttribute('aria-pressed',String(graphMode));}
  toggle.addEventListener('click',()=>{graphMode=!graphMode;updateMode();});
  // Camera controls only; no agent activity is ever inferred from movement.
  app.canvas.addEventListener('wheel',e=>{
    if(!graphMode)return;
    e.preventDefault();
    const r=app.canvas.getBoundingClientRect();
    const px=(e.clientX-r.left)*app.screen.width/r.width;
    const py=(e.clientY-r.top)*app.screen.height/r.height;
    const beforeX=(px-camera.x)/camera.scale.x;
    const beforeY=(py-camera.y)/camera.scale.y;
    const next=clamp(camera.scale.x*(e.deltaY<0?1.12:.89),.18,2.6);
    camera.scale.set(next);camera.x=px-beforeX*next;camera.y=py-beforeY*next;
    app.render();
  },{passive:false});
  app.canvas.addEventListener('pointerdown',e=>{
    if(!graphMode||!(e.shiftKey||e.button===1||e.pointerType==='touch'))return;
    drag={x:e.clientX,y:e.clientY,cx:camera.x,cy:camera.y};
    app.canvas.setPointerCapture(e.pointerId);
  });
  app.canvas.addEventListener('pointermove',e=>{
    if(!drag)return;
    const r=app.canvas.getBoundingClientRect();
    camera.x=drag.cx+(e.clientX-drag.x)*app.screen.width/r.width;
    camera.y=drag.cy+(e.clientY-drag.y)*app.screen.height/r.height;
    app.render();
  });
  for(const name of ['pointerup','pointercancel'])app.canvas.addEventListener(name,()=>{drag=null;});
  function onAgent(public_id){window.dispatchEvent(new CustomEvent('wk:scene-agent-select',{detail:{public_id}}));}
  function onDepartment(code){window.dispatchEvent(new CustomEvent('wk:scene-department-focus',{detail:{code}}));}
  function render(){
    if(!data)return;
    const layout=layoutCampus(data.agents,data.focusDepartment);
    currentLayout=layout;camera.removeChildren().forEach(x=>x.destroy({children:true}));
    const world=new Container();camera.addChild(world);backdrop(world,layout);
    const running=new Set(data.confirmedRunning||[]);
    for(const room of layout.rooms)drawRoom(world,room,running,data.selected,onAgent,onDepartment);
    fitCamera(camera,app,layout,[.85,1,1.15][data.zoom]??1,data.focusDepartment);app.render();
  }
  window.addEventListener('wk:campus-state',e=>{data=e.detail;render();});
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{if(currentLayout){app.resize();render();}}).observe(host);
  updateMode();window.dispatchEvent(new Event('wk:scene-request'));
  window.addEventListener('pagehide',()=>{try{app?.destroy(true,{children:true});}catch(_e){/* already gone */}}, {once:true});
})();

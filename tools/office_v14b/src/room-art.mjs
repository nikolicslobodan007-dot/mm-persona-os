/** V1.4B.3 / PR-B3 — locally bundled, procedural soft-2.5D room artwork.
 * No remote textures, image requests, shaders, animations or unsafe-eval.
 * Rooms are illustrations, never evidence that an agent is working.
 */
import {Container,Graphics} from 'pixi.js';
import {roomVisualSpec} from './room-style.mjs';

// Consolidated layered Graphics to reduce the display-list footprint.
const box=(g,x,y,w,h,c,r=0,a=1)=>{if(r)g.roundRect(x,y,w,h,r);else g.rect(x,y,w,h);g.fill({color:c,alpha:a});};
const circle=(g,x,y,r,c,a=1)=>{g.circle(x,y,r).fill({color:c,alpha:a});};
const line=(g,x,y,x2,y2,c,width=1,a=1)=>{g.moveTo(x,y).lineTo(x2,y2).stroke({color:c,width,alpha:a});};

function plant(g,x,y,tall=false){
  box(g,x-13,y-4,26,15,0x132435,5,.38);
  box(g,x-9,y-15,18,18,0xc39163,4);
  line(g,x,y-14,x,y-(tall?45:33),0x457f60,2.5);
  for(const [ox,oy,r] of [[-13,-29,11],[11,-31,12],[-3,-40,13],[3,-26,10]])
    circle(g,x+ox,y+oy-(tall?11:0),r,0x397b5e,.98);
  circle(g,x-6,y-45-(tall?11:0),5,0x63ac78,.75);
}
function lamp(g,x,y,c){
  // Warm glow drawn as transparent concentric rings, no filters or animation.
  circle(g,x,y,65,c,.028);circle(g,x,y,43,c,.05);circle(g,x,y,22,c,.10);
  box(g,x-15,y-6,30,12,0xd8bd89,6);box(g,x-9,y-3,18,6,0xffe6b0,3);
}
function backWall(g,r,m){
  const {x,y,width:w,height:h}=r;
  box(g,x+15,y+14,w-30,68,m.wallDeep,3);
  box(g,x+17,y+18,w-34,51,m.wall,2);
  box(g,x+17,y+64,w-34,12,0x1c2935,2,.65);
  box(g,x+15,y+70,w-30,9,0x0f1d2b,1,.5);
  box(g,x,y+36,18,h-37,0x192d3d,2);
  box(g,x+9,y+46,10,h-63,m.wall,2,.7);
  box(g,x+w-18,y+36,18,h-37,0x192d3d,2);
  box(g,x+w-14,y+46,7,h-62,m.wall,2,.7);
  box(g,x,y+h-14,w,14,0x132637,2);
  // Cutaway edge separates the virtual room from its corridor.
  box(g,x+w/2-48,y+h-15,96,16,0x405a68,2);
  box(g,x+w/2-39,y+h-10,78,5,0x86a8b2,1,.7);
  for(let i=0;i<2;i++){
    const cx=x+42+i*(w-94);
    box(g,cx,y+25,28,91,0x253745,4,.65);
    box(g,cx+8,y+32,10,76,0x9c866e,2,.75);
  }
  // Blue daylight from window on right wall, subtle artificial falloff.
  box(g,x+w-137,y+24,77,49,0x15283b,3);
  box(g,x+w-132,y+29,67,39,0x80aabd,2);
  box(g,x+w-132,y+29,67,17,0xb4d6e2,1,.53);
  line(g,x+w-98,y+29,x+w-98,y+68,0x3c6176,3);
  box(g,x+w-142,y+73,87,7,0x4a5862,1);
}
function floor(g,r,m){
  const {x,y,width:w,height:h}=r;
  box(g,x+13,y+14,w,h,0x010a13,16,.42);
  box(g,x,y,w,h,m.floor,12);
  box(g,x+13,y+77,w-26,h-93,0x0d1a28,2,.08);
  if(m.surface==='wood'){
    const plankStep=Math.max(31,Math.ceil((h-80)/32));
    for(let row=0;row<Math.ceil((h-80)/plankStep);row++){
      const yy=y+83+row*plankStep;
      line(g,x+21,yy,x+w-22,yy,m.grain,1,.30);
      for(let col=0;col<7;col++){
        const offset=((row%2)*31);
        const xx=x+28+col*72+offset;
        if(xx<x+w-25)line(g,xx,yy,xx,Math.min(yy+plankStep,y+h-17),m.grain,1,.15);
      }
    }
  }else{
    for(let xx=x+25;xx<x+w-25;xx+=52)line(g,xx,y+81,xx,y+h-18,m.grain,1,.19);
    for(let yy=y+85;yy<y+h-13;yy+=Math.max(52,Math.ceil(h/30)))line(g,x+19,yy,x+w-19,yy,m.grain,1,.19);
  }
  // Wool rug + outer shadow, quiet visual zone behind the first two seats.
  box(g,x+158,y+112,212,Math.min(123,h-154),0x070e18,16,.18);
  box(g,x+163,y+108,200,Math.min(117,h-154),m.sofa,14,.13);
  box(g,x+172,y+116,182,Math.min(101,h-168),m.accent,11,.06);
}
function desk(g,x,y,m){
  box(g,x-4,y+11,101,29,0x0c1726,10,.37);
  box(g,x,y,96,25,m.furniture,7);
  box(g,x+3,y+3,90,5,0xf7d8a3,3,.14);
  box(g,x+9,y+25,9,17,0x253345,2);
  box(g,x+78,y+25,9,17,0x253345,2);
  box(g,x+51,y+8,15,10,0x2b4055,3);
  circle(g,x+64,y+13,2,0x93b1bd);
}
function couch(g,x,y,m){
  box(g,x+4,y+16,100,24,0x0c1722,12,.35);
  box(g,x,y+4,105,32,m.sofa,11);
  box(g,x+7,y,92,16,m.furniture,9);
  box(g,x+12,y+18,38,10,m.accent,6,.18);
  box(g,x+58,y+18,32,10,0xe5cda2,6,.18);
}
function shelf(g,x,y,m,rows=3){
  box(g,x,y,94,73,0x192938,4);
  box(g,x+7,y+5,80,62,m.furniture,3);
  for(let k=1;k<rows;k++)box(g,x+7,y+5+k*(62/rows),80,3,0x272d37,1);
  for(let row=0;row<rows;row++)for(let col=0;col<4;col++){
    const xx=x+14+col*18, yy=y+12+row*(57/rows);
    box(g,xx,yy,9,12,[0x8a9cac,0xc7aa7a,m.accent,0x6b8e7c][(col+row)%4],1,.87);
  }
}
function artwork(g,r,m){
  const {x,y,width:w}=r;
  const px=x+w-160,py=y+89;
  // Each department has a functional visual signature, not duplicate boxes.
  switch(m.feature){
  case 'library':
    shelf(g,px,py,m);desk(g,x+171,y+210,m);break;
  case 'moodboard':
    box(g,px,py,108,76,0x1a2e43,5);box(g,px+8,py+8,92,60,0x4e6b78,3);
    for(let i=0;i<7;i++)box(g,px+13+(i%3)*28,py+12+Math.floor(i/3)*19,21,13,[0xf0bd78,0x7bd0c4,0x86abd5][i%3],2,.8);
    break;
  case 'charts':
    box(g,px,py,108,74,0x1b3148,5);box(g,px+6,py+6,96,61,0x35566d,3);
    for(let i=0;i<5;i++)box(g,px+14+i*17,py+56-(i*11)%39,10,(i*11)%39+2,m.accent,2,.81);
    break;
  case 'samples':
    shelf(g,px,py,m);for(let i=0;i<3;i++)box(g,px+8+i*32,py+55,20,16,0xb28c63,3,.88);break;
  case 'research':
    box(g,px,py,110,78,0x253c51,5);box(g,px+7,py+8,96,62,0x47637a,3);
    for(let i=0;i<6;i++)circle(g,px+20+i*14,py+41+Math.sin(i)*19,4,m.accent,.83);
    break;
  case 'support':
    for(let i=0;i<3;i++){
      box(g,px+i*36,py+3,31,63,0x1b3347,5);
      box(g,px+5+i*36,py+9,22,24,0x549c9c,3);
      box(g,px+6+i*36,py+39,20,6,m.accent,2,.48);
    } break;
  case 'checklist':
    box(g,px,py,106,78,0x193245,5);
    for(let i=0;i<3;i++){
      box(g,px+10,py+12+i*19,12,12,m.accent,3,.78);
      line(g,px+29,py+18+i*19,px+94,py+18+i*19,0xb7ced4,2,.85);
    }break;
  case 'logistics':
    shelf(g,px,py,m);break;
  case 'sales':
    box(g,px,py,109,76,0x25445b,5);box(g,px+7,py+7,95,63,0x466e89,4);
    for(let i=0;i<4;i++)line(g,px+16+i*22,py+17,px+16+i*22,py+54,m.accent,1,.42);
    line(g,px+16,py+54,px+82,py+22,0xc5dbe7,2,.7);break;
  case 'servers':
    for(let i=0;i<3;i++){
      box(g,px+2+i*35,py,30,78,0x1a2b39,5);
      for(let j=0;j<5;j++){box(g,px+7+i*35,py+9+j*13,20,6,0x416378,2);circle(g,px+23+i*35,py+12+j*13,2,m.accent,.88);}
    }break;
  default:
    box(g,px,py,105,70,0x243b4f,4);box(g,px+8,py+8,89,54,0x57758a,2);break;
  }
}

/** Adds room artwork behind people; no interaction or external data access. */
export function drawRoomEnvironment(parent, room) {
  const {theme:m, variant:v}=roomVisualSpec(room);
  const {x,y,width:w,height:h}=room;
  const root=new Container();parent.addChild(root);
  const plate=new Graphics();root.addChild(plate);floor(plate,room,m);
  const architecture=new Graphics();root.addChild(architecture);backWall(architecture,room,m);
  const lighting=new Graphics();root.addChild(lighting);
  lamp(lighting,x+111+v.lampOffset*10,y+96,m.glow);
  lamp(lighting,x+w-196,y+100,m.glow);
  const feature=new Graphics();root.addChild(feature);artwork(feature,room,m);
  const furniture=new Graphics();root.addChild(furniture);
  couch(furniture,x+29,y+h-95,m);
  desk(furniture,x+w-129,y+h-105,m);
  if(h>=465)desk(furniture,x+w-129,y+h-205,m);
  const foliage=new Graphics();root.addChild(foliage);
  plant(foliage,x+41,y+h-21,v.plantOffset===1);
  plant(foliage,x+w-42,y+h-24,v.plantOffset===2);
  // Add a little depth above the wall line, not a fake work-status indicator.
  const trim=new Graphics();root.addChild(trim);
  box(trim,x+16,y+72,w-32,6,m.accent,1,.27);
  line(trim,x+19,y+76,x+w-19,y+76,0xf8ebd1,1,.19);
  return root;
}

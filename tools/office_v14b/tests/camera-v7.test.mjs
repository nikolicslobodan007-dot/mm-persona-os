import test from 'node:test';
import assert from 'node:assert/strict';
import {cameraForCampus} from '../src/camera.mjs';
const layout={width:646,height:484,rooms:[{code:'UPRAVA',name:'Uprava',theme:'executive',x:58,y:70,width:530,height:344}]};
test('whole-building fits with B7 safe margins',()=>{
 const state=cameraForCampus(layout,1080,560,1,'');
 assert.equal(state.scale,Math.min(.965*1080/646,.955*560/484));
});
test('focused room uses more available height without clipping',()=>{
 const old=cameraForCampus(layout,1080,560,1,'');
 const focus=cameraForCampus(layout,1080,560,1,'UPRAVA');
 assert.ok(focus.scale>old.scale*1.1);
 assert.ok(focus.scale*344<560*.95);
 assert.ok(focus.scale*530<1080*.95);
});
test('zoom and focused target are deterministic',()=>{
 const a=cameraForCampus(layout,1080,560,1.15,'UPRAVA');
 const b=cameraForCampus(layout,1080,560,1.15,'UPRAVA');
 assert.deepEqual(a,b);
 assert.equal(Math.round(a.x+a.scale*(58+265)),540);
 assert.equal(Math.round(a.y+a.scale*(70+172)),280);
});
test('missing focus code does not zoom unknown location',()=>{
 assert.deepEqual(cameraForCampus(layout,1080,560,1,'MISSING'),cameraForCampus(layout,1080,560,1,''));
});

test('all focused departments now use actual room bounds',()=>{
 const another={...layout,rooms:[{...layout.rooms[0],code:'MKT',name:'Marketing',theme:'creative'}]};
 const before=cameraForCampus(another,1080,560,1,'');
 const focus=cameraForCampus(another,1080,560,1,'MKT');
 assert.ok(focus.scale > before.scale);
 assert.ok(focus.scale*530 <= 1080*.965);
 assert.ok(focus.scale*344 <= 560*.955);
});

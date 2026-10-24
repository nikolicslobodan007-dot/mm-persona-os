import test from 'node:test';
import assert from 'node:assert/strict';
import {departmentLabelScale,roomHitArea} from '../src/visual-legibility.mjs';
import {layoutCampus} from '../src/layout.mjs';
import {cameraForCampus} from '../src/camera.mjs';
const names=['Finansije','Istraživanje tržišta','Korisnička podrška','Kvalitet i usklađenost',
  'Logistika i magacin','Marketing i sadržaj','Nabavka i dobavljači','Prodaja i izvoz',
  'Razvoj i održavanje sistema','Uprava'];
const records=names.map((name,i)=>({public_id:`P-${String(i+1).padStart(5,'0')}`,
  display_name:`Test ${i}`,department:{code:`D${i}`,name}}));
test('10-room overview fills the viewport without clipping',()=>{
  const l=layoutCampus(records,'',{width:1050,height:530});
  const c=cameraForCampus(l,1050,530);
  assert.equal(l.columns,4);
  assert.ok(c.fittedWidth>945 && c.fittedWidth<=1050);
  assert.ok(c.fittedHeight>475 && c.fittedHeight<=530);
});
test('focused Uprava has larger scale and remains centered',()=>{
  const code='D9';
  const l=layoutCampus(records,code,{width:1050,height:530});
  const c=cameraForCampus(l,1050,530,1,code);
  const room=l.rooms[0];
  assert.equal(room.name,'Uprava');
  assert.ok(Math.abs(c.x+c.scale*(room.x+room.width/2)-525)<1e-7);
  assert.ok(Math.abs(c.y+c.scale*(room.y+room.height/2)-265)<1e-7);
  assert.ok(room.width*c.scale<1050 && room.height*c.scale<530);
});
test('department labels are legible at overview scale, but cannot intrude AI count',()=>{
  for(const scale of [0.28,0.42,0.85,1.3]){
    const result=departmentLabelScale(180,530,scale);
    assert.ok(Number.isFinite(result));
    assert.ok(result*180<=530-140+1e-7);
    assert.ok(result>=0.25 && result<=4);
  }
  assert.ok(departmentLabelScale(180,530,.42)>1);
});
test('room targets exclude title but cover floor and reject invalid dimensions',()=>{
  assert.deepEqual(roomHitArea({x:100,y:200,width:530,height:344}),
    {x:103,y:240,width:524,height:300});
  assert.equal(roomHitArea({x:0,y:0,width:0,height:10}),null);
});
test('IDs, sorting, agent membership and camera never invent activity',()=>{
  const result=layoutCampus(records,'',{width:1050,height:530});
  assert.equal(result.rooms.length,10);
  assert.equal(result.rooms.reduce((n,r)=>n+r.people.length,0),10);
  for(const r of result.rooms)for(const agent of r.people){
    assert.ok(agent.public_id.startsWith('P-'));
    assert.equal(agent.department.name,r.name);
    assert.ok(!Object.hasOwn(agent,'confirmedRunning'));
  }
});

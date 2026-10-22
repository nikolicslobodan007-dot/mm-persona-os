import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutCampus, roomTheme, safeAgent} from '../src/layout.mjs';
const a = (id, department, status='READY') => ({public_id:id,display_name:'Test Agent',status,runtime_environment:'SIMULATION',department:{code:department,name:department}});
test('does not create agents from unknown or invalid IDs',()=>{
  const scene = layoutCampus([a('P-00001','FINANCE'),a('not-an-id','RESEARCH')]);
  assert.equal(scene.rooms.length,1);assert.equal(scene.rooms[0].people.length,1);
});
test('groups deterministically and lays out nonoverlapping rooms',()=>{
  const scene=layoutCampus([a('P-00001','RESEARCH'),a('P-00002','FINANCE'),a('P-00003','RESEARCH')]);
  assert.equal(scene.rooms.length,2);
  assert.ok(scene.rooms[1].x >= scene.rooms[0].x + scene.rooms[0].width);
  assert.ok(scene.rooms.every(r => r.people.every(p => p.x >= r.x && p.x <= r.x+r.width)));
});
test('focused department returns only requested team',()=>{
  const scene=layoutCampus([a('P-00001','RESEARCH'),a('P-00002','FINANCE')],'FINANCE');
  assert.deepEqual(scene.rooms.map(r=>r.code),['FINANCE']);
});
test('does not infer running state from READY, ACTIVE or runtime',()=>{
  const p=safeAgent(a('P-00002','FINANCE','ACTIVE'));
  assert.equal(Object.hasOwn(p,'running'),false);
});
test('theme classification is non-sensitive and includes fallback',()=>{
  assert.equal(roomTheme('FINANCE','Finansije'),'finance');
  assert.equal(roomTheme('ODX','Odeljenje X'),'general');
});
test('long labels are capped and optional values safely default',()=>{
  const p=safeAgent({...a('P-00001','OPS'),display_name:'a'.repeat(350)});
  assert.equal(p.display_name.length,160);
  assert.equal(safeAgent(null),null);
});

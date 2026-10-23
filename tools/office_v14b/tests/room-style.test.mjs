import test from 'node:test';
import assert from 'node:assert/strict';
import {ROOM_THEME_NAMES,roomMaterial,roomVariant,roomVisualSpec} from '../src/room-style.mjs';
import {roomTheme,layoutCampus} from '../src/layout.mjs';
const base = (id,code,name) => ({public_id:id,display_name:'Test Agent',status:'READY',runtime_environment:'SIMULATION',department:{code,name}});

test('material palette covers every classified room and one safe fallback',()=>{
  const cases=[
    ['FINANCE','Finansije','finance'],['MKT','Marketing i sadržaj','creative'],
    ['UPRAVA','Uprava','executive'],['PROC','Nabavka i dobavljači','procurement'],
    ['SUP','Korisnička podrška','support'],['RESEARCH','Istraživanje tržišta','research'],
    ['QUALITY','Kvalitet i usklađenost','quality'],['MAG','Logistika i magacin','logistics'],
    ['SALES','Prodaja i izvoz','sales'],['SYS','Razvoj i održavanje sistema','technology'],
    ['UNLISTED','Nepoznato','general'],
  ];
  assert.equal(ROOM_THEME_NAMES.length,11);
  for(const [code,name,theme] of cases){
    assert.equal(roomTheme(code,name),theme,`${name} theme`);
    const palette=roomMaterial(theme);
    assert.ok(Number.isInteger(palette.floor)&&palette.floor>=0&&palette.floor<=0xffffff);
    assert.ok(palette.feature);
  }
});

test('department decor is deterministic, bounded and independent of agent status',()=>{
  const sample='UPRAVA';
  assert.deepEqual(roomVariant(sample),roomVariant(sample));
  assert.notDeepEqual(roomVariant(sample),roomVariant('FINANCE'));
  assert.equal(roomVariant(sample).plantOffset>=0,true);
  assert.equal(roomVariant(sample).plantOffset<3,true);
  const spec=roomVisualSpec({code:sample,theme:'executive',width:530,height:344});
  assert.equal(spec.theme.feature,'library');
  assert.equal(spec.width,530);
  assert.equal('status' in spec,false);
  assert.equal('running' in spec,false);
});

test('normal and unknown departments produce valid themed rooms',()=>{
  const out=layoutCampus([
    base('P-00001','SALES','Prodaja i izvoz'),
    base('P-00002','UNKNOWN','Nepoznato odeljenje'),
    base('P-00003','QUALITY','Kvalitet i usklađenost')
  ],'',{width:1080,height:650});
  assert.equal(out.rooms.length,3);
  assert.ok(out.rooms.every(r=>ROOM_THEME_NAMES.includes(r.theme)));
  assert.ok(out.rooms.every(r=>r.width>0 && r.height>0));
});

test('materials are immutable shared presets',()=>{
  const m=roomMaterial('finance');
  assert.ok(Object.isFrozen(m));
  assert.strictEqual(m,roomMaterial('finance'));
  assert.strictEqual(roomMaterial('__x__'),roomMaterial('general'));
});

test('only code and theme participate in room design identity',()=>{
  const one={code:'SUPPORT',theme:'support',width:530,height:344,private_notes:'do not leak'};
  const two={code:'SUPPORT',theme:'support',width:530,height:344,private_notes:'a different secret'};
  assert.deepEqual(roomVisualSpec(one),roomVisualSpec(two));
  assert.equal(JSON.stringify(roomVisualSpec(one)).includes('do not leak'),false);
});

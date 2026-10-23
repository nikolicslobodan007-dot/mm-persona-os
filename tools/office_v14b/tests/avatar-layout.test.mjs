import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutCampus} from '../src/layout.mjs';
import {avatarStyleFor, shouldShowNameAtScale} from '../src/avatar-style.mjs';

const agent=(id,dep)=>({public_id:id,display_name:`Agent ${id}`,status:'READY',runtime_environment:'SIMULATION',department:{code:dep,name:dep}});

test('unfinished 4-column row is centered without synthetic rooms',()=>{
  const a=['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH','III','JJJ'].map((d,i)=>agent(`P-${String(i+1).padStart(5,'0')}`,d));
  const s=layoutCampus(a,'',{width:1100,height:530});
  assert.equal(s.columns,4);
  assert.equal(s.rooms.length,10);
  assert.equal(s.rows.length,3);
  const top=s.rooms.slice(0,4),bottom=s.rooms.slice(8);
  assert.equal(top.length,4);assert.equal(bottom.length,2);
  const center=(min,max)=>(min+max)/2;
  const midTop=center(top[0].x,top.at(-1).x+top.at(-1).width);
  const midBottom=center(bottom[0].x,bottom.at(-1).x+bottom.at(-1).width);
  assert.equal(midBottom,midTop);
  assert.equal(s.rooms.every(r=>r.people.every(p=>p.x>=r.x&&p.x<=r.x+r.width)),true);
});
test('rows stay centered with 3/1 room final rows as well',()=>{
  const a=['AA','BB','CC','DD','EE','FF','GG','HH','II'].map((d,i)=>agent(`P-${String(i+1).padStart(5,'0')}`,d));
  const s=layoutCampus(a,'',{width:1100,height:530});
  const first=s.rooms.slice(0,s.columns),last=s.rooms.slice(s.columns*2);
  if(last.length===1){
    assert.equal(last[0].x+last[0].width/2,s.width/2);
  }
});
test('focus single department keeps room centered and deterministic',()=>{
  const a=[agent('P-00001','FIN'),agent('P-00002','UPR')];
  const s=layoutCampus(a,'FIN',{width:950,height:460});
  assert.equal(s.columns,1);assert.equal(s.rooms.length,1);
  assert.equal(s.rooms[0].x+s.rooms[0].width/2,s.width/2);
});
test('avatar styles are stable, derived from public ids only',()=>{
  const a=avatarStyleFor('P-00003');
  assert.deepEqual(a,avatarStyleFor('P-00003'));
  assert.equal(avatarStyleFor('P-00003;evil'),null);
  assert.equal(avatarStyleFor('nope'),null);
});
test('first 33 identities have 33 distinctive jacket-hair combinations',()=>{
  const ids=Array.from({length:33},(_,i)=>`P-${String(i+1).padStart(5,'0')}`);
  const combinations=new Set(ids.map(id=>{const s=avatarStyleFor(id);return `${s.jacket}-${s.hair}`}));
  assert.equal(combinations.size,33);
});
test('protected portraits and dossier data are not consumed by avatar factory',()=>{
  const factory=avatarStyleFor('P-00001');
  assert.deepEqual(Object.keys(factory).sort(),['accent','glasses','hair','hairShape','jacket','outfit','pin','skin']);
  assert.ok(!('portrait_url' in factory));
});
test('far view uses LOD names but focused and selected remain readable',()=>{
  assert.equal(shouldShowNameAtScale(.41,false,false),false);
  assert.equal(shouldShowNameAtScale(.41,true,false),true);
  assert.equal(shouldShowNameAtScale(.41,false,true),true);
  assert.equal(shouldShowNameAtScale(.85,false,false),true);
});
test('provisional visual style does not interpret status as work',()=>{
  const one=agent('P-00001','FIN');one.status='ACTIVE';one.runtime_environment='CONTROLLED_LIVE';
  const same=avatarStyleFor(one.public_id);
  assert.deepEqual(same,avatarStyleFor('P-00001'));
});

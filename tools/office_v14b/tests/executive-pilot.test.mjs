import test from 'node:test';
import assert from 'node:assert/strict';
import {B5_ASSETS, isExecutivePilotRoom, premiumAvatarKey, executiveViewAsset,
  safeB5AssetURL, loadB5Textures, b5RoomReady} from '../src/executive-pilot.mjs';
const room={code:'UPRAVA',name:'Uprava',theme:'executive',people:[
  {public_id:'P-00003',display_name:'Ivana Đurić'},
  {public_id:'P-00024',display_name:'Tamás Kovács'},
]};
const src = key => `/static/console/office-premium-b5/${key}.abc123ff.png`;
test('renders pilot only in an actual Uprava room',()=>{
  assert.ok(isExecutivePilotRoom(room));
  assert.equal(isExecutivePilotRoom({...room,name:'Marketing',code:'MKT'}),false);
  assert.equal(isExecutivePilotRoom({...room,theme:'creative'}),false);
});
test('matches pilot by name AND actual room membership; never assumes public IDs',()=>{
  for(const [name,key] of [['Ivana Đurić','ivana-avatar'],['Tamás Kovács','tamas-avatar']]){
    const agent=room.people.find(p=>p.display_name===name);
    assert.equal(premiumAvatarKey(agent,room),key);
    assert.equal(premiumAvatarKey({...agent,public_id:'P-99999'},room),null);
  }
  assert.equal(premiumAvatarKey({public_id:'P-00006',display_name:'Ivana Đurić'},room),null);
  assert.equal(premiumAvatarKey({...room.people[0],display_name:'Ivana Đurić (AI)'},room),'ivana-avatar');
  assert.equal(premiumAvatarKey({...room.people[0],display_name:'Druga osoba'},room),null);
});
test('focus view uses detail art only for matching department',()=>{
  assert.equal(executiveViewAsset(room,'UPRAVA'),'executive-room-detail');
  assert.equal(executiveViewAsset(room,'FINANCE'),'executive-room-overview');
});
test('all seven required resource keys are explicit',()=>{
  assert.equal(B5_ASSETS.length,7);
  assert.equal(new Set(B5_ASSETS).size,B5_ASSETS.length);
});
test('local asset paths permit Django hashed names',()=>{
  assert.equal(safeB5AssetURL('ivana-avatar',src('ivana-avatar'),'https://wk.example'),
    `https://wk.example${src('ivana-avatar')}`);
  assert.equal(safeB5AssetURL('tamas-avatar','/static/console/office-premium-b5/tamas-avatar.png','https://wk.example'),
    'https://wk.example/static/console/office-premium-b5/tamas-avatar.png');
});
test('URLs reject remote hosts, script classes, queries and traversal',()=>{
  for(const attempt of [
    'https://cdn.evil.example/static/console/office-premium-b5/ivana-avatar.png',
    '//cdn.evil.example/static/console/office-premium-b5/ivana-avatar.png',
    '/static/console/office-premium-b5/tamas-avatar.png',
    '/static/console/office-premium-b5/ivana-avatar.png?token=abc',
    '/static/console/office-premium-b5/ivana-avatar.png#x',
    '/static/console/office-premium-b5/ivana-avatar.svg',
    '/private/files/ivana-avatar.png',
  ]) assert.equal(safeB5AssetURL('ivana-avatar',attempt,'https://wk.example'),null);
});
test('reject invalid asset keys including prototype tricks',()=>{
  for(const key of ['__proto__','constructor','other-avatar','room-executive',''])
    assert.equal(safeB5AssetURL(key,src('ivana-avatar'),'https://wk.example'),null);
});
test('partial failures are tolerated, non-validated files not fetched',async()=>{
  const fetched=[];
  const out=await loadB5Textures(async url=>{
    fetched.push(url); if(url.includes('foreground'))throw Error('missing');return {url};
  },[
    {key:'ivana-avatar',url:src('ivana-avatar')},
    {key:'executive-room-foreground',url:src('executive-room-foreground')},
    {key:'tamas-avatar',url:'https://external.example/foo.png'},
  ],'https://wk.example');
  assert.equal(out.size,1);
  assert.ok(out.has('ivana-avatar'));
  assert.equal(fetched.length,2);
});
test('room fallback when key background missing',()=>{
  const map = new Map([['executive-room-overview',{texture:true}]]);
  assert.equal(b5RoomReady(room,map,''),true);
  assert.equal(b5RoomReady(room,map,'UPRAVA'),false);
  assert.equal(b5RoomReady({...room,name:'Nabavka',code:'NAB'},map,''),false);
});
test('no status, runtime, activity, secrets or dossiers are needed',()=>{
  assert.ok(!Object.keys(room).some(k=>/status|runtime|goal|dossier|private/i.test(k)));
  assert.equal(premiumAvatarKey({...room.people[0],status:'READY',runtime_environment:'SIMULATION'},room),'ivana-avatar');
});

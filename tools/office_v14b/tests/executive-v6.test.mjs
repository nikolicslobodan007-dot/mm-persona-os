import test from 'node:test';
import assert from 'node:assert/strict';
import {B6_ASSETS,safeB6AssetURL,loadB6Textures,b6RoomAsset,b6RoomReady,b6AvatarKey} from '../src/executive-v6.mjs';
const origin='https://webkorporacija.com';
const src=k=>`/static/console/office-premium-b6/${k}.png`;
const room={code:'UPRAVA',name:'Uprava',theme:'executive',people:[
  {public_id:'P-00003',display_name:'Ivana Đurić'},
  {public_id:'P-00004',display_name:'Tamás Kovács'},
]};
test('exactly five local asset keys',()=>{
 assert.deepEqual(B6_ASSETS,['executive-overview-v6','executive-detail-v6','executive-foreground-v6','ivana-v6','tamas-v6']);
});
test('Django regular and hashed URLs are valid',()=>{
 assert.equal(safeB6AssetURL('ivana-v6',src('ivana-v6'),origin),origin+src('ivana-v6'));
 assert.equal(safeB6AssetURL('executive-detail-v6',src('executive-detail-v6').replace('.png','.a1b2c3d4e5f6.png'),origin),
  origin+src('executive-detail-v6').replace('.png','.a1b2c3d4e5f6.png'));
});
test('remote, injection, mismatch, query and odd paths are blocked',()=>{
 for(const bad of [
  'https://cdn.example/static/console/office-premium-b6/ivana-v6.png',
  '//evil.example/static/console/office-premium-b6/ivana-v6.png',
  src('tamas-v6'),src('ivana-v6')+'?query=1',src('ivana-v6')+'#frag',
  '/static/console/office-premium-b6/../evil.png',
  '/static/console/office-premium-b6/ivana-v6.svg',
 ])assert.equal(safeB6AssetURL('ivana-v6',bad,origin),null,bad);
 for(const key of ['__proto__','constructor','other',''])assert.equal(safeB6AssetURL(key,src('ivana-v6'),origin),null);
});
test('asset loader deduplicates, handles partial failures and prevents remote loading',async()=>{
 const seen=[];
 const m=await loadB6Textures(async url=>{seen.push(url);if(url.includes('tamas'))throw Error('missing');return {url};},[
  {key:'ivana-v6',url:src('ivana-v6')},{key:'ivana-v6',url:src('ivana-v6')},
  {key:'tamas-v6',url:src('tamas-v6')},{key:'executive-detail-v6',url:'https://evil.example/'},
 ],origin);
 assert.equal(seen.length,2);assert.equal(m.size,1);assert.equal(m.has('ivana-v6'),true);
});
test('focused department uses detail only on actual Uprava',()=>{
 assert.equal(b6RoomAsset(room,''),'executive-overview-v6');
 assert.equal(b6RoomAsset(room,'UPRAVA'),'executive-detail-v6');
 assert.equal(b6RoomAsset({...room,name:'Marketing',code:'MKT'},'MKT'),null);
});
test('missing focused detail falls back rather than displaying wrong art',()=>{
 const loaded=new Map([['executive-overview-v6',{texture:true}]]);
 assert.equal(b6RoomReady(room,loaded,''),true);
 assert.equal(b6RoomReady(room,loaded,'UPRAVA'),false);
 assert.equal(b6RoomReady({...room,theme:'finance'},loaded,''),false);
});
test('two avatars are resolved by room membership, not guessed IDs or statuses',()=>{
 assert.equal(b6AvatarKey(room.people[0],room),'ivana-v6');
 assert.equal(b6AvatarKey(room.people[1],room),'tamas-v6');
 assert.equal(b6AvatarKey({...room.people[0],status:'READY',runtime_environment:'SIMULATION'},room),'ivana-v6');
 assert.equal(b6AvatarKey({...room.people[0],public_id:'P-99999'},room),null);
 assert.equal(b6AvatarKey({...room.people[0],display_name:'Other'},room),null);
});

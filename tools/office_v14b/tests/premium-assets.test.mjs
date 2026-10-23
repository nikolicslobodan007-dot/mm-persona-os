import test from 'node:test';
import assert from 'node:assert/strict';
import {roomAssetFile,safePremiumAssetURL,loadPremiumRoomAssets,ROOM_PREMIUM_THEMES} from '../src/premium-assets.mjs';
const origin='https://webkorporacija.com';
const path='/static/console/office-premium/room-finance.png';
test('eleven explicit themes',()=>assert.equal(ROOM_PREMIUM_THEMES.length,11));
test('unknown theme resolves to general filename',()=>assert.equal(roomAssetFile('../../bad'),'room-general.png'));
test('safe un-hashed URL accepted',()=>assert.equal(safePremiumAssetURL('finance',path,origin),origin+path));
test('Django hashed static URL accepted',()=>assert.equal(safePremiumAssetURL('finance','/static/console/office-premium/room-finance.0a1b2c3d4e5f.png',origin),origin+'/static/console/office-premium/room-finance.0a1b2c3d4e5f.png'));
test('different theme rejected',()=>assert.equal(safePremiumAssetURL('finance','/static/console/office-premium/room-executive.png',origin),null));
test('external origin rejected',()=>assert.equal(safePremiumAssetURL('finance','https://images.example/console/office-premium/room-finance.png',origin),null));
test('unrelated static path rejected',()=>assert.equal(safePremiumAssetURL('finance','/static/other/room-finance.png',origin),null));
test('directory traversal / malicious code rejected',()=>assert.equal(safePremiumAssetURL('finance','/static/console/office-premium/../evil.png',origin),null));
test('duplicate or unknown assets ignored',async()=>{
 let requests=0;
 const map=await loadPremiumRoomAssets(async url=>{requests++;return {url}},[
 {theme:'finance',url:path},{theme:'finance',url:path},{theme:'HACK',url:'https://evil.example'},
 {theme:'executive',url:'/static/console/office-premium/room-executive.png'},
 ],origin);
 assert.equal(requests,2);assert.equal(map.size,2);
});
test('failed asset is isolated and does not break other assets',async()=>{
 const map=await loadPremiumRoomAssets(async url=>{
 if(url.includes('room-finance'))throw Error('missing');return {url};
 },[{theme:'finance',url:path},{theme:'creative',url:'/static/console/office-premium/room-creative.png'}],origin);
 assert.equal(map.has('finance'),false);assert.equal(map.has('creative'),true);
});
test('no entries or loader => empty Map',async()=>{
 assert.equal((await loadPremiumRoomAssets(null,[],origin)).size,0);
 assert.equal((await loadPremiumRoomAssets(async()=>true,null,origin)).size,0);
});

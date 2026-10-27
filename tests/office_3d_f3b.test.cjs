const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,readdirSync}=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../console/static/console');
const oldWindow=global.window;
global.window=global;
require(path.join(root,'office-3d-f3a.js'));
require(path.join(root,'office-3d-f3b.js'));
const f3a=window.WKOfficeF3A,f3b=window.WKOfficeF3B;
const origin='https://webkorporacija.com';
const url=k=>`/static/console/office-3d-avatars/f3b-${k}.glb`;
const keys=f3b.NAMES;
function bin(key){const f=readFileSync(path.join(root,'office-3d-avatars',`f3b-${key}.glb`));return f.buffer.slice(f.byteOffset,f.byteOffset+f.byteLength);}

test('five real GLB avatars use vertex colors and valid pre-baked geometry',()=>{
 assert.deepEqual(readdirSync(path.join(root,'office-3d-avatars')).sort(),keys.map(k=>`f3b-${k}.glb`).sort());
 for(const k of keys){
  const b=bin(k);assert.ok(b.byteLength>10000 && b.byteLength<300000);
  const verts=f3a.readGLB(b);assert.equal(verts.length%27,0);
  assert.ok(verts.length>4000);assert.ok(verts.every(Number.isFinite));
 }
});
test('public_id variant mapping is stable, bounded and uses no names / portraits',()=>{
 assert.equal(new Set([1,2,3,4,5].map(n=>f3b.variantFor(`P-${String(n).padStart(5,'0')}`))).size,5);
 const big='P-12345678901234567890';assert.equal(f3b.variantFor(big),f3b.variantFor(big));
 for(const id of ['P-1','P-../../secret','P-0000X','','__proto__',null])assert.equal(f3b.variantFor(id),null);
 assert.equal(f3b.variantFor('P-00001'),'agent-2');
});
test('supports local and Django fingerprinted filenames',()=>{
 assert.equal(f3b.safeModelURL('agent-3',url('agent-3'),origin),origin+url('agent-3'));
 assert.equal(f3b.safeModelURL('agent-3','/static/console/office-3d-avatars/f3b-agent-3.aabbccdd1234.glb',origin),origin+'/static/console/office-3d-avatars/f3b-agent-3.aabbccdd1234.glb');
});
test('reject remote origins, hashes, wrong model, query strings and code URLs',()=>{
 for(const attempt of [
  'https://other.example'+url('agent-3'),'//cdn.evil.example'+url('agent-3'),
  url('agent-2'),url('agent-3')+'?sig=1',url('agent-3')+'#asset',
  '/static/console/office-3d-avatars/../f3b-agent-3.glb',
  'data:application/javascript,x','javascript:alert(1)'
 ])assert.equal(f3b.safeModelURL('agent-3',attempt,origin),null,attempt);
 for(const k of ['__proto__','constructor','agent-0','agent-6','','f3a-room'])assert.equal(f3b.safeModelURL(k,url('agent-3'),origin),null);
});
test('template has five Django assets and correct local script load order',()=>{
 const h=readFileSync(path.resolve(__dirname,'../console/templates/console/office_3d.html'),'utf8');
 assert.equal((h.match(/name="wk-f3b-model"/g)||[]).length,5);
 assert.ok(h.indexOf('office-3d-f3a.js')<h.indexOf('office-3d-f3b.js'));
 assert.ok(h.indexOf('office-3d-f3b.js')<h.indexOf('office-3d.js'));
 const main=readFileSync(path.join(root,'office-3d.js'),'utf8');
 assert.ok(main.includes('if(figuresDrawn)drawStatusFeet(cube)'));
 assert.ok(main.includes('else drawSeatMarkers(cube)'));
 assert.ok(main.includes('selected') && main.includes('state.shown'));
 assert.ok(main.includes("renderer?.f3b?.ready) ? 2.35 : 1.9"));
});
function fakeGL(){
 const calls={upload:[],draw:[],offset:[],deleted:[]};let id=0;
 const gl={VERTEX_SHADER:1,FRAGMENT_SHADER:2,COMPILE_STATUS:3,LINK_STATUS:4,ARRAY_BUFFER:5,STATIC_DRAW:6,FLOAT:7,TRIANGLES:8};
 for(const fn of ['createShader','createProgram','createBuffer'])gl[fn]=()=>({id:++id});
 for(const fn of ['shaderSource','compileShader','attachShader','linkProgram','useProgram','deleteShader','bindBuffer','enableVertexAttribArray','vertexAttribPointer','uniformMatrix4fv'])gl[fn]=()=>{};
 gl.deleteBuffer=b=>calls.deleted.push(b);
 gl.deleteProgram=b=>calls.deleted.push(b);
 gl.getShaderParameter=()=>true;gl.getProgramParameter=()=>true;
 gl.getAttribLocation=(p,k)=>({aPos:0,aNorm:1,aColor:2}[k]);
 gl.getUniformLocation=(p,k)=>k;
 gl.bufferData=(target,data,usage)=>calls.upload.push(data.length);
 gl.uniform3f=(loc,x,y,z)=>calls.offset.push([x,y,z]);
 gl.drawArrays=(mode,start,count)=>calls.draw.push(count);
 return {gl,calls};
}
const entries=keys.map(key=>({key,url:url(key)}));
function withFetch(fn){const original=global.fetch;
 global.fetch=async u=>{const k=String(u).match(/f3b-(agent-[1-5])\.glb/)?.[1];
 if(!k)throw Error('unexpected URL');let b=bin(k);
 return {ok:true,headers:{get:()=>String(b.byteLength)},arrayBuffer:async()=>b};};
 return Promise.resolve().then(fn).finally(()=>global.fetch=original);
}
test('GPU uploads 5 assets and draws only the currently visible 5 agents',async()=>{
 await withFetch(async()=>{
  const {gl,calls}=fakeGL();const engine=f3b.create(gl);
  assert.equal(engine.ready,false);
  await engine.load(entries,origin);assert.equal(engine.ready,true);
  assert.equal(calls.upload.length,5);
  const shown=Array.from({length:7},(_,i)=>({public_id:`P-${String(i+1).padStart(5,'0')}`,display_name:`TEST ${i}`}));
  assert.ok(engine.render(Array(16).fill(0),shown));
  assert.equal(calls.draw.length,5);assert.equal(calls.offset.length,5);
  assert.deepEqual(calls.offset.map(x=>x[0]),[-4.2,-2.1,0,2.1,4.2]);
  engine.dispose();assert.equal(engine.ready,false);assert.equal(calls.deleted.length,6);
  engine.dispose();assert.equal(calls.deleted.length,6);
 });
});
test('empty or invalid data cannot produce invented agent figures',async()=>{
 await withFetch(async()=>{
  const {gl,calls}=fakeGL();const engine=f3b.create(gl);await engine.load(entries,origin);
  assert.equal(engine.render(Array(16).fill(0),[]),true);assert.equal(calls.draw.length,0);
  assert.equal(engine.render(Array(16).fill(0),[{public_id:'evil'}]),true);assert.equal(calls.draw.length,0);
  engine.dispose();
 });
});
test('loader rejects missing asset, preserving F3A fallback',async()=>{
 const {gl}=fakeGL();const e=f3b.create(gl);
 await assert.rejects(e.load(entries.slice(0,3),origin),/five allowlisted/);
 assert.equal(e.ready,false);assert.equal(e.render(Array(16).fill(0),[{public_id:'P-00001'}]),false);e.dispose();
});
test('bad GLB and denied HTTP response never activate avatar rendering',async()=>{
 const original=global.fetch;
 try{
  const {gl}=fakeGL();const e=f3b.create(gl);
  global.fetch=async()=>({ok:false,status:404,headers:{get:()=>0}});
  await assert.rejects(e.load(entries,origin),/HTTP 404/);assert.equal(e.ready,false);
  global.fetch=async()=>({ok:true,headers:{get:()=>100},arrayBuffer:async()=>new ArrayBuffer(100)});
  await assert.rejects(e.load(entries,origin),/GLB/);assert.equal(e.ready,false);e.dispose();
 }finally{global.fetch=original;}
});
test('static scene never fetches API or runs untrusted generated code in F3B module',()=>{
 const s=readFileSync(path.join(root,'office-3d-f3b.js'),'utf8');
 assert.ok(!s.includes('/api/v1/'));assert.ok(!/\beval\s*\(|new Function\s*\(/.test(s));
});

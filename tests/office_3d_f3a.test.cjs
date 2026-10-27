const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,readdirSync}=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../console/static/console');
const previous=global.window;global.window=global;
require(path.join(root,'office-3d-f3a.js'));
const f3a=global.WKOfficeF3A;
const origin='https://webkorporacija.com';
test('all five local GLB assets exist and parse as actual geometry',()=>{
  const dir=path.join(root,'office-3d-models');
  const names=['room','desk','chair','plant','shelf'];
  assert.deepEqual(readdirSync(dir).sort(),names.map(n=>`f3a-${n}.glb`).sort());
  for (const n of names){
    const file=readFileSync(path.join(dir,`f3a-${n}.glb`));
    const buffer=file.buffer.slice(file.byteOffset,file.byteOffset+file.byteLength);
    const triangles=f3a.readGLB(buffer);
    assert.equal(triangles.length%27,0);
    assert.ok(triangles.length>200);
    assert.ok(triangles.every(Number.isFinite));
  }
});
test('same-origin static paths and fingerprinted names are allowed',()=>{
  assert.equal(f3a.validatedURL('room','/static/console/office-3d-models/f3a-room.glb',origin),origin+'/static/console/office-3d-models/f3a-room.glb');
  assert.equal(f3a.validatedURL('room','/static/console/office-3d-models/f3a-room.aabbccddeeff.glb',origin),origin+'/static/console/office-3d-models/f3a-room.aabbccddeeff.glb');
});
test('external hosts, mismatched assets and query params are rejected',()=>{
  for(const url of ['https://evil.example/static/console/office-3d-models/f3a-room.glb',
    '//evil.example/static/console/office-3d-models/f3a-room.glb',
    '/static/console/office-3d-models/f3a-desk.glb',
    '/static/console/office-3d-models/f3a-room.glb?token=abcd',
    '/static/console/office-3d-models/f3a-room.glb#anything',
    '/static/console/office-3d-models/../f3a-room.glb',
    'data:application/octet-stream;base64,aGVsbG8='])
    assert.equal(f3a.validatedURL('room',url,origin),null,url);
});
test('proto pollution is not a model key',()=>{
  for(const k of ['__proto__','constructor','toString','glb',''])
    assert.equal(f3a.validatedURL(k,'/static/console/office-3d-models/f3a-room.glb',origin),null);
});
test('invalid and oversized binary blobs are rejected',()=>{
  assert.throws(()=>f3a.readGLB(new ArrayBuffer(1)),/GLB/);
  assert.throws(()=>f3a.readGLB(new ArrayBuffer(4*1024*1024)),/GLB/);
  const file=readFileSync(path.join(root,'office-3d-models/f3a-room.glb'));
  const buf=Uint8Array.from(file).buffer;
  new DataView(buf).setUint32(0,0,true);
  assert.throws(()=>f3a.readGLB(buf),/GLB/);
});
test('asset script loads ahead of main office app',()=>{
  const html=readFileSync(path.resolve(__dirname,'../console/templates/console/office_3d.html'),'utf8');
  assert.ok(html.indexOf('office-3d-f3a.js')<html.indexOf('office-3d.js'));
  assert.equal((html.match(/name="wk-f3a-model"/g)||[]).length,5);
});
function fakeGL() {
 let next=0;
 const calls={draw:[],uploaded:[]};
 const gl={VERTEX_SHADER:1,FRAGMENT_SHADER:2,COMPILE_STATUS:3,LINK_STATUS:4,ARRAY_BUFFER:5,STATIC_DRAW:6,FLOAT:7,TRIANGLES:8};
 for(const fn of ['createShader','createProgram','createBuffer'])gl[fn]=()=>({id:++next});
 for(const fn of ['shaderSource','compileShader','deleteShader','attachShader','linkProgram','useProgram','deleteProgram','bindBuffer','deleteBuffer','enableVertexAttribArray','vertexAttribPointer','uniform3f','uniformMatrix4fv'])gl[fn]=()=>{};
 gl.getShaderParameter=()=>true;gl.getProgramParameter=()=>true;
 gl.getAttribLocation=(p,s)=>({aPos:0,aNorm:1,aColor:2}[s]);
 gl.getUniformLocation=(p,s)=>s;
 gl.bufferData=(target,buf,usage)=>calls.uploaded.push(buf.length);
 gl.drawArrays=(mode,start,count)=>calls.draw.push(count);
 return {gl,calls};
}
test('WebGL abstraction uploads five models, draws room and workstations',async()=>{
 const {gl,calls}=fakeGL();const engine=f3a.create(gl);
 const oldFetch=global.fetch;
 global.fetch=async url=>{
   const key=String(url).match(/f3a-(room|desk|chair|plant|shelf)\.glb/)?.[1];
   const file=readFileSync(path.join(root,`office-3d-models/f3a-${key}.glb`));
   return {ok:true,headers:{get:()=>String(file.length)},arrayBuffer:async()=>file.buffer.slice(file.byteOffset,file.byteOffset+file.byteLength)};
 };
 try{
   const entries=['room','desk','chair','plant','shelf'].map(key=>({key,url:`/static/console/office-3d-models/f3a-${key}.glb`}));
   assert.equal(engine.ready,false);
   await engine.load(entries,origin);
   assert.equal(engine.ready,true);
   assert.equal(calls.uploaded.length,5);
   assert.ok(engine.render(Array(16).fill(0),Array(5).fill({public_id:'P-00001'})));
   assert.equal(calls.draw.length,14); // 1 shell + 5 desks + 5 chairs + 2 plants + 1 bookshelf
   engine.dispose();assert.equal(engine.ready,false);
 }finally{global.fetch=oldFetch;}
});
test('GLB renderer refuses incomplete model manifests, keeping legacy fallback',async()=>{
 const {gl}=fakeGL();const engine=f3a.create(gl);
 await assert.rejects(engine.load([{key:'room',url:'/static/console/office-3d-models/f3a-room.glb'}],origin),/missing model URL/);
 assert.equal(engine.ready,false);
 assert.equal(engine.render(Array(16).fill(0),[]),false);
 engine.dispose();
});

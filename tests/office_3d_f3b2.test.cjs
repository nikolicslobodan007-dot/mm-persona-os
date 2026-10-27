const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../console/static/console');
const before=global.window;global.window=global;
require(path.join(root,'office-3d-f3b2.js'));
const f=global.WKOfficeF3B2;
const origin='https://webkorporacija.com';
const agent=(id='P-00003',extra={})=>({public_id:id,portrait_url:`/console/office/portraits/${id}`,...extra});
test('only existing canonical portrait proxy for same public ID accepted',()=>{
  assert.equal(f.portraitURL(agent(),origin),origin+'/console/office/portraits/P-00003');
  for(const a of [agent('BAD'),agent('P-00003',{portrait_url:'/console/office/portraits/P-00004'}),
    agent('P-00003',{portrait_url:'https://evil.example/portrait.png'}),
    agent('P-00003',{portrait_url:'/console/office/portraits/P-00003?download=1'}),
    agent('P-00003',{portrait_url:'/static/private/foo.png'}),
    agent('P-00003',{portrait_url:null}),null])assert.equal(f.portraitURL(a,origin),null);
});
test('does not infer image identity or fetch photos from generic model file paths',()=>{
  assert.equal(f.portraitURL({public_id:'P-00003',display_name:'Ivana Đurić'},origin),null);
  assert.equal(f.portraitURL(agent(), 'javascript:alert(1)'),null);
});
test('script is local and loaded after F3B models, before main controller',()=>{
  const html=fs.readFileSync(path.resolve(__dirname,'../console/templates/console/office_3d.html'),'utf8');
  assert.ok(html.indexOf('office-3d-f3b.js')<html.indexOf('office-3d-f3b2.js'));
  assert.ok(html.indexOf('office-3d-f3b2.js')<html.indexOf('office-3d.js'));
  assert.ok(!html.includes('cdn.')&&!html.includes('<script src="http'));
});
function fakeGL(){
  let id=0;
  const calls={draw:[],deleted:[],mask:[],depth:[]};
  const gl={VERTEX_SHADER:1,FRAGMENT_SHADER:2,COMPILE_STATUS:3,LINK_STATUS:4,ARRAY_BUFFER:5,
    STATIC_DRAW:6,FLOAT:7,TRIANGLES:8,TEXTURE0:9,TEXTURE_2D:10,RGBA:11,
    UNSIGNED_BYTE:12,TEXTURE_MIN_FILTER:13,TEXTURE_MAG_FILTER:14,LINEAR:15,
    TEXTURE_WRAP_S:16,TEXTURE_WRAP_T:17,CLAMP_TO_EDGE:18,DEPTH_TEST:19,UNPACK_FLIP_Y_WEBGL:20};
  for(const fn of ['createShader','createProgram','createBuffer','createTexture'])gl[fn]=()=>({id:++id});
  for(const fn of ['shaderSource','compileShader','deleteShader','attachShader','linkProgram','useProgram',
    'deleteProgram','bindBuffer','deleteBuffer','enableVertexAttribArray','vertexAttribPointer',
    'uniform1i','uniform1f','uniform3f','uniformMatrix4fv','bufferData','activeTexture',
    'bindTexture','texImage2D','texParameteri','pixelStorei'])gl[fn]=()=>{};
  gl.getShaderParameter=()=>true;gl.getProgramParameter=()=>true;
  gl.getAttribLocation=()=>0;gl.getUniformLocation=(p,n)=>n;
  gl.depthMask=x=>calls.mask.push(x);
  gl.enable=x=>calls.depth.push('enable:'+x);gl.disable=x=>calls.depth.push('disable:'+x);
  gl.drawArrays=(...args)=>calls.draw.push(args);
  gl.deleteTexture=x=>calls.deleted.push(x);
  return {gl,calls};
}
test('no portrait network operation until actual agent register includes trusted proxy',()=>{
  const {gl}=fakeGL(),e=f.create(gl);
  e.sync([{public_id:'P-00003',portrait_url:'https://evil.example'}],origin);
  assert.equal(e.count,0);
  e.dispose();e.dispose();
});
test('separate authenticated faces get independent textures and removed on paging',async()=>{
  const oldImage=global.Image,oldDocument=global.document;
  const {gl,calls}=fakeGL();
  global.Image=class {set src(url){this.naturalWidth=160;this.naturalHeight=170;queueMicrotask(()=>this.onload());}};
  global.document={createElement:()=>({width:0,height:0,getContext:()=>({drawImage:()=>{}})})};
  try{
    const e=f.create(gl);
    e.sync([agent('P-00001'),agent('P-00002')],origin);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(e.count,2);
    assert.equal(e.render(Array(16).fill(0),[agent('P-00001'),agent('P-00002')],-.5,'P-00002'),2);
    assert.equal(calls.draw.length,2);
    assert.deepEqual(calls.mask.slice(-2),[false,true]);
    assert.ok(calls.depth.slice(-2).includes('enable:19'));
    e.sync([agent('P-00002')],origin);
    assert.equal(e.count,1);
    assert.equal(calls.deleted.length,1);
    e.dispose();assert.equal(e.count,0);assert.equal(calls.deleted.length,2);
  }finally{global.Image=oldImage;global.document=oldDocument;}
});
test('pending network result cannot reintroduce agent who left current page',async()=>{
  const oldImage=global.Image,oldDocument=global.document;
  let savedImage;
  global.Image=class {set src(url){savedImage=this;this.naturalWidth=160;this.naturalHeight=170;}};
  global.document={createElement:()=>({getContext:()=>({drawImage:()=>{}})})};
  try{
    const {gl}=fakeGL(),e=f.create(gl);
    e.sync([agent('P-00010')],origin);
    e.sync([agent('P-00011',{portrait_url:null})],origin);
    savedImage.onload();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(e.count,0);e.dispose();
  }finally{global.Image=oldImage;global.document=oldDocument;}
});
test('F3B2 source does not contain API writes, remote hosts or persistent storage',()=>{
  const js=fs.readFileSync(path.join(root,'office-3d-f3b2.js'),'utf8');
  assert.ok(!/localStorage|sessionStorage|indexedDB|sendBeacon|method:\s*["']POST|method:\s*["']PUT|method:\s*["']DELETE|analytics/i.test(js.split('  window.WKOfficeF3B2')[0].replace(/\/\*[\s\S]*?\*\//g,'')));
  assert.ok(!js.includes('fetch('));
  assert.ok(js.includes('gl.deleteTexture'));
});
if(before===undefined)delete global.window;else global.window=before;

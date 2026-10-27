/* WK-3D F3A — reviewed static GLB renderer, no remote code, no dependencies.
 * Business data and clickable agent labels stay in office-3d.js / V1.2 API.
 * Only load exact Django same-origin GLB paths, never execute 3DCodeVerse source code.
 */
(() => {
  'use strict';
  const NAMES = Object.freeze(['room','desk','chair','plant','shelf']);
  const LIMIT_BYTES = 3 * 1024 * 1024;
  const MAX_TRIANGLES = 90000;
  const XS = Object.freeze([-4.2,-2.1,0,2.1,4.2]);
  const encoder = new TextDecoder();
  const clamp = (n,a,b)=>Math.max(a,Math.min(b,n));

  function validatedURL(key, supplied, origin) {
    if (!NAMES.includes(key) || typeof supplied !== 'string') return null;
    try {
      const root = new URL(origin);
      const u = new URL(supplied, root);
      if (u.origin !== root.origin || !['https:', 'http:'].includes(u.protocol) ||
          u.username || u.password || u.search || u.hash) return null;
      const expected = new RegExp(`^/static/console/office-3d-models/f3a-${key}(?:\\.[a-f0-9]{8,})?\\.glb$`,'i');
      return expected.test(u.pathname) ? u.href : null;
    } catch (_) {return null;}
  }
  function readGLB(buffer) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 28 || buffer.byteLength > LIMIT_BYTES)
      throw new Error('F3A: neispravna veličina GLB modela');
    const dv=new DataView(buffer);
    if (dv.getUint32(0,true)!==0x46546c67 || dv.getUint32(4,true)!==2 ||
        dv.getUint32(8,true)!==buffer.byteLength) throw new Error('F3A: neispravno GLB zaglavlje');
    let json=null, binary=null, cursor=12;
    while(cursor+8<=buffer.byteLength) {
      const length=dv.getUint32(cursor,true),kind=dv.getUint32(cursor+4,true);cursor+=8;
      if(length>buffer.byteLength-cursor)throw new Error('F3A: neispravna GLB dužina');
      if(kind===0x4e4f534a)json=JSON.parse(encoder.decode(new Uint8Array(buffer,cursor,length)).trim());
      if(kind===0x004e4942)binary=new DataView(buffer,cursor,length);
      cursor+=length;
    }
    if (!json || !binary || !Array.isArray(json.meshes) || json.buffers?.length!==1 ||
        json.buffers[0]?.uri || (json.extensionsRequired?.length || 0)>0 ||
        json.buffers[0].byteLength>binary.byteLength) throw new Error('F3A: unsupported GLB');
    // F3A model factory pre-bakes transforms into vertices. Reject transformed nodes.
    for(const n of json.nodes||[]) {
      if(n.matrix || n.rotation || n.translation || n.scale)throw new Error('F3A: scene transformations are not baked');
    }
    const SIZES={5120:1,5121:1,5122:2,5123:2,5125:4,5126:4};
    const LENGTHS={SCALAR:1,VEC2:2,VEC3:3,VEC4:4};
    function accessor(index) {
      const a=json.accessors?.[index],v=json.bufferViews?.[a?.bufferView];
      const bytes=SIZES[a?.componentType],count=LENGTHS[a?.type];
      if(!v || !bytes || !count || !Number.isInteger(a.count) || a.count<0 || a.count>150000 || a.sparse || v.buffer!==0)
        throw new Error('F3A: unsupported accessor');
      const stride=v.byteStride||bytes*count,start=v.byteOffset||0,off=a.byteOffset||0;
      const end=start+off+(a.count?stride*(a.count-1)+bytes*count:0);
      if(stride<bytes*count || stride%bytes || end>binary.byteLength || end>start+v.byteLength)
        throw new Error('F3A: accessor outside binary data');
      const read=(i,k)=>{
        const pos=start+off+i*stride+k*bytes;
        switch(a.componentType){
        case 5121: return a.normalized?binary.getUint8(pos)/255:binary.getUint8(pos);
        case 5123: return a.normalized?binary.getUint16(pos,true)/65535:binary.getUint16(pos,true);
        case 5125: return binary.getUint32(pos,true);
        case 5126: return binary.getFloat32(pos,true);
        case 5122: return binary.getInt16(pos,true);
        case 5120: return binary.getInt8(pos);
        default: throw new Error('F3A: unsupported component');
        }
      };
      return {size:count,length:a.count,read};
    }
    const vertices=[];let triangles=0;
    for(const mesh of json.meshes)for(const p of mesh.primitives||[]) {
      if (p.mode!==undefined && p.mode!==4)throw new Error('F3A: triangles only');
      const pos=accessor(p.attributes?.POSITION),norm=accessor(p.attributes?.NORMAL),color=accessor(p.attributes?.COLOR_0);
      if(pos.size!==3||norm.size!==3||color.size<3||pos.length!==norm.length||pos.length!==color.length)
        throw new Error('F3A: expected POSITION/NORMAL/COLOR_0');
      const ix=(p.indices!==undefined?accessor(p.indices):null);
      const n=ix?ix.length:pos.length;
      if(n%3 || triangles+n/3>MAX_TRIANGLES)throw new Error('F3A: triangle limit');
      triangles+=n/3;
      for(let j=0;j<n;j++) {
        const k=ix?ix.read(j,0):j;
        if(!Number.isInteger(k)||k>=pos.length||k<0)throw new Error('F3A: out of range index');
        for(let c=0;c<3;c++)vertices.push(pos.read(k,c));
        for(let c=0;c<3;c++)vertices.push(norm.read(k,c));
        for(let c=0;c<3;c++)vertices.push(clamp(color.read(k,c),0,1));
      }
    }
    if(!triangles)throw new Error('F3A: empty geometry');
    const out=new Float32Array(vertices);
    if(!out.every(Number.isFinite))throw new Error('F3A: non-finite geometry');
    return out;
  }
  function compile(gl, type, src) {
    const shader=gl.createShader(type);gl.shaderSource(shader,src);gl.compileShader(shader);
    if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){const err=gl.getShaderInfoLog(shader);gl.deleteShader(shader);throw new Error('F3A GL shader: '+err);}
    return shader;
  }
  function create(gl) {
    const vertex = compile(gl,gl.VERTEX_SHADER,`attribute vec3 aPos,aNorm,aColor;
      uniform mat4 uVP;uniform vec3 uOffset;varying vec3 vCol;varying float vLight;
      void main(){gl_Position=uVP*vec4(aPos+uOffset,1.0);vCol=aColor;
      vLight=0.55+0.45*max(0.0,dot(normalize(aNorm),normalize(vec3(-0.45,0.88,0.36))));}`);
    const fragment=compile(gl,gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 vCol;varying float vLight;
      void main(){gl_FragColor=vec4(vCol*vLight,1.0);}`);
    const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);
    gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('F3A GL program');
    gl.deleteShader(vertex);gl.deleteShader(fragment);
    const attr=[gl.getAttribLocation(program,'aPos'),gl.getAttribLocation(program,'aNorm'),gl.getAttribLocation(program,'aColor')];
    const vpLoc=gl.getUniformLocation(program,'uVP'),offsetLoc=gl.getUniformLocation(program,'uOffset');
    const buffers=new Map();let ready=false;
    function draw(name,x=0,y=0,z=0) {
      const mesh=buffers.get(name);if(!mesh)return;
      gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);
      for(let i=0;i<3;i++){
        gl.enableVertexAttribArray(attr[i]);gl.vertexAttribPointer(attr[i],3,gl.FLOAT,false,9*4,i*3*4);
      }
      gl.uniform3f(offsetLoc,x,y,z);gl.drawArrays(gl.TRIANGLES,0,mesh.count);
    }
    async function load(entries, origin) {
      const safe=new Map();
      for(const e of entries||[]) {
        if(!e || safe.has(e.key))continue;
        const url=validatedURL(e.key,e.url,origin);
        if(url)safe.set(e.key,url);
      }
      if(NAMES.some(k=>!safe.has(k)))throw new Error('F3A: missing model URL');
      const generated=await Promise.all(NAMES.map(async key=>{
        const response=await fetch(safe.get(key),{credentials:'same-origin',mode:'same-origin'});
        if(!response.ok)throw new Error(`F3A: model ${key} HTTP ${response.status}`);
        if(Number(response.headers.get('content-length')||0)>LIMIT_BYTES)throw new Error('F3A: model too large');
        return [key,readGLB(await response.arrayBuffer())];
      }));
      try {
        for(const [key,data] of generated){const buf=gl.createBuffer();if(!buf)throw new Error('F3A GPU buffer');
          gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
          buffers.set(key,{buffer:buf,count:data.length/9});}
      }catch(e){for(const v of buffers.values())gl.deleteBuffer(v.buffer);buffers.clear();throw e;}
      ready=true;
    }
    function render(vp,shown) {
      if(!ready)return false;
      gl.useProgram(program);gl.uniformMatrix4fv(vpLoc,false,new Float32Array(vp));
      draw('room');
      for(let i=0;i<(shown||[]).length&&i<5;i++){
        const x=XS[i],z=i%2===0?0:0.30;
        draw('desk',x,0,z);
        draw('chair',x,0,z+1.25);
      }
      draw('plant',5.23,0,2.98);draw('plant',-5.12,0,3.19);
      draw('shelf',4.15,0,-3.95);
      return true;
    }
    function dispose() {for(const v of buffers.values())gl.deleteBuffer(v.buffer);buffers.clear();ready=false;gl.deleteProgram(program);}
    return {load,render,dispose,get ready(){return ready;}};
  }
  window.WKOfficeF3A=Object.freeze({validatedURL,readGLB,create});
})();

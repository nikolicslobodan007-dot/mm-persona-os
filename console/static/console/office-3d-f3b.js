/* WK-3D F3B: five original, static GLB visual variants of professional office agents.
 * Never infer appearance from names/photos; public_id only selects a deterministic style.
 * Renderer is read-only. It receives the SAME five agents as F3A and never calls API.
 * Requires local F3A readGLB validation; no CDN, dynamic code, external asset URLs.
 */
(() => {
  'use strict';
  const NAMES=Object.freeze(['agent-1','agent-2','agent-3','agent-4','agent-5']);
  const XS=Object.freeze([-4.2,-2.1,0,2.1,4.2]);
  const LIMIT=3*1024*1024;
  const ID=/^P-\d{5,20}$/;
  function variantFor(publicId) {
    if(typeof publicId!=='string'||!ID.test(publicId))return null;
    // Modulo digits, rather than integer conversion, preserves 20-digit IDs precisely.
    let mod=0;
    for(const digit of publicId.slice(2))mod=(mod*10+Number(digit))%5;
    return NAMES[mod];
  }
  function safeModelURL(key,supplied,origin) {
    if(!NAMES.includes(key)||typeof supplied!=='string'||!supplied)return null;
    try {
      const root=new URL(origin),url=new URL(supplied,root);
      if(!['https:','http:'].includes(root.protocol)||url.origin!==root.origin||
          url.username||url.password||url.search||url.hash)return null;
      const pattern=new RegExp(`^/static/console/office-3d-avatars/f3b-${key}(?:\\.[a-f0-9]{8,})?\\.glb$`,'i');
      return pattern.test(url.pathname)?url.href:null;
    }catch(_){return null;}
  }
  function shader(gl,type,src){
    const obj=gl.createShader(type);
    if(!obj)throw new Error('F3B: shader allocation');
    gl.shaderSource(obj,src);gl.compileShader(obj);
    if(!gl.getShaderParameter(obj,gl.COMPILE_STATUS)){
      const log=gl.getShaderInfoLog(obj);gl.deleteShader(obj);
      throw new Error('F3B shader: '+log);
    }
    return obj;
  }
  function create(gl) {
    if(!window.WKOfficeF3A?.readGLB)throw new Error('F3B requires F3A GLB validator');
    const vs=shader(gl,gl.VERTEX_SHADER,`attribute vec3 aPos,aNorm,aColor;
      uniform mat4 uVP;uniform vec3 uOffset;varying vec3 vCol;varying float vLight;
      void main(){gl_Position=uVP*vec4(aPos+uOffset,1.0);vCol=aColor;
      vLight=0.60+0.40*max(0.0,dot(normalize(aNorm),normalize(vec3(-0.35,0.90,0.4))));}`);
    const fs=shader(gl,gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 vCol;varying float vLight;
      void main(){gl_FragColor=vec4(vCol*vLight,1.0);}`);
    const program=gl.createProgram();
    if(!program)throw new Error('F3B: program allocation');
    gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('F3B: link failed');
    gl.deleteShader(vs);gl.deleteShader(fs);
    const attr=['aPos','aNorm','aColor'].map(k=>gl.getAttribLocation(program,k));
    if(attr.some(x=>x<0))throw new Error('F3B: shader attribute missing');
    const vpLoc=gl.getUniformLocation(program,'uVP'),offsetLoc=gl.getUniformLocation(program,'uOffset');
    const meshes=new Map();
    let ready=false,disposed=false;
    async function load(entries,origin) {
      if(disposed)throw new Error('F3B: disposed');
      const byKey=new Map();
      for(const entry of entries||[]){
        if(!entry||byKey.has(entry.key))continue;
        const safe=safeModelURL(entry.key,entry.url,origin);
        if(safe)byKey.set(entry.key,safe);
      }
      if(NAMES.some(n=>!byKey.has(n)))throw new Error('F3B: five allowlisted GLB models required');
      const loaded=await Promise.all(NAMES.map(async key=>{
        const response=await fetch(byKey.get(key),{credentials:'same-origin',mode:'same-origin'});
        if(!response.ok)throw new Error(`F3B: ${key} HTTP ${response.status}`);
        if(Number(response.headers.get('content-length')||0)>LIMIT)throw new Error('F3B: asset too large');
        const data=await response.arrayBuffer();
        const vertices=window.WKOfficeF3A.readGLB(data);
        return [key,vertices];
      }));
      if(disposed)throw new Error('F3B: disposed during load');
      try{
        for(const [key,vertices] of loaded){
          const buf=gl.createBuffer();if(!buf)throw new Error('F3B: GPU buffer');
          gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.bufferData(gl.ARRAY_BUFFER,vertices,gl.STATIC_DRAW);
          meshes.set(key,{buffer:buf,count:vertices.length/9});
        }
      }catch(error){for(const m of meshes.values())gl.deleteBuffer(m.buffer);meshes.clear();throw error;}
      ready=true;
    }
    function render(vp,agents) {
      if(!ready||disposed)return false;
      gl.useProgram(program);gl.uniformMatrix4fv(vpLoc,false,new Float32Array(vp));
      for(let i=0;i<Math.min(5,(agents||[]).length);i++){
        const key=variantFor(agents[i]?.public_id),mesh=meshes.get(key);
        if(!mesh)continue; // Never manufacture an agent when data is invalid.
        gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);
        for(let j=0;j<3;j++){
          gl.enableVertexAttribArray(attr[j]);
          gl.vertexAttribPointer(attr[j],3,gl.FLOAT,false,9*4,j*3*4);
        }
        gl.uniform3f(offsetLoc,XS[i],0,i%2===0?0.88:1.18);
        gl.drawArrays(gl.TRIANGLES,0,mesh.count);
      }
      return true;
    }
    function dispose(){
      if(disposed)return;disposed=true;ready=false;
      for(const m of meshes.values())gl.deleteBuffer(m.buffer);
      meshes.clear();gl.deleteProgram(program);
    }
    return {load,render,dispose,get ready(){return ready;}};
  }
  window.WKOfficeF3B=Object.freeze({NAMES,variantFor,safeModelURL,create});
})();

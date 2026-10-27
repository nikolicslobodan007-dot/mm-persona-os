/* WK-3D F3B.2 — portrait-anchored identity layer.
 * Faces come ONLY from the already authenticated Office V1.2 portrait proxy,
 * as returned for the same public_id by the agent register. No new API, storage,
 * CDN, analytics, exported portraits or biometric inference.
 * These are flat camera-facing portrait surfaces over separate 3D figures,
 * NOT identity-faithful sculpted heads. Reviewed 3D heads are a later gate.
 */
(() => {
  'use strict';
  const ID=/^P-[0-9]{5,20}$/;
  const XS=Object.freeze([-4.2,-2.1,0,2.1,4.2]);
  const MAX=5;
  const SIZE=256;
  function portraitURL(agent,origin) {
    if(!agent||!ID.test(agent.public_id)||typeof agent.portrait_url!=='string')return null;
    const expected=`/console/office/portraits/${agent.public_id}`;
    if(agent.portrait_url!==expected)return null;
    try {
      const root=new URL(origin);
      if(!['https:','http:'].includes(root.protocol))return null;
      const url=new URL(expected,root.href);
      return url.origin===root.origin?url.href:null;
    }catch(_){return null;}
  }
  function compile(gl,type,source) {
    const s=gl.createShader(type);if(!s)throw new Error('F3B2: shader allocation');
    gl.shaderSource(s,source);gl.compileShader(s);
    if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){
      const info=gl.getShaderInfoLog(s);gl.deleteShader(s);throw new Error('F3B2 shader: '+info);
    }
    return s;
  }
  function create(gl,notifier=()=>{}) {
    const vertex=compile(gl,gl.VERTEX_SHADER,`attribute vec2 aCorner;
      uniform mat4 uVP;uniform vec3 uCenter,uRight;uniform float uSize;
      varying vec2 vUV;
      void main(){vUV=aCorner*.5+.5;
        vec3 world=uCenter+uRight*aCorner.x*uSize*.5+vec3(0.,aCorner.y*uSize*.5,0.);
        gl_Position=uVP*vec4(world,1.);}`);
    const fragment=compile(gl,gl.FRAGMENT_SHADER,`precision mediump float;
      uniform sampler2D uPortrait;uniform float uSelected;varying vec2 vUV;
      void main(){float rad=length(vUV-.5);
        if(rad>.5) discard;
        vec3 border=mix(vec3(.72,.88,.97),vec3(1.,.67,.33),uSelected);
        vec3 color=rad>.445?border:texture2D(uPortrait,vUV).rgb;
        gl_FragColor=vec4(color,1.);}`);
    const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);
    gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('F3B2 program link');
    gl.deleteShader(vertex);gl.deleteShader(fragment);
    const attr=gl.getAttribLocation(program,'aCorner');
    if(attr<0)throw new Error('F3B2 attribute missing');
    const u={vp:gl.getUniformLocation(program,'uVP'),center:gl.getUniformLocation(program,'uCenter'),
      right:gl.getUniformLocation(program,'uRight'),size:gl.getUniformLocation(program,'uSize'),
      tex:gl.getUniformLocation(program,'uPortrait'),chosen:gl.getUniformLocation(program,'uSelected')};
    const geometry=gl.createBuffer();if(!geometry)throw new Error('F3B2 buffer allocation');
    gl.bindBuffer(gl.ARRAY_BUFFER,geometry);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
    const textures=new Map(),pending=new Map();
    let disposed=false;
    function discard(id) {
      const t=textures.get(id);if(t)gl.deleteTexture(t);textures.delete(id);
    }
    function upload(id,image) {
      if(disposed)return;
      const surface=document.createElement('canvas');surface.width=SIZE;surface.height=SIZE;
      const ctx=surface.getContext('2d',{willReadFrequently:false});if(!ctx)return;
      const w=image.naturalWidth||image.width,h=image.naturalHeight||image.height;
      if(!w||!h)return;
      // Crop only in memory, never save/send source portrait as an asset.
      const sq=Math.min(w,h),sx=(w-sq)/2,sy=(h-sq)/2;
      ctx.drawImage(image,sx,sy,sq,sq,0,0,SIZE,SIZE);
      const texture=gl.createTexture();if(!texture)return;
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
      try {gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,surface);}
      finally {gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);}
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      discard(id);textures.set(id,texture);
      notifier();
    }
    function loadImage(url) {
      return new Promise((resolve,reject)=>{
        const img=new Image();img.referrerPolicy='same-origin';img.decoding='async';
        img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('portrait unavailable'));
        img.src=url;
      });
    }
    function sync(agents,origin) {
      if(disposed)return;
      const wanted=new Map();
      for(const a of (agents||[]).slice(0,MAX)){
        const url=portraitURL(a,origin);
        if(url)wanted.set(a.public_id,url);
      }
      for(const id of textures.keys())if(!wanted.has(id))discard(id);
      for(const id of pending.keys())if(!wanted.has(id))pending.delete(id);
      for(const [id,url] of wanted) {
        if(textures.has(id)||pending.has(id))continue;
        const promise=loadImage(url).then(img=>{
          if(disposed||pending.get(id)!==promise)return;
          upload(id,img);
        }).catch(()=>{/* Keep 3D body and protected DOM portrait as fallback. */})
          .finally(()=>{if(pending.get(id)===promise)pending.delete(id);});
        pending.set(id,promise);
      }
    }
    function render(vp,agents,yaw,selectedId) {
      if(disposed||!textures.size)return 0;
      const items=(agents||[]).slice(0,MAX);
      gl.useProgram(program);gl.bindBuffer(gl.ARRAY_BUFFER,geometry);
      gl.enableVertexAttribArray(attr);gl.vertexAttribPointer(attr,2,gl.FLOAT,false,0,0);
      gl.uniformMatrix4fv(u.vp,false,new Float32Array(vp));
      // Same camera yaw as the existing 3D scene; portrait always faces viewer.
      gl.uniform3f(u.right,Math.cos(yaw),0,-Math.sin(yaw));
      gl.uniform1i(u.tex,0);gl.uniform1f(u.size,0.59);
      // Portrait is a face medallion anchored at head height, not a sculpted face.
      // Turn off depth writes to avoid corrupting future passes; preserve depth test.
      gl.depthMask(false);gl.disable(gl.DEPTH_TEST);
      let drawn=0;
      try {
        for(let i=0;i<items.length;i++) {
          const agent=items[i],tex=textures.get(agent?.public_id);
          if(!tex)continue;
          gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,tex);
          gl.uniform3f(u.center,XS[i]+Math.sin(yaw)*0.31,1.78,
            (i%2===0?0.88:1.18)+Math.cos(yaw)*0.31);
          gl.uniform1f(u.chosen,selectedId===agent.public_id?1:0);
          gl.drawArrays(gl.TRIANGLES,0,6);drawn++;
        }
      }finally{gl.depthMask(true);gl.enable(gl.DEPTH_TEST);}
      return drawn;
    }
    function dispose(){if(disposed)return;disposed=true;
      pending.clear();for(const id of [...textures.keys()])discard(id);
      gl.deleteBuffer(geometry);gl.deleteProgram(program);
    }
    return {sync,render,dispose,get count(){return textures.size;}};
  }
  window.WKOfficeF3B2=Object.freeze({portraitURL,create});
})();

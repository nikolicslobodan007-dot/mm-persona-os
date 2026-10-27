/* Web Korporacija 3D Office F1/F2 pilot. No external libraries, no writes.
 * Browser WebGL renderer. The V1.2 Office API is the sole source of agent data.
 * No arbitrary generated JS or 3DCodeVerse output is executed in this page.
 */
(() => {
  'use strict';
  const BASE = '/console/office/api/v1/';
  const MAX_LOADED = 100; // F1 bounded initial page. Later phase: server-filtered navigation.
  const SEATS = 5;
  const byId = id => document.getElementById(id);
  const ui = {
    canvas: byId('view3d'), scene: byId('scene'), labels: byId('labels'),
    department: byId('department'), list: byId('agentList'), inspector: byId('inspector'),
    info: byId('pageInfo'), prev: byId('prev'), next: byId('next'), notice: byId('notice')
  };
  const state = { agents: [], shown: [], page: 0, selected: '', details: null,
    department: '', yaw: -0.50, pitch: 0.67, radius: 17, dragging: null };
  const validId = id => typeof id === 'string' && /^P-[0-9]{5,20}$/.test(id);
  const label = (tag, cls, value) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  };
  function clear(node) { node.replaceChildren(); }
  function message(text) { ui.notice.textContent = text || ''; }
  function emptyInspector(text) {
    clear(ui.inspector);
    ui.inspector.appendChild(label('p','empty',text));
  }
  function clearSelection(text) {
    state.selected='';state.details=null;++selectionTicket;
    emptyInspector(text);
  }
  function cleanText(x, length = 150) { return String(x || '—').slice(0, length); }
  async function get(url) {
    const r = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!r.ok) {
      if (r.status === 401 || r.status === 403) throw new Error('Sesija je istekla ili nemate pristup. Vratite se na prijavu konzole.');
      throw new Error(`Office API: HTTP ${r.status}`);
    }
    return r.json();
  }
  // Column-major 4x4 math for GLSL. Camera/view and projection are physically 3D.
  function perspective(fov, aspect, near, far) {
    const f = 1 / Math.tan(fov / 2), z = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * z, -1, 0, 0, 2 * far * near * z, 0];
  }
  function sub(a, b) { return a.map((v, i) => v - b[i]); }
  function dot(a, b) { return a.reduce((s, v, i) => s + v * b[i], 0); }
  function cross(a, b) { return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]; }
  function unit(a) { const mag = Math.hypot(...a) || 1; return a.map(v => v / mag); }
  function lookAt(eye, target) {
    const z = unit(sub(eye, target)), x = unit(cross([0,1,0], z)), y = cross(z, x);
    return [x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1];
  }
  function multiply(a, b) {
    const out = Array(16).fill(0);
    for (let c=0;c<4;c++) for(let r=0;r<4;r++) for(let k=0;k<4;k++) out[c*4+r]+=a[k*4+r]*b[c*4+k];
    return out;
  }
  function project(v, m) {
    const x=v[0], y=v[1], z=v[2];
    const w=m[3]*x+m[7]*y+m[11]*z+m[15];
    if (w <= 0) return null;
    return [(m[0]*x+m[4]*y+m[8]*z+m[12])/w,(m[1]*x+m[5]*y+m[9]*z+m[13])/w];
  }
  function unitCube() {
    const faces = [
      [[0,0,1],[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]]],
      [[0,0,-1],[[1,-1,-1],[-1,-1,-1],[-1,1,-1],[1,1,-1]]],
      [[1,0,0],[[1,-1,1],[1,-1,-1],[1,1,-1],[1,1,1]]],
      [[-1,0,0],[[-1,-1,-1],[-1,-1,1],[-1,1,1],[-1,1,-1]]],
      [[0,1,0],[[-1,1,1],[1,1,1],[1,1,-1],[-1,1,-1]]],
      [[0,-1,0],[[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1]]]
    ];
    const out=[];
    faces.forEach(([norm,verts])=>[0,1,2,0,2,3].forEach(i=>{
      out.push(...verts[i].map(a=>a*0.5),...norm);
    }));
    return new Float32Array(out);
  }
  const VERT = `attribute vec3 aPosition; attribute vec3 aNormal;
    uniform mat4 uVP; uniform vec3 uTranslate; uniform vec3 uScale;
    varying float vLight;
    void main() { gl_Position = uVP * vec4(aPosition * uScale + uTranslate, 1.0);
      vLight = 0.66 + 0.34 * max(0.0, dot(normalize(aNormal), normalize(vec3(-0.4,1.0,0.55)))); }`;
  const FRAG = `precision mediump float; uniform vec3 uColor; varying float vLight;
    void main() { gl_FragColor = vec4(uColor * vLight, 1.0); }`;
  function shader(gl, type, text) {
    const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);
    if (!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw new Error('3D shader: '+gl.getShaderInfoLog(s));
    return s;
  }
  function drawOffice(cube) {
    // Low-poly procedural office geometry; deterministic and shared by WebGL / fallback.
    cube([0,-0.16,0],[12,0.24,9],'#263c52');
    cube([0,1.65,-4.48],[12,3.45,0.12],'#1e354d');
    cube([-5.95,1.65,0],[0.12,3.45,9],'#1a344c');
    cube([0,0.02,3.95],[11.4,0.04,0.24],'#455d70');
    cube([0,2.6,-4.38],[4.8,0.10,0.11],'#e6a35d');
    cube([0,2.0,-4.37],[4.8,1.10,0.09],'#2d6480');
    cube([0,1.38,-4.29],[4.8,0.08,0.10],'#ed9b59');
    cube([5.4,0.04,-2.85],[0.58,0.1,0.7],'#395d51');
    const xs=[-4.2,-2.1,0,2.1,4.2];
    state.shown.forEach((a,i)=>{
      const x=xs[i],z=i%2===0?0.0:0.30;
      cube([x,0.75,z],[1.65,0.10,1.0],'#bb926c');
      cube([x-0.70,0.38,z-0.38],[0.10,0.73,0.10],'#75899d');
      cube([x+0.70,0.38,z-0.38],[0.10,0.73,0.10],'#75899d');
      cube([x,1.12,z-0.2],[0.72,0.48,0.08],'#0a1525');
      cube([x,1.12,z-0.14],[0.59,0.34,0.025],'#287ca0');
      cube([x,0.87,z-0.21],[0.08,0.11,0.09],'#75899d');
      cube([x,0.28,z+1.1],[0.92,0.12,0.78],'#425b76');
      cube([x,0.86,z+1.40],[0.92,1.12,0.12],'#334b67');
      const status=String(a.status||'').toUpperCase();
      const color=status==='ACTIVE'?'#53dfc4':status==='READY'?'#7ab9ed':status==='PAUSED'?'#e6ac61':'#97a9bd';
      cube([x,0.84,z+0.86],[0.38,0.70,0.34],a.public_id===state.selected?'#ef9a52':color);
      cube([x,1.38,z+0.86],[0.36,0.36,0.36],'#d3b8a0');
    });
  }
  function createRenderer(canvas) {
    const gl=canvas.getContext('webgl',{antialias:true,alpha:false,depth:true});
    if (!gl) throw new Error('WebGL nije dostupan u ovom pregledaču. Lista agenata ostaje dostupna.');
    const program=gl.createProgram();gl.attachShader(program,shader(gl,gl.VERTEX_SHADER,VERT));
    gl.attachShader(program,shader(gl,gl.FRAGMENT_SHADER,FRAG));gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error('Povezivanje WebGL programa nije uspelo');
    gl.useProgram(program);
    const vert=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vert);
    gl.bufferData(gl.ARRAY_BUFFER,unitCube(),gl.STATIC_DRAW);
    const stride=6*Float32Array.BYTES_PER_ELEMENT;
    const aPosition=gl.getAttribLocation(program,'aPosition'), aNormal=gl.getAttribLocation(program,'aNormal');
    gl.enableVertexAttribArray(aPosition);gl.vertexAttribPointer(aPosition,3,gl.FLOAT,false,stride,0);
    gl.enableVertexAttribArray(aNormal);gl.vertexAttribPointer(aNormal,3,gl.FLOAT,false,stride,3*4);
    const uniforms={vp:gl.getUniformLocation(program,'uVP'),at:gl.getUniformLocation(program,'uTranslate'),
      scale:gl.getUniformLocation(program,'uScale'),color:gl.getUniformLocation(program,'uColor')};
    gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
    const rgb = hex => { const n=parseInt(hex.replace('#',''),16);return [(n>>16&255)/255,(n>>8&255)/255,(n&255)/255]; };
    function cube(pos,size,color) {
      gl.uniform3fv(uniforms.at,pos);gl.uniform3fv(uniforms.scale,size);
      gl.uniform3fv(uniforms.color,rgb(color));gl.drawArrays(gl.TRIANGLES,0,36);
    }
    function render(vp) {
      const rect=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,1.5);
      const width=Math.max(1,Math.floor(rect.width*dpr)),height=Math.max(1,Math.floor(rect.height*dpr));
      if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
      gl.viewport(0,0,width,height);gl.clearColor(0.055,0.101,0.16,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      gl.uniformMatrix4fv(uniforms.vp,false,new Float32Array(vp));
      drawOffice(cube);
    }
    return {render};
  }
  // Accessible 2D projection fallback when WebGL is disabled by browser or policy.
  function createFallback(canvas) {
    let ctx=canvas.getContext('2d');
    // If a WebGL context was acquired but its shader failed, the same canvas
    // cannot allocate a 2D context. Replace it before installing fallback.
    if(!ctx) {
      const replacement=document.createElement('canvas');
      replacement.id=canvas.id;replacement.setAttribute('aria-hidden','true');
      canvas.replaceWith(replacement);ui.canvas=replacement;canvas=replacement;
      ctx=canvas.getContext('2d');
    }
    if(!ctx) return null;
    const faces=[
      [[0,1,2,3],0.62],[[4,5,6,7],0.85],[[0,4,7,3],0.68],
      [[1,5,6,2],0.74],[[3,2,6,7],1.00],[[0,1,5,4],0.56]
    ];
    return {render(vp) {
      const rect=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,1.5);
      canvas.width=Math.max(1,Math.floor(rect.width*dpr));canvas.height=Math.max(1,Math.floor(rect.height*dpr));
      ctx.clearRect(0,0,canvas.width,canvas.height);
      const polygons=[];
      function cube(pos,size,hex) {
        const [x,y,z]=pos,[a,b,c]=size.map(s=>s/2);
        const v=[[x-a,y-b,z-c],[x+a,y-b,z-c],[x+a,y-b,z+c],[x-a,y-b,z+c],
          [x-a,y+b,z-c],[x+a,y+b,z-c],[x+a,y+b,z+c],[x-a,y+b,z+c]];
        faces.forEach(([inds,shade])=>{
          const pts=inds.map(i=>project(v[i],vp));if(pts.some(p=>!p))return;
          const depth=inds.reduce((t,i)=>t+(vp[3]*v[i][0]+vp[7]*v[i][1]+vp[11]*v[i][2]+vp[15]),0)/4;
          polygons.push({pts,depth,hex,shade});
        });
      }
      drawOffice(cube);
      polygons.sort((a,b)=>b.depth-a.depth);
      for(const f of polygons) {
        const n=parseInt(f.hex.slice(1),16);
        const rgb=[n>>16&255,n>>8&255,n&255].map(v=>Math.round(v*f.shade));
        ctx.fillStyle=`rgb(${rgb.join(',')})`;ctx.strokeStyle='#2e4150';ctx.lineWidth=0.4*dpr;
        ctx.beginPath();f.pts.forEach(([x,y],i)=>{
          const px=(x+1)*canvas.width/2,py=(1-y)*canvas.height/2;
          if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
        });ctx.closePath();ctx.fill();ctx.stroke();
      }
    }};
  }
  let renderer=null;
  let fallbackInfo='';
  try {renderer=createRenderer(ui.canvas);}
  catch(e) {renderer=createFallback(ui.canvas);fallbackInfo=e.message + ' Prikazana je 2D projekcija prostora.';message(fallbackInfo);}
  let frame=0;
  function redraw() {
    if(frame)cancelAnimationFrame(frame);
    frame=requestAnimationFrame(()=>{
      frame=0;
      const eye=[state.radius*Math.cos(state.pitch)*Math.sin(state.yaw),
        1+state.radius*Math.sin(state.pitch),state.radius*Math.cos(state.pitch)*Math.cos(state.yaw)];
      const bounds=ui.scene.getBoundingClientRect();
      const vp=multiply(perspective(Math.PI*47/180,Math.max(bounds.width,1)/Math.max(bounds.height,1),0.1,100),lookAt(eye,[0,0.75,0]));
      if(renderer)renderer.render(vp);
      const xs=[-4.2,-2.1,0,2.1,4.2];
      [...ui.labels.children].forEach((btn,i)=>{
        const z=i%2===0?0.0:0.30;
        const xy=project([xs[i],1.9,z+0.85],vp);
        btn.hidden=!xy||Math.abs(xy[0])>0.92||Math.abs(xy[1])>0.96;
        if(xy){btn.style.left=`${(xy[0]+1)*50}%`;btn.style.top=`${(1-xy[1])*50}%`;}
      });
    });
  }
  function updateFilters() {
    const dep=ui.department.value;
    state.department=dep;state.page=0;
    clearSelection('Izaberite agenta iz prikazanog odeljenja.');
    updateSeats();
  }
  function updateDepartmentOptions() {
    const seen=new Map();
    state.agents.forEach(a=>{
      const code=String(a.department?.code||'__none__');
      seen.set(code,String(a.department?.name||'Bez odeljenja'));
    });
    clear(ui.department);
    const all=label('option','',`Sva odeljenja (${state.agents.length} učitanih)`);all.value='';ui.department.appendChild(all);
    [...seen].sort((a,b)=>a[1].localeCompare(b[1],'sr')).forEach(([code,name])=>{
      const opt=label('option','',name);opt.value=code;ui.department.appendChild(opt);
    });
    if(seen.has(state.department))ui.department.value=state.department;else state.department='';
  }
  function seats() {
    const filtered=state.department?state.agents.filter(a=>String(a.department?.code||'__none__')===state.department):state.agents;
    const maxPage=Math.max(0,Math.ceil(filtered.length/SEATS)-1);
    state.page=Math.max(0,Math.min(maxPage,state.page));
    state.shown=filtered.slice(state.page*SEATS,state.page*SEATS+SEATS);
    ui.info.textContent=filtered.length?`${state.page*SEATS+1}–${Math.min(filtered.length,(state.page+1)*SEATS)} / ${filtered.length}`:'Nema agenata';
    ui.prev.disabled=state.page<=0;ui.next.disabled=state.page>=maxPage;
  }
  function updateSeats() {
    seats();clear(ui.list);clear(ui.labels);
    if(!state.shown.length)ui.list.appendChild(label('p','empty','Nema agenata u izabranom odeljenju.'));
    state.shown.forEach(a=>{
      const item=label('button','agent-row');item.type='button';
      if(a.public_id===state.selected)item.classList.add('selected');
      const dot=label('span','dot '+String(a.status||'').toLowerCase());dot.setAttribute('aria-hidden','true');
      const copy=label('div');copy.appendChild(label('strong','',cleanText(a.display_name)));
      copy.appendChild(label('small','',`${a.public_id} · ${cleanText(a.status,30)}`));
      item.append(dot,copy);item.addEventListener('click',()=>select(a.public_id));ui.list.appendChild(item);
      const sign=label('button','agent-label',cleanText(a.display_name,50));sign.type='button';
      sign.setAttribute('aria-label',`Otvori profil ${cleanText(a.display_name,50)}`);
      if(a.public_id===state.selected)sign.classList.add('selected');
      sign.addEventListener('click',()=>select(a.public_id));ui.labels.appendChild(sign);
    });
    redraw();
  }
  function detailRow(dl,name,value) {dl.append(label('dt','',name),label('dd','',cleanText(value)));}
  let selectionTicket=0;
  async function select(id) {
    if(!validId(id))return;
    const ticket=++selectionTicket;
    state.selected=id;state.details=null;
    updateSeats();clear(ui.inspector);ui.inspector.appendChild(label('p','empty','Učitavanje profila…'));
    try {
      const a=await get(BASE+'agents/'+encodeURIComponent(id));
      if(ticket!==selectionTicket || id!==state.selected)return;
      state.details=a;clear(ui.inspector);
      const head=label('div','person');
      const proxy='/console/office/portraits/'+id;
      if(a.portrait_url === proxy && validId(id)) {
        const img=label('img','portrait');img.src=proxy;
        img.alt=`Portret: ${cleanText(a.display_name,60)}`;
        img.onerror=()=>{img.replaceWith(label('div','portrait placeholder-portrait',(a.display_name||'?').slice(0,1)));};head.appendChild(img);
      } else head.appendChild(label('div','portrait placeholder-portrait',(a.display_name||'?').slice(0,1)));
      const name=label('div');name.append(label('strong','',cleanText(a.display_name)),label('small','',id));head.appendChild(name);ui.inspector.appendChild(head);
      const tags=label('div','tags');[a.status,a.runtime_environment,a.trust_level].forEach(v=>tags.appendChild(label('span','',cleanText(v,40))));ui.inspector.appendChild(tags);
      const dl=label('dl','details');detailRow(dl,'Odeljenje',a.department?.name);
      detailRow(dl,'Radno mesto',a.position?.title);detailRow(dl,'Aktivan plan',a.active_plan?.public_id);
      detailRow(dl,'Plan status',a.active_plan?.status);detailRow(dl,'Aktivni korak',a.active_step?.step_type);
      ui.inspector.appendChild(dl);
      ui.inspector.appendChild(label('p','empty','Status, režim i izvođenje zadataka su odvojeni. Ova strana ne izdaje naredbe agentima.'));
    } catch(e) { if(ticket===selectionTicket){clear(ui.inspector);ui.inspector.appendChild(label('p','empty',e.message));} }
  }
  async function reload() {
    message('Učitavanje iz zaštićenog Office API-ja…');
    try {
      const [summary,data]=await Promise.all([get(BASE+'summary'),get(BASE+`agents?limit=${MAX_LOADED}`)]);
      byId('countAgents').textContent=String(summary.agents.total);
      byId('countPlans').textContent=String(summary.plans.active);
      byId('countApprovals').textContent=String(summary.approvals.pending);
      if(!Array.isArray(data.items))throw new Error('Office API nije vratio validan registar agenata.');
      state.agents=data.items.filter(a=>validId(a.public_id));
      state.page=0;clearSelection('Izaberite agenta za pregled njegovog statusa.');
      updateDepartmentOptions();updateSeats();
      message((data.next_cursor ? 'Pilot trenutno prikazuje prvih 100 agenata. Za pretragu ostalih koristite postojeću kancelariju.' : 'Podaci su učitani iz Persona OS-a.') + (fallbackInfo ? ' ' + fallbackInfo : ''));
    } catch(e) {
      state.agents=[];state.page=0;state.department='';
      ['countAgents','countPlans','countApprovals'].forEach(id=>{byId(id).textContent='—';});
      clearSelection('Podaci nisu dostupni. Ponovo proverite prijavu i osvežite stranicu.');
      updateDepartmentOptions();updateSeats();message(e.message);
    }
  }
  ui.department.addEventListener('change',updateFilters);
  ui.prev.addEventListener('click',()=>{state.page--;clearSelection('Izaberite agenta sa trenutne strane.');updateSeats();});
  ui.next.addEventListener('click',()=>{state.page++;clearSelection('Izaberite agenta sa trenutne strane.');updateSeats();});
  byId('reload').addEventListener('click',reload);
  byId('rotateLeft').addEventListener('click',()=>{state.yaw-=0.18;redraw();});
  byId('rotateRight').addEventListener('click',()=>{state.yaw+=0.18;redraw();});
  byId('zoomIn').addEventListener('click',()=>{state.radius=Math.max(10,state.radius-1.6);redraw();});
  byId('zoomOut').addEventListener('click',()=>{state.radius=Math.min(28,state.radius+1.6);redraw();});
  byId('reset').addEventListener('click',()=>{state.yaw=-0.5;state.pitch=0.67;state.radius=17;redraw();});
  ui.canvas.addEventListener('pointerdown',e=>{ui.canvas.setPointerCapture(e.pointerId);state.dragging={x:e.clientX,y:e.clientY};});
  ui.canvas.addEventListener('pointermove',e=>{
    if(!state.dragging)return;
    const dx=e.clientX-state.dragging.x,dy=e.clientY-state.dragging.y;
    state.yaw+=dx*0.007;state.pitch=Math.max(0.23,Math.min(1.32,state.pitch+dy*0.007));
    state.dragging={x:e.clientX,y:e.clientY};redraw();
  });
  ['pointerup','pointercancel','lostpointercapture'].forEach(event=>ui.canvas.addEventListener(event,()=>{state.dragging=null;}));
  ui.scene.addEventListener('wheel',e=>{if(!renderer)return;e.preventDefault();state.radius=Math.max(10,Math.min(28,state.radius+Math.sign(e.deltaY)*1.1));redraw();},{passive:false});
  window.addEventListener('resize',redraw);
  reload();
})();

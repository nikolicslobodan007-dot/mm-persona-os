/* Web Korporacija Virtual Office V1.4A — read-only navigation shell.
 * The V1.2 API contract is unchanged; no task execution or business writes.
 * Uses textContent/createElement for untrusted content; portrait URLs are reconstructed from public_id.
 */
(() => {
  "use strict";
  const BASE = "/console/office/api/v1/";
  const $ = id => document.getElementById(id);
  const ui = {
    campus: $("departments"), agentList: $("agentList"), inspector: $("inspector"),
    events: $("events"), notice: $("notice"), filter: $("filter"),
    state: $("stateFilter"), department: $("departmentFilter"),
    zoomLabel: $("zoomLabel")
  };
  let agents = [], selected = "", focusDepartment = "", zoom = 1, inspectorOpen = true;
  let currentSelectionRequest = 0;
  let confirmedRunning = new Set();
  let summary = null;

  const el = (tag, className, txt) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (txt !== undefined && txt !== null) node.textContent = String(txt);
    return node;
  };
  const add = (parent, ...children) => { parent.append(...children); return parent; };
  const validId = id => typeof id === "string" && /^P-[0-9]{5,20}$/.test(id);
  const initial = name => (name || "?").trim().charAt(0).toLocaleUpperCase("sr");
  const normalized = value => String(value || "").toLocaleLowerCase("sr").trim();
  const label = (text, className = "") => el("span", className, text);
  const runtimeClass = v => v === "LIVE" ? "live" : "";
  const stateClass = v => (v === "READY" || v === "ACTIVE") ? "ready" :
    (["PAUSED", "SUSPENDED", "DEGRADED"].includes(v) ? "attention" : "");
  const ax = (text, type = "") => label(text, "axis " + type);
  function note(s) { ui.notice.textContent = s; ui.notice.hidden = !s; }
  function portraitUrl(agent) {
    const expected = "/console/office/portraits/" + agent.public_id;
    return validId(agent.public_id) && agent.portrait_url === expected ? expected : null;
  }
  function imageFor(agent) {
    const url = portraitUrl(agent);
    if (!url) return null;
    const img = el("img"); img.src = url; img.alt = ""; img.loading = "lazy";
    img.referrerPolicy = "same-origin"; img.addEventListener("error", () => img.remove());
    return img;
  }
  function avatar(agent, cls="wk-face") {
    const node = el("span", cls, initial(agent.display_name));
    const img = imageFor(agent); if (img) node.appendChild(img);
    return node;
  }
  function shownAgents() {
    const search = normalized(ui.filter.value), state = ui.state.value;
    const department = ui.department.value;
    return agents.filter(a => (!state || a.status === state) &&
      (!department || (a.department?.code || "UNASSIGNED") === department) &&
      (!search || [a.display_name, a.public_id, a.department?.name, a.position?.title]
        .some(text => normalized(text).includes(search))));
  }
  function refreshDepartments() {
    const selectedValue = ui.department.value;
    const departments = new Map();
    agents.forEach(a => {
      const code = a.department?.code || "UNASSIGNED";
      departments.set(code, a.department?.name || "Bez odeljenja");
    });
    ui.department.replaceChildren(el("option", "", "Sva odeljenja"));
    ui.department.firstElementChild.value = "";
    [...departments.entries()].sort((a,b)=>a[1].localeCompare(b[1],"sr")).forEach(([code,name]) => {
      const opt = el("option", "", name); opt.value = code; ui.department.appendChild(opt);
    });
    ui.department.value = departments.has(selectedValue) ? selectedValue : "";
  }
  function renderList() {
    ui.agentList.replaceChildren();
    const visible = shownAgents(); $("listCount").textContent = String(visible.length);
    if (!visible.length) { ui.agentList.appendChild(el("p", "wk-no-results", "Nema agenata za zadate filtere.")); return; }
    visible.forEach(a => {
      const b = el("button", "wk-agent-row" + (selected === a.public_id ? " chosen" : ""));
      b.type = "button"; b.setAttribute("aria-label", "Izaberi " + a.display_name);
      if (selected === a.public_id) b.setAttribute("aria-pressed", "true");
      const info = el("span", "wk-agent-info");
      add(info, el("strong", "", a.display_name), el("small", "", a.position?.title || a.department?.name || "Bez radnog mesta"),
          label(a.runtime_environment || "—", "wk-agent-runtime"));
      add(b, avatar(a), info, ax(a.status || "—", stateClass(a.status)));
      b.addEventListener("click", () => selectAgent(a.public_id));
      ui.agentList.appendChild(b);
    });
  }
  function uniform(id) {
    let sum = 0; for (const char of String(id)) sum += char.charCodeAt(0);
    return "uniform-" + (sum % 5);
  }
  function figure(a) {
    const head = el("span", "figure-head");head.appendChild(label(initial(a.display_name)));
    const img = imageFor(a); if (img) head.appendChild(img);
    return add(el("span", "figurine " + uniform(a.public_id)),
      el("span", "figure-shadow"),el("span", "figure-leg l"), el("span", "figure-leg r"),
      el("span", "figure-arm l"), el("span", "figure-arm r"),el("span", "figure-body"),
      el("span", "figure-neck"),head);
  }
  function spot(a) {
    const running = confirmedRunning.has(a.public_id);
    const b = el("button", "workspot" + (selected === a.public_id ? " selected" : "") + (running ? " is-running" : ""));
    b.type = "button";
    b.setAttribute("aria-label", "Otvori agenta " + a.display_name + ", " + a.status + ", " + a.runtime_environment);
    if (selected === a.public_id) b.setAttribute("aria-pressed", "true");
    const desk = add(el("span", "desk-set"),el("span", "desk-top"),el("span", "screen"));
    const badges = add(el("span", "agent-axes"),ax(a.status,stateClass(a.status)),ax(a.runtime_environment,runtimeClass(a.runtime_environment)));
    add(b, el("span", "activity-indicator", "RUNNING"), desk, figure(a),
      label(a.display_name, "workspot-name"), label(a.public_id, "workspot-id"), badges);
    b.addEventListener("click", () => selectAgent(a.public_id));
    return b;
  }
  function renderCampus() {
    ui.campus.replaceChildren();
    const filtered = shownAgents();
    const groups = new Map();
    filtered.forEach(a => {
      const code = a.department?.code || "UNASSIGNED";
      if (focusDepartment && focusDepartment !== code) return;
      if (!groups.has(code)) groups.set(code, {name:a.department?.name || "Bez odeljenja", people:[]});
      groups.get(code).people.push(a);
    });
    $("sectionSub").textContent = focusDepartment ? "Uvećani pogled na izabrano odeljenje." : "Odeljenja i radna mesta iz postojeće organizacije.";
    if (!groups.size) {ui.campus.appendChild(el("div", "empty-results", "Nema rezultata u izabranom odeljenju ili filteru."));return;}
    [...groups.entries()].sort((a,b) => a[1].name.localeCompare(b[1].name, "sr")).forEach(([code,group])=>{
      const room = el("article", "office-room");
      const id = add(el("div"),label(group.name,"room-name"),label("  "+code+" · "+group.people.length,"room-caption"));
      const toggle = el("button", "room-focus", focusDepartment ? "← Sve kancelarije" : "Uđi u odeljenje ↗");
      toggle.type="button";toggle.addEventListener("click", ()=> {focusDepartment = focusDepartment ? "" : code;renderCampus();});
      const header=add(el("div", "room-header"),id,toggle);
      const people = el("div", "room-people" + (group.people.length>=6 ? " large-room":""));
      group.people.forEach(a=>people.appendChild(spot(a)));
      const stage = add(el("div", "room-stage"),el("span", "room-wall"),el("span", "room-floor"),label("🪴","room-plants"),people);
      room.append(header,stage);ui.campus.appendChild(room);
    });
    ui.campus.className = "office-campus zoom-" + zoom + (focusDepartment ? " focused" : "");
    ui.zoomLabel.textContent = ["85%","100%","115%"][zoom];
    // Read-only bridge for a progressively enhanced Pixi scene. The scene is
    // derived from the exact same filtered data as the accessible DOM view.
    // Never infer RUNNING from status=READY/ACTIVE.
    window.dispatchEvent(new CustomEvent("wk:campus-state", {detail: {
      agents: filtered.map(a => ({
        public_id: a.public_id, display_name: a.display_name,
        status: a.status, runtime_environment: a.runtime_environment,
        department: a.department ? {code: a.department.code, name: a.department.name} : null
      })),
      selected, focusDepartment, zoom, confirmedRunning: [...confirmedRunning]
    }}));
  }
  function renderSelection() { renderList(); renderCampus(); }
  function detailRow(labelText,value) {
    return add(el("div","wk-dl-row"),el("dt","",labelText),el("dd","",value ?? "—"));
  }
  function inspector(details) {
    ui.inspector.replaceChildren();
    const head = el("div","wk-inspect-head");
    const identity = add(el("div","wk-inspect-identity"), el("h3","",details.display_name),
      el("p","",details.public_id + " · " + (details.position?.title || "Bez radnog mesta")));
    add(head,avatar(details,"wk-inspect-photo"),identity);
    const tags = add(el("div","wk-inspect-tags"),ax(details.status,stateClass(details.status)),
      ax(details.runtime_environment,runtimeClass(details.runtime_environment)),ax(details.trust_level));
    const facts = el("dl","wk-facts");
    [
      ["Odeljenje", details.department?.name], ["Radno mesto",details.position?.title],
      ["Zanimanje",details.occupation?.title], ["Aktivan plan",details.active_plan?.public_id],
      ["Status plana",details.active_plan?.status], ["Aktivni korak",details.active_step?.step_type]
    ].forEach(([k,v])=>facts.appendChild(detailRow(k,v)));
    const confirmed = details.active_plan?.status === "ACTIVE" && details.active_step?.status === "RUNNING";
    const explanation = el("p","wk-interpretation",confirmed ?
      "Potvrđen aktivni korak RUNNING. Signal važi samo do sledećeg osvežavanja." :
      "Nema potvrđenog izvršavanja. READY / ACTIVE nisu dokaz da agent trenutno radi.");
    const link=el("a","wk-profile-link","Otvori postojeći Django profil ↗");
    link.href="/console/personas/"+encodeURIComponent(details.public_id);
    ui.inspector.append(head,tags,el("h4","","Operativni podaci"),facts,explanation,link);
  }
  function formatDate(date) {
    const parsed=new Date(date); if(Number.isNaN(parsed.valueOf()))return "—";
    return new Intl.DateTimeFormat("sr-RS",{dateStyle:"short",timeStyle:"short",timeZone:"Europe/Belgrade"}).format(parsed);
  }
  async function request(path) {
    const response=await fetch(path,{credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
    if(response.status===401)throw new Error("Sesija je istekla. Prijavi se ponovo u Django konzolu.");
    if(response.status===403)throw new Error("Pristup odbijen: nalog nema odgovarajuću ulogu.");
    if(!response.ok)throw new Error("Podaci trenutno nisu dostupni (HTTP "+response.status+").");
    return response.json();
  }
  async function loadAgents() {
    const list=[];let cursor=null;let pages=0;
    do {
      const page=await request(BASE+"agents?limit=100"+(cursor?"&cursor="+encodeURIComponent(cursor):""));
      if(!Array.isArray(page.items))throw new Error("Neispravan odgovor registra agenata.");
      list.push(...page.items);cursor=page.next_cursor || null;
      if(++pages>200 || list.length>10000)throw new Error("Previše podataka za prikaz; primeni filter.");
    } while(cursor);
    agents=list.filter(a=>validId(a.public_id));
    refreshDepartments();renderSelection();
    if(selected&&!agents.some(a=>a.public_id===selected)){
      selected="";confirmedRunning.clear();ui.inspector.replaceChildren(el("p","wk-muted","Izabrani agent više nije u registru."));
    }
  }
  async function loadSummary() {
    summary=await request(BASE+"summary");
    const d=summary;
    [["total",d.agents?.total],["miniAgents",d.agents?.total],["plans",d.plans?.active],["miniPlans",d.plans?.active],
      ["approvals",d.approvals?.pending],["miniApprovals",d.approvals?.pending]].forEach(([key,value])=>$(key).textContent=String(value??"—"));
  }
  async function loadEvents() {
    try {
      const data=await request(BASE+"events?limit=20");
      ui.events.replaceChildren();
      if(!data.items?.length){ui.events.appendChild(el("p","wk-muted","Nema dozvoljenih događaja."));return;}
      data.items.forEach(item=>{
        const node=el("article","wk-event");
        add(node,el("time","",formatDate(item.occurred_at)),el("strong","",item.event_key),
          el("small","",(item.persona_public_id||"—")+" · "+item.severity));
        ui.events.appendChild(node);
      });
    }catch(e){ui.events.replaceChildren(el("p","wk-muted",e.message));}
  }
  async function selectAgent(id) {
    if(!validId(id))return;
    selected=id;const token=++currentSelectionRequest;
    confirmedRunning.delete(id);renderSelection();
    ui.inspector.replaceChildren(el("p","wk-muted","Učitavanje profila…"));
    try {
      const data=await request(BASE+"agents/"+encodeURIComponent(id));
      if(token!==currentSelectionRequest)return;
      if(data.active_plan?.status==="ACTIVE"&&data.active_step?.status==="RUNNING")confirmedRunning.add(id);
      inspector(data);renderSelection();
      const url=new URL(window.location.href);url.searchParams.set("agent",id);
      if(window.location.pathname === "/console/office" && window.history?.replaceState)window.history.replaceState(null,"",url.pathname+url.search);
      closeMobileAgents();
    }catch(e){if(token===currentSelectionRequest)ui.inspector.replaceChildren(el("p","wk-muted",e.message));}
  }
  async function refresh() {
    note("Učitavanje podataka iz Django sistema…");confirmedRunning.clear();
    try {
      await Promise.all([loadAgents(),loadSummary(),loadEvents()]);note("");
      if(selected&&agents.some(a=>a.public_id===selected))await selectAgent(selected);
    } catch(e){note(e.message);}
  }
  function onFiltersChanged() {
    focusDepartment="";renderSelection();
  }
  function closeMobileAgents() {
    $("agentPanel").classList.remove("mobile-open");$("toggleAgents").setAttribute("aria-expanded","false");
  }
  $("refresh").addEventListener("click",refresh);
  $("reloadEvents").addEventListener("click",loadEvents);
  $("showAll").addEventListener("click",()=>{focusDepartment="";ui.filter.value="";ui.state.value="";ui.department.value="";renderSelection();});
  ui.filter.addEventListener("input",onFiltersChanged);
  ui.state.addEventListener("change",onFiltersChanged);
  ui.department.addEventListener("change",onFiltersChanged);
  $("zoomOut").addEventListener("click",()=>{zoom=Math.max(0,zoom-1);renderCampus();});
  $("zoomIn").addEventListener("click",()=>{zoom=Math.min(2,zoom+1);renderCampus();});
  $("toggleAgents").addEventListener("click",()=>{
    const open=$("agentPanel").classList.toggle("mobile-open");$("toggleAgents").setAttribute("aria-expanded",String(open));
  });
  $("closeAgents").addEventListener("click",closeMobileAgents);
  $("collapseInspector").addEventListener("click",()=>{
    inspectorOpen=!inspectorOpen;$("inspector").hidden=!inspectorOpen;
    $("collapseInspector").setAttribute("aria-expanded",String(inspectorOpen));
  });
  const fromQuery=new URLSearchParams(window.location.search).get("agent");
  if(validId(fromQuery))selected=fromQuery;
  document.addEventListener("visibilitychange",()=>{
    // Never leave a stale RUNNING animation visible while the tab is hidden.
    if(document.visibilityState==="hidden"){confirmedRunning.clear();renderCampus();}
    else refresh();
  });
  // Existing V1.2 read-only API is polled; no new websocket/command endpoint.
  window.setInterval(()=>{if(document.visibilityState==="visible")refresh();},60*1000);
  // Scene->DOM interaction remains in the existing navigation controller.
  window.addEventListener("wk:scene-request", () => renderCampus());
  window.addEventListener("wk:scene-agent-select", e => {
    const id = e.detail?.public_id;
    if (validId(id) && agents.some(a => a.public_id === id)) selectAgent(id);
  });
  window.addEventListener("wk:scene-department-focus", e => {
    const code = e.detail?.code;
    if (typeof code === "string" && agents.some(a => (a.department?.code || "UNASSIGNED") === code)) {
      focusDepartment = focusDepartment === code ? "" : code;
      renderCampus();
    }
  });
  refresh();
})();

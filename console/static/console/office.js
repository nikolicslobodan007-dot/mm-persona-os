/* Virtual Office V1.2: read-only, same-origin, no inline scripts or HTML injection. */
(function () {
  "use strict";
  const base = "/console/office/api/v1/";
  const els = {
    total: document.getElementById("total"),
    plans: document.getElementById("plans"),
    approvals: document.getElementById("approvals"),
    departments: document.getElementById("departments"),
    inspector: document.getElementById("inspector"),
    events: document.getElementById("events"),
    notice: document.getElementById("notice"),
    filter: document.getElementById("filter")
  };
  let agents = [];
  let selected = "";
  const mk = (tag, className, label) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (label !== undefined) el.textContent = label;
    return el;
  };
  const text = (id, value) => { els[id].textContent = String(value); };
  function notice(msg) { els.notice.textContent = msg; els.notice.hidden = !msg; }
  async function get(path) {
    const resp = await fetch(path, { credentials: "same-origin", cache: "no-store" });
    if (resp.status === 401) throw new Error("Sesija je istekla. Prijavi se ponovo u konzolu.");
    if (!resp.ok) throw new Error("Podaci nisu dostupni (HTTP " + resp.status + ").");
    return resp.json();
  }
  function portrait(parent, agent) {
    const box = mk("span", "avatar", (agent.display_name || "?").charAt(0));
    if (agent.portrait_url) {
      const img = document.createElement("img");
      img.src = agent.portrait_url;
      img.alt = "";
      img.addEventListener("error", () => img.remove());
      box.appendChild(img);
    }
    parent.appendChild(box);
  }
  function renderRooms() {
    els.departments.replaceChildren();
    const q = els.filter.value.toLocaleLowerCase("sr").trim();
    const filtered = agents.filter(a => (a.display_name + " " + a.public_id).toLocaleLowerCase("sr").includes(q));
    const groups = new Map();
    filtered.forEach(a => {
      const id = a.department?.code || "NEASSIGNED";
      const label = a.department?.name || "Bez dodeljenog odeljenja";
      if (!groups.has(id)) groups.set(id, { label, list: [] });
      groups.get(id).list.push(a);
    });
    if (!groups.size) { els.departments.appendChild(mk("p", "muted", "Nema agenata za izabranu pretragu.")); return; }
    [...groups].sort((a,b) => a[1].label.localeCompare(b[1].label,"sr")).forEach(([code, group]) => {
      const room = mk("section", "department");
      const heading = mk("header", "dept-title");
      heading.appendChild(mk("b", "", group.label));
      heading.appendChild(mk("small", "", code + " · " + group.list.length));
      room.appendChild(heading);
      const people = mk("div", "agent-grid");
      group.list.forEach(agent => {
        const btn = mk("button", "agent" + (agent.public_id === selected ? " selected" : ""));
        btn.type = "button";
        btn.setAttribute("aria-label", "Otvori agenta " + agent.display_name);
        portrait(btn, agent);
        btn.appendChild(mk("span", "name", agent.display_name));
        btn.appendChild(mk("span", "status", agent.status + " / " + agent.runtime_environment));
        btn.addEventListener("click", () => selectAgent(agent.public_id));
        people.appendChild(btn);
      });
      room.appendChild(people);
      els.departments.appendChild(room);
    });
  }
  function row(dl, k, v) { dl.appendChild(mk("dt", "", k)); dl.appendChild(mk("dd", "", v == null ? "—" : String(v))); }
  async function selectAgent(id) {
    selected = id;
    renderRooms();
    els.inspector.replaceChildren(mk("p", "muted", "Učitavanje profila…"));
    try {
      const a = await get(base + "agents/" + encodeURIComponent(id));
      if (id !== selected) return;
      els.inspector.replaceChildren();
      const head = mk("div", "inspect-head"); portrait(head, a);
      const label = mk("div");label.appendChild(mk("strong", "", a.display_name));
      label.appendChild(mk("small", "", a.public_id)); head.appendChild(label);
      els.inspector.appendChild(head);
      const tags = mk("div", "tag-row"); [a.status,a.runtime_environment,a.trust_level].forEach(t => tags.appendChild(mk("span", "tag", t)));
      els.inspector.appendChild(tags);
      const dl = mk("dl", "detail-dl");
      row(dl,"Odeljenje",a.department?.name); row(dl,"Radno mesto",a.position?.title);
      row(dl,"Zanimanje",a.occupation?.title);row(dl,"Aktivan plan",a.active_plan?.public_id);
      row(dl,"Status plana",a.active_plan?.status);row(dl,"Aktivni korak",a.active_step?.step_type);
      els.inspector.appendChild(dl);
      els.inspector.appendChild(mk("p", "inspect-note", "Status agenta i režim rada su odvojeni. Postojanje plana ne znači potvrđeno izvršavanje."));
    } catch (e) { els.inspector.replaceChildren(mk("p", "muted", e.message)); }
  }
  async function loadAgents() {
    const all = [];
    let cursor = null;
    do {
      const url = base + "agents?limit=100" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : "");
      const page = await get(url);
      all.push(...page.items);
      cursor = page.next_cursor;
      if (all.length > 10000) throw new Error("Limit prikaza je 10.000 agenata; primeni filter.");
    } while (cursor);
    agents = all;
    renderRooms();
  }
  async function loadSummary() {
    const data = await get(base + "summary");
    text("total", data.agents.total);text("plans", data.plans.active);text("approvals", data.approvals.pending);
  }
  async function loadEvents() {
    els.events.replaceChildren(mk("p", "muted", "Učitavanje…"));
    try {
      const data = await get(base + "events?limit=20");
      els.events.replaceChildren();
      if (!data.items.length) els.events.appendChild(mk("p", "muted", "Nema dostupnih događaja."));
      data.items.forEach(e => {
        const entry = mk("article", "event");
        entry.appendChild(mk("time", "", e.occurred_at));
        entry.appendChild(mk("strong", "", e.event_key));
        entry.appendChild(mk("small", "", (e.persona_public_id || "—") + " · " + e.severity));
        els.events.appendChild(entry);
      });
    } catch (e) { els.events.replaceChildren(mk("p", "muted", e.message)); }
  }
  async function refresh() {
    notice("Učitavanje iz Django baze…");
    try { await Promise.all([loadAgents(),loadSummary(),loadEvents()]);notice(""); }
    catch (e) { notice(e.message); }
  }
  document.getElementById("refresh").addEventListener("click", refresh);
  document.getElementById("reloadEvents").addEventListener("click", loadEvents);
  document.getElementById("all").addEventListener("click", () => { els.filter.value = ""; renderRooms(); });
  els.filter.addEventListener("input", renderRooms);
  refresh();
})();

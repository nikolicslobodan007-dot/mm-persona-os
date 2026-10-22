/** Pure office layout. No backend data, secrets, DOM or renderer dependencies. */
export const ROOM_W = 530;
export const ROOM_GAP = 92;
export const ROOM_X = 72;
export const ROOM_Y = 116;
export const ROOM_MIN_H = 344;
export const AGENTS_PER_ROW = 3;
export const ROOM_VERTICAL_GAP = 92;

const clean = value => String(value ?? "").trim();
export function safeAgent(agent) {
  const publicId = clean(agent?.public_id);
  if (!/^P-\d{5,20}$/.test(publicId)) return null;
  return {
    public_id: publicId,
    display_name: clean(agent.display_name).slice(0, 160),
    status: clean(agent.status).slice(0, 24),
    runtime_environment: clean(agent.runtime_environment).slice(0, 24),
    department: {
      code: clean(agent.department?.code || "UNASSIGNED").slice(0, 32),
      name: clean(agent.department?.name || "Neraspoređeni").slice(0, 100),
    },
  };
}

export function roomTheme(code, name) {
  const value = `${code} ${name}`.toLocaleLowerCase("sr");
  if (/finan|finance|računovod|account/.test(value)) return "finance";
  if (/marketing|content|sadržaj|uredništ|redakc/.test(value)) return "creative";
  if (/uprav|direktor|management|executive/.test(value)) return "executive";
  if (/nabav|dobavlja|procure|purchase/.test(value)) return "procurement";
  if (/podrš|support|service/.test(value)) return "support";
  if (/istraž|research|tržišt/.test(value)) return "research";
  if (/kvalitet|compliance|quality|bezbedn/.test(value)) return "quality";
  return "general";
}

const groupOf = a => a.department.code;
const roomHeight = count => ROOM_MIN_H + Math.max(0, Math.ceil(count / AGENTS_PER_ROW) - 2) * 120;
export function layoutCampus(records, focusDepartment = "") {
  const byCode = new Map();
  for (const record of records || []) {
    const person = safeAgent(record);
    if (!person || (focusDepartment && person.department.code !== focusDepartment)) continue;
    const code = groupOf(person);
    if (!byCode.has(code)) byCode.set(code, {
      code, name: person.department.name, theme: roomTheme(code, person.department.name), agents: [],
    });
    byCode.get(code).agents.push(person);
  }
  const groups = [...byCode.values()].sort((a, b) => a.name.localeCompare(b.name, "sr"));
  const rooms = []; let y = ROOM_Y;
  const cols = focusDepartment ? 1 : 2;
  for (let n = 0; n < groups.length; n += cols) {
    const row = groups.slice(n, n + cols);
    const maxHeight = Math.max(...row.map(group => roomHeight(group.agents.length)));
    row.forEach((room, col) => {
      const x = ROOM_X + col * (ROOM_W + ROOM_GAP);
      room.agents.sort((a, b) => a.display_name.localeCompare(b.display_name, "sr"));
      room.x = x; room.y = y; room.width = ROOM_W; room.height = maxHeight;
      room.people = room.agents.map((agent, i) => ({
        ...agent, x: x + 97 + (i % AGENTS_PER_ROW) * 169,
        y: y + 157 + Math.floor(i / AGENTS_PER_ROW) * 120,
      }));
      rooms.push(room);
    });
    y += maxHeight + ROOM_VERTICAL_GAP;
  }
  return {
    rooms,
    width: ROOM_X * 2 + cols * ROOM_W + (cols - 1) * ROOM_GAP,
    height: Math.max(500, y - ROOM_VERTICAL_GAP + 94),
  };
}

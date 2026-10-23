/** Responsive, deterministic office layout. No backend data, secrets, DOM or renderer. */
export const ROOM_W = 530;
export const ROOM_GAP = 58;
export const ROOM_X = 58;
export const ROOM_Y = 70;
export const ROOM_MIN_H = 344;
export const AGENTS_PER_ROW = 3;
export const ROOM_VERTICAL_GAP = 62;

const clean = value => String(value ?? '').trim();
export function safeAgent(agent) {
  const publicId = clean(agent?.public_id);
  if (!/^P-\d{5,20}$/.test(publicId)) return null;
  return {
    public_id: publicId,
    display_name: clean(agent.display_name).slice(0, 160),
    status: clean(agent.status).slice(0, 24),
    runtime_environment: clean(agent.runtime_environment).slice(0, 24),
    department: {
      code: clean(agent.department?.code || 'UNASSIGNED').slice(0, 32),
      name: clean(agent.department?.name || 'Neraspoređeni').slice(0, 100),
    },
  };
}

export function roomTheme(code, name) {
  const value = `${code} ${name}`.toLocaleLowerCase('sr');
  if (/finan|finance|računovod|account/.test(value)) return 'finance';
  if (/marketing|content|sadržaj|uredništ|redakc/.test(value)) return 'creative';
  if (/uprav|direktor|management|executive/.test(value)) return 'executive';
  if (/nabav|dobavlja|procure|purchase/.test(value)) return 'procurement';
  if (/podrš|support|service/.test(value)) return 'support';
  if (/istraž|research|tržišt/.test(value)) return 'research';
  if (/kvalitet|compliance|quality|bezbedn/.test(value)) return 'quality';
  return 'general';
}

const roomHeight = count => ROOM_MIN_H + Math.max(0, Math.ceil(count / AGENTS_PER_ROW) - 2) * 120;
const dimension = (v, fallback) => Number.isFinite(v) && v > 0 ? v : fallback;

/** Predict the actual stage dimensions for a particular number of columns. */
function geometryFor(groups, cols) {
  const rowHeights = [];
  for (let i = 0; i < groups.length; i += cols) {
    rowHeights.push(Math.max(...groups.slice(i, i + cols).map(g => roomHeight(g.agents.length))));
  }
  const rows = rowHeights.map((height, index) => ({index, height}));
  const width = ROOM_X * 2 + cols * ROOM_W + (cols - 1) * ROOM_GAP;
  const height = ROOM_Y * 2 + rowHeights.reduce((a, h) => a + h, 0)
    + Math.max(0, rows.length - 1) * ROOM_VERTICAL_GAP;
  return {cols, rows, width, height};
}

/**
 * Pick a layout that makes agents legible in the *current* viewport.
 * Maximizing fit-scale avoids a tall 2-column strip on a wide monitor.
 * Empty last-row slots and extreme aspect ratios receive a small penalty.
 * Limits to 5 columns keep rooms distinguishable and the scene navigable.
 */
export function chooseCampusGrid(groups, viewport = {}) {
  if (!groups.length) return geometryFor(groups, 1);
  const width = dimension(viewport.width, 1150);
  const height = dimension(viewport.height, 680);
  const screenAspect = width / height;
  let best = null;
  for (let cols = 1; cols <= Math.min(5, groups.length); cols++) {
    const candidate = geometryFor(groups, cols);
    const scale = Math.min(width * 0.90 / candidate.width, height * 0.90 / candidate.height);
    const aspectPenalty = Math.abs(Math.log((candidate.width / candidate.height) / screenAspect));
    const lastRowEmpty = (cols - (groups.length % cols)) % cols;
    const score = scale * (1 - Math.min(aspectPenalty, 3) * 0.075)
      * (1 - 0.018 * lastRowEmpty / cols);
    if (!best || score > best.score + 1e-9) best = {...candidate, score};
  }
  return best;
}

/**
 * @param {Array<object>} records - already allowlisted agent JSON
 * @param {string} focusDepartment - public Department.code, or empty for whole building
 * @param {{width?: number, height?: number}} viewport - PixiJS stage dimensions
 */
export function layoutCampus(records, focusDepartment = '', viewport = {}) {
  const byCode = new Map();
  for (const record of records || []) {
    const person = safeAgent(record);
    if (!person || (focusDepartment && person.department.code !== focusDepartment)) continue;
    const code = person.department.code;
    if (!byCode.has(code)) byCode.set(code, {
      code, name: person.department.name, theme: roomTheme(code, person.department.name), agents: [],
    });
    byCode.get(code).agents.push(person);
  }
  const groups = [...byCode.values()].sort((a, b) => a.name.localeCompare(b.name, 'sr'));
  for (const group of groups) {
    group.agents.sort((a, b) => a.display_name.localeCompare(b.display_name, 'sr'));
  }
  const geometry = focusDepartment ? geometryFor(groups, 1) : chooseCampusGrid(groups, viewport);
  const rooms = [], rows = [];
  let y = ROOM_Y;
  for (let start = 0; start < groups.length; start += geometry.cols) {
    const row = groups.slice(start, start + geometry.cols);
    const maxHeight = Math.max(...row.map(group => roomHeight(group.agents.length)));
    rows.push({index: rows.length, y, height: maxHeight});
    // Center incomplete rows; there are no fake rooms to fill empty slots.
    // Avoid shifting the rest of the building or modifying department order.
    const offset = (geometry.cols - row.length) * (ROOM_W + ROOM_GAP) / 2;
    row.forEach((room, col) => {
      const x = ROOM_X + offset + col * (ROOM_W + ROOM_GAP);
      room.x = x; room.y = y; room.width = ROOM_W; room.height = maxHeight;
      room.people = room.agents.map((agent, i) => ({
        ...agent,
        x: x + 97 + (i % AGENTS_PER_ROW) * 169,
        y: y + 157 + Math.floor(i / AGENTS_PER_ROW) * 120,
      }));
      rooms.push(room);
    });
    y += maxHeight + ROOM_VERTICAL_GAP;
  }
  return {
    rooms, rows, columns: geometry.cols,
    width: geometry.width,
    height: Math.max(ROOM_Y * 2 + ROOM_MIN_H, geometry.height),
    rowGap: ROOM_VERTICAL_GAP,
  };
}

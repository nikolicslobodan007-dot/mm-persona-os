import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutCampus, chooseCampusGrid} from '../src/layout.mjs';
import {cameraForCampus} from '../src/camera.mjs';

const teamSizes = [2, 3, 3, 2, 4, 3, 2, 3, 9, 2];
const agents = teamSizes.flatMap((size, index) => Array.from({length: size}, (_, n) => ({
  public_id: `P-${String(1 + teamSizes.slice(0, index).reduce((a, b) => a + b, 0) + n).padStart(5, '0')}`,
  display_name: `Agent ${index} ${n}`,
  status: 'READY',
  runtime_environment: index % 2 ? 'SIMULATION' : 'CONTROLLED_LIVE',
  department: {code: `DEPT-${index}`, name: `Odeljenje ${index}`},
})));

function collide(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x &&
    a.y < b.y + b.height && a.y + a.height > b.y;
}

test('desktop campus chooses 3+ columns for ten departments, not tall 2x5 strip', () => {
  const layout = layoutCampus(agents, '', {width: 1050, height: 520});
  assert.equal(layout.rooms.length, 10);
  assert.ok(layout.columns >= 3);
  assert.ok(layout.rows.length <= 4);
});

test('fit-to-bounds occupies screen on desktop without clipping', () => {
  const layout = layoutCampus(agents, '', {width: 1050, height: 520});
  const camera = cameraForCampus(layout, 1050, 520);
  assert.ok(camera.fittedWidth / 1050 >= .72, 'building should occupy most available width');
  assert.ok(camera.fittedWidth <= 1050 * .921);
  assert.ok(camera.fittedHeight <= 520 * .901);
  assert.ok(camera.x >= -0.0001 && camera.y >= -0.0001);
});

test('rooms do not overlap and every agent belongs to exactly one room', () => {
  for (const dims of [[1050, 520], [800, 800], [390, 650]]) {
    const layout = layoutCampus(agents, '', {width: dims[0], height: dims[1]});
    const publicIds = layout.rooms.flatMap(r => r.people.map(p => p.public_id));
    assert.equal(new Set(publicIds).size, agents.length);
    for (const room of layout.rooms) {
      for (const person of room.people) {
        assert.ok(person.x > room.x && person.x < room.x + room.width);
        assert.ok(person.y > room.y && person.y < room.y + room.height);
      }
      for (const other of layout.rooms) {
        if (room === other) continue;
        assert.equal(collide(room, other), false);
      }
    }
  }
});

test('same records and viewport generate deterministic layout', () => {
  const a = layoutCampus(agents, '', {width: 1100, height: 520});
  const b = layoutCampus([...agents].reverse(), '', {width: 1100, height: 520});
  assert.deepEqual(a, b);
});

test('focus only includes selected department and recenters camera', () => {
  const single = layoutCampus(agents, 'DEPT-8', {width: 1050, height: 520});
  assert.equal(single.rooms.length, 1);
  assert.equal(single.rooms[0].people.length, 9);
  const camera = cameraForCampus(single, 1050, 520, 1, 'DEPT-8');
  assert.ok(camera.scale > 0.5);
  assert.ok(camera.fittedWidth < 1050);
});

test('zoom is relative to fitted bounds and centered on viewport', () => {
  const layout = layoutCampus(agents, '', {width: 1050, height: 520});
  const base = cameraForCampus(layout, 1050, 520, 1);
  const zoom = cameraForCampus(layout, 1050, 520, 1.15);
  assert.ok(Math.abs(zoom.scale / base.scale - 1.15) < 1e-9);
  assert.ok(Math.abs(base.x + layout.width * base.scale / 2 - 1050 / 2) < 1e-9);
  assert.ok(Math.abs(base.y + layout.height * base.scale / 2 - 520 / 2) < 1e-9);
});

test('mobile fits content and does not grow beyond viewport', () => {
  const dims = {width: 390, height: 650};
  const layout = layoutCampus(agents, '', dims);
  const camera = cameraForCampus(layout, dims.width, dims.height);
  assert.ok(camera.scale > 0);
  assert.ok(camera.fittedWidth <= dims.width);
  assert.ok(camera.fittedHeight <= dims.height);
});

test('empty, invalid and adversarial input does not create phantom agents', () => {
  const layout = layoutCampus([{}, null, {public_id: 'P-1234', department:{code:'A'}}], '', {width:600, height:400});
  assert.equal(layout.rooms.length, 0);
  const camera = cameraForCampus(layout, 600, 400);
  assert.ok(Number.isFinite(camera.scale));
  const empty = chooseCampusGrid([], {width:600, height:400});
  assert.equal(empty.cols, 1);
});

test('layout never infers RUNNING from persona status or runtime environment', () => {
  const layout = layoutCampus(agents, '', {width: 1050, height: 520});
  for (const p of layout.rooms.flatMap(r => r.people)) {
    assert.equal(Object.hasOwn(p, 'isRunning'), false);
    assert.equal(Object.hasOwn(p, 'running'), false);
  }
});

// node --test src/zone.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bandEdges, bandColour, legend, verdict, spoken, viaZone, bandRange, bookingNote, sameSettings, corridorColour, shade, zoneColour, BAND_COLOURS } from './zone.js';

const cov = { limit_miles: 50, hub_miles: 5, band_step_miles: 10 };

test('band edges match zonegen.classify.band_edges', () => {
  assert.deepEqual(bandEdges(cov), [0, 5, 15, 25, 35, 45, 50]);
  assert.deepEqual(bandEdges({ limit_miles: 45, hub_miles: 5, band_step_miles: 10 }), [0, 5, 15, 25, 35, 45]);
  assert.equal(bandRange(2, cov), '15–25');
  assert.equal(bandRange(9, cov), null);
});

test('legend runs green at the Hub to red at the last band', () => {
  const l = legend(cov);
  assert.equal(l.length, 6);
  assert.equal(l[0].name, 'Hub');
  assert.equal(l[0].colour, BAND_COLOURS[0]);
  assert.equal(l[5].colour, BAND_COLOURS[5]);
  assert.equal(bandColour(1, 1), BAND_COLOURS[5]);
});

test('verdict never calls an unsure answer a yes', () => {
  assert.equal(verdict({ status: 'centroid_sampled', zone: '2AB', review: false }), 'in');
  assert.equal(verdict({ status: 'centroid_sampled', zone: '2AB', review: true }), 'review');
  assert.equal(verdict({ status: 'centroid_sampled', zone: '2?', review: false }), 'review');
  assert.equal(verdict({ status: 'unreachable', zone: null, review: false }), 'review');
  assert.equal(verdict({ status: 'outside_coverage', zone: null, review: false }), 'out');
});

test('zone codes read aloud and name their branch', () => {
  assert.equal(spoken('2AB'), 'two A B');
  assert.equal(spoken('0'), 'zero, the Hub');
  assert.equal(spoken('3?'), 'three unknown highway');
  assert.equal(viaZone('2AB'), '2A');
  assert.equal(viaZone('2A'), null);
  assert.equal(viaZone('0'), null);
});

test('each corridor has its own colour, darker for each ring further out', () => {
  const ids = ['A', 'AB', 'B', 'HUB', 'L'];
  const a = corridorColour('A', ids);
  assert.notEqual(a, corridorColour('AB', ids));
  assert.notEqual(a, corridorColour('B', ids));
  assert.equal(corridorColour('HUB', ids), '#52525B');
  assert.equal(shade('#3B7DD8', 1), '#3B7DD8');
  assert.ok(parseInt(shade('#3B7DD8', 3).slice(1, 3), 16) < 0x3B);
  assert.equal(zoneColour({ corridor: 'A', band: 2 }, 'zones', ids, 5), shade(a, 2));
  assert.equal(zoneColour({ corridor: 'A', band: 0 }, 'distance', ids, 5), BAND_COLOURS[0]);
  assert.match(corridorColour('Z', [...'ABCDEFGHIJKLMZ']), /^hsl\(/);
});

test('settings match ignores highway order and number types', () => {
  const v = { limit_miles: 50, hub_miles: 5, band_step_miles: 10, min_corridor_cells: 30, highways: ['I', 'US'] };
  assert.ok(sameSettings(v, { ...v, limit_miles: '50', highways: ['US', 'I'] }));
  assert.ok(!sameSettings(v, { ...v, highways: ['I'] }));
  assert.ok(!sameSettings(v, { ...v, min_corridor_cells: 40 }));
});

test('booking note is one pasteable line', () => {
  const r = { zone: '3CA', miles: 27.9, label: 'Oak Ridge Road, Los Gatos, Santa Clara County, California' };
  assert.equal(bookingNote('review', r), 'Zone 3CA (needs review) · 27.9 road mi · Oak Ridge Road, Los Gatos, Santa Clara County');
  assert.equal(bookingNote('out', { zone: null, miles: 63.8, label: 'Salinas' }), 'Outside service area · 63.8 road mi · Salinas');
});

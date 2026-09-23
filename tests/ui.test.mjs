import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts, dataURL } from '../assets/domain.mjs';

const t = Date.parse('2026-09-23T12:00:00Z');
const a = { id: 'one', player: 'A.J. Brown', team: 'NE', opponent: 'SEA', injury: 'Ankle', position: 'WR', outcome: 'out', gameDate: '2026-09-09', claims: [{ date: '2026-09-10' }] };
const b = { id: 'two', player: 'Rico Dowdle', team: 'PIT', opponent: 'NE', injury: 'Toe', position: 'RB', outcome: 'returned', gameDate: '2026-09-20', claims: [{ date: '2026-09-22' }] };

test('changing feeds bypass stale Pages edge caches once per minute', () => {
  const base = 'https://example.github.io/InjuryAlerTNFL/';
  const live = dataURL('./data/live.json', base, t);
  assert.equal(live.href, `${base}data/live.json?check=${Math.floor(t / 60_000)}`);
  assert.equal(dataURL('./data/live.json', base, t + 10_000).href, live.href);
  assert.notEqual(dataURL('./data/live.json', base, t + 60_000).href, live.href);
  assert.ok(dataURL('./data/scoreboard.json', base, t).searchParams.has('check'));
  assert.equal(dataURL('./data/archive.json', base, t).search, '');
});

test('curated entry wins when live feed has the same game/player', () => {
  const merged = mergeIncidents([a, b], [{ ...a, player: 'Incorrect auto label', automatic: true }]);
  assert.deepEqual(merged.map(row => row.id), ['two', 'one']);
  assert.equal(merged[1].player, 'A.J. Brown');
});
test('query and outcome filters never treat returned as cleared for next game', () => {
  assert.deepEqual(filterIncidents([a, b], { query: 'toe', outcome: 'returned' }).map(row => row.id), ['two']);
  assert.deepEqual(filterIncidents([a, b], { team: 'NE', outcome: 'returned' }), []);
});
test('missing, future, old, and failing checks are not fresh', () => {
  assert.equal(freshness({ checkedAt: null, status: 'ok' }, t), 'not_checked');
  assert.equal(freshness({ checkedAt: '2026-09-23T12:06:00Z', status: 'ok' }, t), 'stale');
  assert.equal(freshness({ checkedAt: '2026-09-23T11:39:00Z', status: 'ok' }, t), 'stale');
  assert.equal(freshness({ checkedAt: '2026-09-23T11:55:00Z', status: 'unavailable' }, t), 'degraded');
  assert.equal(freshness({ checkedAt: '2026-09-23T11:55:00Z', status: 'waiting' }, t), 'waiting');
});
test('scores show nearest game day, not fabricated no-games or old scores', () => {
  const games = [{ id: '1', date: '2026-09-24T20:00:00Z' }, { id: '2', date: '2026-09-27T17:00:00Z' }];
  assert.equal(selectScoreGames(games, t).games[0].id, '1');
  assert.deepEqual(selectScoreGames([], t).games, []);
});
test('browser alerts never fire for archive, prior feed IDs, or stale games', () => {
  const recent = { id: 'new', automatic: true, gameStart: '2026-09-23T11:00:00Z' };
  const old = { id: 'stale', automatic: true, gameStart: '2026-09-20T11:00:00Z' };
  assert.deepEqual(newAutoAlerts([], [a, old, recent], t).map(item => item.id), ['new']);
  assert.deepEqual(newAutoAlerts([recent], [recent], t), []);
});

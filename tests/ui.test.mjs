import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts, dataURL,
  tierLabel, detectInGameSignals, rankSignals, humanizeSeconds, latencySeconds,
  liveGames, shouldWatchForInGame, socialSearchLinks, eligiblePartnerAlerts,
} from '../assets/domain.mjs';

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

test('in-game wording is only reported when a provider actually said it', () => {
  assert.equal(detectInGameSignals('Seahawks NT Brandon Pili (concussion) has been ruled out.').status, 'out');
  assert.equal(detectInGameSignals('Barkley returned to the field after halftime.').status, 'returned');
  assert.equal(detectInGameSignals('X is questionable to return with an ankle injury.').status, 'questionable');
  assert.deepEqual(detectInGameSignals('Reed was carted off on a stretcher'), { status: 'observed', observation: 'Cart or stretcher', phrase: 'carted off' });
  assert.equal(detectInGameSignals('J. Smith runs for 6 yards up the middle.'), null);
  assert.equal(detectInGameSignals('short'), null);
});
test('signal ranking puts availability outcomes above observations', () => {
  const ranked = rankSignals([
    { id: 'observed', signal: { status: 'observed' }, detectedAt: '2026-09-24T17:00:00Z' },
    { id: 'out', signal: { status: 'out' }, detectedAt: '2026-09-24T16:00:00Z' },
    { id: 'questionable', signal: { status: 'questionable' }, detectedAt: '2026-09-24T16:30:00Z' },
  ]);
  assert.deepEqual(ranked.map(item => item.id), ['out', 'questionable', 'observed']);
});
test('latency is measured against the provider timestamp and never goes negative', () => {
  assert.equal(latencySeconds('2026-09-24T17:00:00Z', '2026-09-24T16:58:30Z'), 90);
  assert.equal(latencySeconds('2026-09-24T16:00:00Z', '2026-09-24T17:00:00Z'), 0);
  assert.equal(latencySeconds('not a time', '2026-09-24T16:58:30Z'), null);
  assert.equal(humanizeSeconds(45), '45s');
  assert.equal(humanizeSeconds(9000), '2.5 h');
  assert.equal(humanizeSeconds(null, 'unknown'), 'unknown');
});
test('the watch window is honest about when a game is actually in play', () => {
  const games = [
    { id: 'live', phase: 'live', date: '2026-09-24T00:15:00Z' },
    { id: 'soon', date: '2026-09-23T12:10:00Z' },
    { id: 'later-today', date: '2026-09-23T20:00:00Z' },
    { id: 'old', date: '2026-09-20T17:00:00Z' },
    { id: 'over', phase: 'final', date: '2026-09-23T11:55:00Z' },
  ];
  assert.deepEqual(liveGames(games, t).map(item => item.id).sort(), ['live', 'soon']);
  assert.equal(shouldWatchForInGame([{ id: 'old', phase: 'final', date: '2026-09-20T17:00:00Z' }], t), false);
  assert.equal(shouldWatchForInGame(games, t), true);
});
test('unofficial lanes are link-outs with tier labels, never fetched evidence', () => {
  const links = socialSearchLinks('Jayden Reed', 'GB');
  assert.equal(links.length, 8);
  assert.ok(links.every(link => link.url.startsWith('https://') && link.tier === 'unofficial'));
  assert.ok(links.some(link => link.url.startsWith('https://x.com/search')));
  assert.ok(links.some(link => link.url.startsWith('https://www.reddit.com/search')));
  assert.equal(tierLabel('official'), 'OFFICIAL — league or club');
  assert.equal(tierLabel('nonsense').includes('UNCLASSIFIED'), true);
});
test('a partner item becomes an alert only when its own text and a live game agree', () => {
  const live = [{ id: 'g', phase: 'live', date: '2026-09-24T00:15:00Z', home: 'GB', away: 'ATL' }];
  const articles = [
    { headline: 'Packers WR ruled out with a knee injury', description: '', teamAbbreviations: ['GB'] },
    { headline: 'Trade grades from around the league', description: '', teamAbbreviations: ['GB'] },
    { headline: 'Jets safety questionable to return', description: '', teamAbbreviations: ['NYJ'] },
    { headline: 'Falcons injury update', description: 'ruled out', teamAbbreviations: ['ATL'] },
  ];
  const alerts = eligiblePartnerAlerts(articles, live, t);
  assert.deepEqual(alerts.map(item => item.headline), ['Packers WR ruled out with a knee injury', 'Falcons injury update']);
  assert.ok(alerts.every(item => item.tier === 'partner'));
});

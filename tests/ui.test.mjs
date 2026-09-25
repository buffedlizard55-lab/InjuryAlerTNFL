import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts, dataURL,
  tierLabel, detectInGameSignals, detectAllSignals, rankSignals, humanizeSeconds, latencySeconds,
  stampSeconds, isoSeconds, mergeAlertLog, newSince, logLine, groupSources, laneHealth,
  liveGames, shouldWatchForInGame, socialSearchLinks, eligiblePartnerAlerts,
} from '../assets/domain.mjs';

const t = Date.parse('2026-09-23T12:00:00Z');
const a = { id: 'one', player: 'A.J. Brown', team: 'NE', opponent: 'SEA', injury: 'Ankle', position: 'WR', outcome: 'out', gameDate: '2026-09-09', claims: [{ date: '2026-09-10' }] };
const b = { id: 'two', player: 'Rico Dowdle', team: 'PIT', opponent: 'NE', injury: 'Toe', position: 'RB', outcome: 'returned', gameDate: '2026-09-20', claims: [{ date: '2026-09-22' }] };

test('changing feeds bypass stale Pages edge caches once per 30-second bucket', () => {
  const base = 'https://example.github.io/InjuryAlerTNFL/';
  const live = dataURL('./data/live.json', base, t);
  assert.equal(live.href, `${base}data/live.json?check=${Math.floor(t / 30_000)}`);
  assert.equal(dataURL('./data/live.json', base, t + 10_000).href, live.href);
  assert.notEqual(dataURL('./data/live.json', base, t + 30_000).href, live.href);
  // Every machine-written file the page reads revalidates on the same clock, so
  // a new log entry or club-scan candidate is never stuck behind a stale cache.
  for (const path of ['./data/scoreboard.json', './data/alert-log.json', './data/candidates.json', './data/watch.json']) {
    assert.ok(dataURL(path, base, t).searchParams.has('check'), `${path} must be cache-busted`);
  }
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
  const carted = detectInGameSignals('Reed was carted off on a stretcher');
  assert.equal(carted.status, 'observed');
  assert.equal(carted.observation, 'Cart or stretcher');
  assert.equal(carted.phrase, 'carted off');
  assert.equal(carted.label, 'CART / STRETCHER wording');
  // A sentence can carry more than one honest signal; the strongest one leads and
  // the rest stay available rather than being silently dropped.
  const both = detectAllSignals('Goedert was ruled out after he was carted off the field.');
  assert.deepEqual(both.map(signal => signal.status).slice(0, 2), ['out', 'observed']);
  assert.equal(detectInGameSignals('J. Smith runs for 6 yards up the middle.'), null);
  assert.equal(detectInGameSignals('short'), null);
});
test('return-side and got-up wording is surfaced, replay chatter is not', () => {
  // Pass 8 vocabulary: the brief asks for "does he get up, does he come back".
  assert.equal(detectInGameSignals('Smith was carted off and is under evaluation on the field.').status, 'evaluated');
  assert.equal(detectInGameSignals('Jones got up and walked back to the huddle.').status, 'observed');
  assert.equal(detectInGameSignals('Brown was back on his feet after the hit.').status, 'observed');
  assert.equal(detectInGameSignals('Williams re-entered the game in the second quarter.').status, 'returned');
  assert.equal(detectInGameSignals('The replay is under review by the officials.'), null);
  // The stronger availability phrase still leads when both appear; "may not
  // return" is return-uncertain wording, not a ruling.
  const both = detectAllSignals('He was carted off, is under evaluation, and may not return.');
  assert.deepEqual(both.map(signal => signal.status).slice(0, 2), ['questionable', 'evaluated']);
  assert.equal(detectInGameSignals('He may return after the next drive.').status, 'questionable');
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

test('timestamps are shown to the second, and never invented', () => {
  assert.equal(isoSeconds('2026-09-24T20:53:07.412Z'), '2026-09-24T20:53:07Z');
  assert.equal(isoSeconds('2026-09-24T20:53:07+00:00'), '2026-09-24T20:53:07Z');
  assert.equal(isoSeconds(''), null);
  assert.equal(isoSeconds('sometime yesterday'), null);
  assert.match(stampSeconds('2026-09-24T20:53:07Z'), /20:53:07 UTC$/);
  assert.equal(stampSeconds(null), 'time unavailable');
});

test('the session log survives refreshes and keeps the first detection time', () => {
  const server = [
    { id: 'b', detectedAt: '2026-09-24T20:00:02Z', lane: 'x', tier: 'partner', subject: 'B' },
    { id: 'a', detectedAt: '2026-09-24T20:00:01Z', lane: 'x', tier: 'official', subject: 'A' },
  ];
  const session = [
    // The same event seen later (a refetch) must never rewrite the first sighting.
    { id: 'a', detectedAt: '2026-09-24T21:00:00Z', lane: 'x', tier: 'official', subject: 'A' },
    { id: 'c', detectedAt: '2026-09-24T20:30:00Z', lane: 'y', tier: 'unofficial', subject: 'C' },
  ];
  const merged = mergeAlertLog(server, session);
  assert.deepEqual(merged.map(entry => entry.id), ['c', 'b', 'a']);
  assert.equal(merged.find(entry => entry.id === 'a').detectedAt, '2026-09-24T20:00:01Z');
  assert.deepEqual(newSince(merged, '2026-09-24T20:15:00Z').map(entry => entry.id), ['c']);
  assert.deepEqual(newSince(merged, null), []);
});

test('an alert says what it knows about latency instead of guessing', () => {
  const withSource = logLine({ detectedAt: '2026-09-24T20:00:30Z', sourceAt: '2026-09-24T20:00:00Z' });
  assert.match(withSource, /provider timestamp/);
  assert.match(withSource, /30s later/);
  assert.match(logLine({ detectedAt: '2026-09-24T20:00:30Z' }), /not published on this lane/);
});

test('the registry groups by tier and category, and filters without inventing rows', () => {
  const lanes = [
    { id: 'o1', name: 'Club newsroom', tier: 'official', category: 'official-club', org: 'X', what: 'w', proves: 'p' },
    { id: 'p1', name: 'ESPN feed', tier: 'partner', category: 'partner-espn', org: 'ESPN', what: 'w', proves: 'p' },
    { id: 'u1', name: 'Beat writer', tier: 'unofficial', category: 'unofficial-beat', org: 'Outlet', what: 'w', proves: 'p' },
  ];
  const groups = groupSources(lanes);
  assert.deepEqual(groups.map(group => group.category), ['official-club', 'partner-espn', 'unofficial-beat']);
  assert.equal(groups[0].rows.length, 1);
  const filtered = lanes.filter(lane => lane.tier !== 'partner');
  assert.equal(filtered.length, 2);
  assert.equal(laneHealth({ checkedAt: '2026-09-24T20:00:00Z', status: 'ok' }, Date.parse('2026-09-24T20:10:00Z')), 'ok');
  assert.equal(laneHealth({ checkedAt: '2026-09-24T19:00:00Z', status: 'ok' }, Date.parse('2026-09-24T20:10:00Z')), 'stale');
  assert.equal(laneHealth({}, Date.now()), 'unknown');
});

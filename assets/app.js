/* Sideline Signal — page logic.
 *
 * Two clocks, one rule: a live game outranks everything, and nothing is shown
 * without its tier, its source and a timestamp.
 *
 *   * fast lanes (this file, 10-20 s) — ESPN scoreboard header, per-game
 *     summary (injuries section), ESPN core play-by-play and the ESPN news
 *     feed. All of it is PARTNER tier: shown, never presented as official.
 *   * durable lanes (the repository, minutes to hours) — data/alert-log.json,
 *     data/candidates.json, data/live.json, data/watch.json: what the CI
 *     collectors saw, with the sentence and the URL.
 *
 * Everything the page sees is written to a session log in localStorage, so a
 * refresh cannot lose an alert, and "new since your last visit" is exact.
 */
import {
  OUTCOME_LABEL, mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts, dataURL,
  tierLabel, detectInGameSignals, detectAllSignals, rankSignals, signalWeight, humanizeSeconds, latencySeconds,
  liveGames, shouldWatchForInGame, socialSearchLinks, eligiblePartnerAlerts,
  isoSeconds, stampSeconds, mergeAlertLog, newSince, logLine, groupSources, filterSources,
  SOURCE_CATEGORY_LABEL, LATENCY_LABEL, laneHealth,
} from './domain.mjs';

const $ = id => document.getElementById(id);
const SESSION_KEY = 'sideline-signal-session-log-v1';
const VISIT_KEY = 'sideline-signal-last-visit-v1';
const SESSION_CAP = 300;

const ESPN_HEADER = 'https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=football&league=nfl';
const ESPN_NEWS = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=25';
const ESPN_SUMMARY = eventId => `https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=${eventId}`;
const ESPN_PLAYS = eventId => `https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/${eventId}`
  + `/competitions/${eventId}/plays?limit=120`;
const LANE_HEADER_MS = 10_000;
const LANE_GAME_MS = 20_000;

const state = {
  archive: null, review: null, live: null, scores: null, sources: null, leads: null,
  alertLog: null, candidates: null, watch: null, rows: [],
  filter: { query: '', team: 'all', outcome: 'all' },
  sourceFilter: { query: '', tier: 'all', category: 'all', access: 'all' },
  logFilter: 'all',
  ready: false, notifications: false,
  laneStatus: { header: 'idle', news: 'idle', summary: 'idle', plays: 'idle' },
  laneCheckedAt: { header: null, news: null, summary: null, plays: null },
  laneLatencyMs: {},
  liveSignals: [], partnerArticles: [], lastLaneCheck: null,
  sessionLog: [], lastVisit: null, newIds: new Set(),
};

/* ------------------------------------------------------------------ small helpers */
const el = (tag, className = '', content = '') => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== '') node.textContent = String(content);
  return node;
};
const notice = text => el('p', 'notice', text);
const day = value => {
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(date)
    : 'Date unverified';
};
const reading = value => (value === null || value === undefined || value === '' ? '—' : String(value));

function trustedLink(url, label, type = 'news') {
  const link = el('a', '', label);
  let valid = false;
  try {
    const parsed = new URL(url);
    const allowed = [
      'www.49ers.com',
      'www.atlantafalcons.com',
      'www.azcardinals.com',
      'www.baltimoreravens.com',
      'www.bengals.com',
      'www.buccaneers.com',
      'www.buffalobills.com',
      'www.chargers.com',
      'www.chicagobears.com',
      'www.chiefs.com',
      'www.clevelandbrowns.com',
      'www.colts.com',
      'www.commanders.com',
      'www.dallascowboys.com',
      'www.denverbroncos.com',
      'www.detroitlions.com',
      'www.giants.com',
      'www.houstontexans.com',
      'www.jaguars.com',
      'www.miamidolphins.com',
      'www.neworleanssaints.com',
      'www.newyorkjets.com',
      'www.nfl.com',
      'www.packers.com',
      'www.panthers.com',
      'www.patriots.com',
      'www.philadelphiaeagles.com',
      'www.raiders.com',
      'www.rams.com',
      'www.seahawks.com',
      'www.steelers.com',
      'www.tennesseetitans.com',
      'www.vikings.com',
];
    const hostOk = allowed.includes(parsed.hostname) || parsed.hostname.endsWith('.nfl.com');
    valid = parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port
      && !parsed.search && !parsed.hash && hostOk
      && (parsed.pathname.startsWith('/news/') || parsed.pathname.startsWith('/videos/')
        || parsed.pathname.startsWith('/game-day/')
        || (type === 'review' && parsed.hostname === 'www.nfl.com' && parsed.pathname.startsWith('/players/')))
      || (parsed.protocol === 'https:' && parsed.hostname === 'www.nfl.com'
        && parsed.pathname.startsWith('/playerhealthandsafety/'));
  } catch { /* Invalid URLs are never followed. */ }
  if (valid) {
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  } else {
    link.textContent = 'Source URL unavailable';
    link.removeAttribute('href');
  }
  return link;
}

function tierLink(url, label, tier) {
  const link = el('a', `tier-link tier-${tier}`, label);
  let ok = false;
  try {
    const parsed = new URL(url);
    ok = parsed.protocol === 'https:' && !parsed.username && !parsed.password && Boolean(parsed.hostname);
  } catch { /* A malformed URL is never followed. */ }
  if (ok) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  else { link.textContent = 'Link unavailable'; link.removeAttribute('href'); }
  return link;
}

const NEW_IDS = new Set([
  '2026-09-13-atl-a-j-terrell', '2026-09-13-cle-zion-johnson', '2026-09-13-phi-cooper-dejean',
  '2026-09-13-phi-jalen-carter', '2026-09-20-chi-tyson-bagent', '2026-09-20-nyj-kiko-mauigoa',
  '2026-09-20-nyj-mason-taylor', '2026-09-20-sf-romello-height',
  '2026-09-20-no-martin-emerson-jr', '2026-09-20-min-brett-thorson',
]);

/* ------------------------------------------------------------------ session log */
function loadSessionLog() {
  try {
    const raw = window.localStorage?.getItem(SESSION_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(entry => entry && entry.detectedAt) : [];
  } catch { return []; }
}

function saveSessionLog() {
  try { window.localStorage?.setItem(SESSION_KEY, JSON.stringify(state.sessionLog.slice(0, SESSION_CAP))); }
  catch { /* Private mode: the server log still holds everything durable. */ }
}

function remember(entries) {
  if (!entries.length) return 0;
  const known = new Set(state.sessionLog.map(entry => entry.id));
  const fresh = entries.filter(entry => entry && entry.id && !known.has(entry.id));
  if (!fresh.length) return 0;
  state.sessionLog = [...fresh, ...state.sessionLog].slice(0, SESSION_CAP);
  saveSessionLog();
  return fresh.length;
}

/* ------------------------------------------------------------------ alert log view */
function mergedLog() {
  return mergeAlertLog(state.alertLog?.entries ?? [], state.sessionLog);
}

function logEntryCard(entry, isNew) {
  const card = el('article', `log-card log-${entry.kind}${isNew ? ' log-new' : ''}`);
  const top = el('div', 'log-top');
  top.append(el('span', `tier-chip tier-${entry.tier}`, tierLabel(entry.tier)));
  top.append(el('span', 'log-kind', entry.kind.replace(/-/g, ' ')));
  if (isNew) top.append(el('span', 'new-badge', 'NEW'));
  top.append(el('span', 'log-stamp', stampSeconds(entry.detectedAt)));
  card.append(top);
  card.append(el('h3', 'log-subject', entry.subject || entry.lane));
  if (entry.text) card.append(el('p', 'log-text', entry.text));
  if (entry.quote && entry.quote !== entry.text) card.append(el('blockquote', '', `“${entry.quote}”`));
  const meta = el('div', 'log-meta');
  meta.append(el('span', 'log-lane', `${entry.lane}${entry.status ? ` · ${entry.status}` : ''}`));
  meta.append(el('span', 'log-latency', logLine(entry)));
  if (entry.evidence) meta.append(tierLink(entry.evidence, 'Open the source ↗', entry.tier));
  card.append(meta);
  if (entry.note) card.append(el('p', 'microcopy', entry.note));
  return card;
}

function renderLog() {
  const box = $('alert-log-list');
  if (!box) return;
  const entries = mergedLog();
  const filtered = entries.filter(entry => state.logFilter === 'all' ? true
    : state.logFilter === 'new' ? state.newIds.has(entry.id) : entry.tier === state.logFilter);
  const newCount = entries.filter(entry => state.newIds.has(entry.id)).length;
  const count = $('count-log');
  if (count) count.textContent = String(entries.length);
  const status = $('alerts-status');
  if (status) {
    status.textContent = entries.length
      ? `${entries.length} logged alert(s) · ${newCount} new since your last visit${state.lastVisit ? ` (${stampSeconds(state.lastVisit)})` : ''}. Detection time is when this project saw the text, never the moment of injury.`
      : 'No alerts logged yet. The server writes here on every scan; an empty log is not an all-clear.';
  }
  const policy = $('log-policy');
  if (policy) policy.textContent = state.alertLog?.policy ?? 'Append-only log of everything this project has seen.';
  box.replaceChildren(...(filtered.length
    ? filtered.slice(0, 120).map(entry => logEntryCard(entry, state.newIds.has(entry.id)))
    : [notice('Nothing matches this filter yet.')]));
}

function wireLogTools() {
  const exportButton = $('export-log');
  if (exportButton) {
    exportButton.addEventListener('click', () => {
      const payload = { exportedAt: new Date().toISOString(), serverEntries: state.alertLog?.entries?.length ?? 0,
        sessionEntries: state.sessionLog.length, entries: mergedLog() };
      const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
      const link = el('a');
      link.href = URL.createObjectURL(blob);
      link.download = `sideline-signal-alert-log-${new Date().toISOString().slice(0, 19).replace(/:/g, '')}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    });
  }
  const clearButton = $('clear-log');
  if (clearButton) {
    clearButton.addEventListener('click', () => {
      state.sessionLog = [];
      state.newIds = new Set();
      saveSessionLog();
      renderLog();
    });
  }
  const notifyButton = $('notify-button');
  if (notifyButton) notifyButton.addEventListener('click', enableAlerts);
}

/* ------------------------------------------------------------------ live lanes */
async function fetchJSON(url, timeoutMs = 9_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = performance.now();
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal, referrerPolicy: 'no-referrer' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return { payload, ms: Math.round(performance.now() - started) };
  } finally { clearTimeout(timer); }
}

function markLane(name, status, ms) {
  state.laneStatus[name] = status;
  state.laneCheckedAt[name] = new Date().toISOString();
  if (Number.isFinite(ms)) state.laneLatencyMs[name] = ms;
}

function currentWatchGames() {
  const status = state.scores?.status;
  if (status && status !== 'ok' && status !== 'partial') return [];
  return liveGames(state.scores?.games || [], Date.now());
}

function laneFromHeader(payload) {
  const sports = Array.isArray(payload?.sports) ? payload.sports : [];
  const leagues = sports.flatMap(sport => sport.leagues || []);
  const events = leagues.flatMap(league => league.events || []);
  return events.map(event => {
    const teams = (event.competitors || []).map(team => ({
      code: team.abbreviation || team.team?.abbreviation || '',
      score: team.score ?? '—',
      homeAway: team.homeAway || '',
    }));
    const phase = event.fullStatus?.type?.state || event.status || '';
    return {
      id: String(event.id || ''),
      name: event.shortName || event.name || '',
      date: event.date || '',
      phase: phase === 'in' ? 'live' : phase === 'post' ? 'final' : 'scheduled',
      detail: event.fullStatus?.type?.shortDetail || event.summary || '',
      clock: event.fullStatus?.displayClock || '',
      period: event.fullStatus?.displayPeriod || '',
      home: teams.find(team => team.homeAway === 'home')?.code || '',
      away: teams.find(team => team.homeAway === 'away')?.code || '',
      homeScore: teams.find(team => team.homeAway === 'home')?.score ?? null,
      awayScore: teams.find(team => team.homeAway === 'away')?.score ?? null,
    };
  }).filter(game => game.id && game.home && game.away);
}

// Walk any ESPN payload for an injuries array. Unknown shapes yield nothing:
// the page would rather stay silent than invent a status.
function collectInjuries(payload) {
  const out = [];
  const visit = (node, team, depth = 0) => {
    if (depth > 8 || node === null || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(item => visit(item, team, depth + 1)); return; }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'injuries' && Array.isArray(value)) {
        for (const item of value) {
          if (item && Array.isArray(item.injuries)) {
            visit({ injuries: item.injuries }, item.team?.abbreviation || item.displayName || team, depth + 1);
          } else if (item?.athlete || item?.name) {
            const name = item.athlete?.displayName || item.athlete?.fullName || item.name || '';
            const status = item.status || item.type?.description || '';
            if (!name || !status) continue;
            out.push({
              name, status: String(status),
              detail: String(item.detail || item.longComment || item.shortComment || ''),
              date: item.date || '', team: item.team?.abbreviation || team || '',
            });
          }
        }
      } else {
        visit(value, key === 'team' && node.abbreviation ? node.abbreviation : team, depth + 1);
      }
    }
  };
  visit(payload, '');
  return out;
}

function collectPlays(payload, limit = 200) {
  const plays = [];
  const visit = (node, depth = 0) => {
    if (depth > 10 || plays.length >= limit || node === null || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(item => visit(item, depth + 1)); return; }
    const text = node.text || node.shortText;
    if (typeof text === 'string' && text.trim() && (node.clock || node.wallclock)) {
      plays.push({
        text: text.trim(),
        wallclock: node.wallclock || '',
        period: node.period?.number ?? node.period ?? null,
        clock: node.clock?.displayValue ?? null,
      });
      if (plays.length >= limit) return;
    }
    Object.values(node).forEach(value => visit(value, depth + 1));
  };
  visit(payload);
  return plays;
}

function signalEntry({ lane, tier, text, sourceAt, evidence, team = '', player = '', signal, game = '' }) {
  const detectedAt = new Date().toISOString();
  return {
    id: `sig-${detectedAt.replace(/[:.-]/g, '')}-${Math.abs(hashCode(`${lane}|${text}`)) % 10_000_000}`,
    at: detectedAt, detectedAt,
    sourceAt: isoSeconds(sourceAt),
    latencySeconds: latencySeconds(detectedAt, sourceAt),
    kind: 'live-signal', tier, lane, subject: player || team || 'Live lane wording',
    text, quote: '', status: signal.status, evidence,
    player, team, opponent: '', gameDate: '',
    note: `Matched the phrase “${signal.phrase}” (${signal.label}). Wording from this lane is not a league or club statement.`,
    game,
  };
}

function hashCode(value) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) hash = (hash * 31 + value.charCodeAt(index)) | 0;
  return hash;
}

function laneCard(name, label, detail) {
  const status = state.laneStatus[name] || 'idle';
  const card = el('div', `lane-card lane-${status}`);
  const top = el('div', 'lane-card-top');
  top.append(el('span', 'lane-name', label), el('span', `lane-state lane-state-${status}`, status));
  card.append(top, el('p', 'lane-detail', detail));
  const stamp = state.laneCheckedAt[name];
  const latency = state.laneLatencyMs[name];
  card.append(el('p', 'lane-stamp', stamp
    ? `checked ${stampSeconds(stamp)}${Number.isFinite(latency) ? ` · ${latency} ms` : ''}`
    : 'not checked yet'));
  return card;
}

function renderLaneDashboard() {
  const box = $('lane-dashboard');
  if (!box) return;
  box.replaceChildren(
    laneCard('header', 'Scoreboard header (10 s)', 'Is a game live, and what is the clock?'),
    laneCard('summary', 'Game summary · injuries (20 s)', 'Provider status lines for players in that game.'),
    laneCard('plays', 'Play-by-play with wall-clock (20 s)', 'Each play, stamped to the second by the provider.'),
    laneCard('news', 'News feed (20 s)', 'Timestamped articles that use in-game wording.'),
  );
}

function signalCard(item) {
  const card = el('article', `live-signal signal-${item.signal.status}`);
  const head = el('div', 'live-signal-top');
  const who = item.teams?.length ? item.teams.join(' / ') : (item.player ? `${item.player} · ${item.team}` : 'League');
  head.append(el('span', 'live-badge', item.tier === 'partner' ? 'PARTNER FEED · UNVERIFIED' : 'UNOFFICIAL · UNVERIFIED'),
    el('span', 'live-time', `seen ${stampSeconds(item.detectedAt)}`));
  card.append(head, el('h4', '', who), el('p', 'live-text', item.text.length > 280 ? `${item.text.slice(0, 277)}…` : item.text));
  const meta = el('div', 'live-meta');
  meta.append(el('span', 'signal-chip', item.signal.label));
  if (item.published) meta.append(el('span', 'latency-chip', `provider timestamp ${stampSeconds(item.published)} · ${humanizeSeconds(latencySeconds(item.detectedAt, item.published))} later`));
  else if (item.sourceAt) meta.append(el('span', 'latency-chip', `provider timestamp ${stampSeconds(item.sourceAt)}`));
  else meta.append(el('span', 'latency-chip', 'this lane publishes no per-event timestamp'));
  if (item.url) meta.append(tierLink(item.url, 'Provider item ↗', item.tier));
  card.append(meta);
  const searches = el('div', 'social-links');
  for (const link of socialSearchLinks(item.player || '', item.teams?.[0] || '').slice(0, 4)) {
    searches.append(tierLink(link.url, link.name, 'unofficial'));
  }
  card.append(searches);
  card.append(el('p', 'microcopy', `Matched “${item.signal.phrase}” in ${item.lane}. Not a diagnosis, a severity score, or a return date.`));
  return card;
}

function renderLiveWatch() {
  const box = $('live-watch-feed');
  if (!box) return;
  const watch = currentWatchGames();
  const live = watch.filter(game => game.phase === 'live');
  const signals = rankSignals(state.liveSignals);
  const status = $('live-watch-status');
  if (status) {
    const laneText = name => ({ ok: 'ok', blocked: 'blocked', idle: 'idle', stale: 'stale' }[state.laneStatus[name]] || 'idle');
    status.textContent = `${live.length ? `${live.length} game(s) in progress` : `${watch.length} game(s) in the watch window`}`
      + ` · header ${laneText('header')} · summary ${laneText('summary')} · plays ${laneText('plays')} · news ${laneText('news')}`
      + (state.lastLaneCheck ? ` · last check ${stampSeconds(state.lastLaneCheck)}` : '');
  }
  const children = [];
  if (live.length) {
    const strip = el('div', 'live-games');
    for (const game of live) {
      const item = el('div', 'live-game');
      item.append(el('span', 'live-dot'), el('span', '', `${game.away} ${game.awayScore ?? '—'} · ${game.home} ${game.homeScore ?? '—'}`),
        el('span', 'live-clock', `${game.period || ''} ${game.clock || game.detail || ''}`.trim()));
      const searches = el('div', 'social-links');
      for (const link of socialSearchLinks('injury', `${game.away} ${game.home}`).slice(0, 4)) {
        searches.append(tierLink(link.url, link.name, 'unofficial'));
      }
      item.append(searches);
      strip.append(item);
    }
    children.push(strip);
  }
  if (signals.length) {
    children.push(el('h3', 'live-heading', `In-game wording found now (${signals.length})`));
    children.push(...signals.slice(0, 8).map(signalCard));
  } else if (state.laneStatus.news === 'ok' || state.laneStatus.summary === 'ok') {
    children.push(notice('No in-game injury wording in the partner lanes right now. An empty lane is not an all-clear: most in-game events are announced by clubs, not by these feeds.'));
  } else if ([state.laneStatus.header, state.laneStatus.news, state.laneStatus.summary].every(status => status === 'blocked')) {
    children.push(notice('The partner lanes could not be reached from this browser (offline, blocked, or cross-origin). The source-checked feed is unaffected; nothing here implies a player is healthy.'));
  } else {
    children.push(notice('Live watch is idle: it starts polling when a game is in progress and the scoreboard lane is healthy.'));
  }
  box.replaceChildren(...children);
}

async function pollLiveLanes() {
  const now = Date.now();
  if (!shouldWatchForInGame(state.scores?.games || [], now)) {
    state.laneStatus = { header: 'idle', news: 'idle', summary: 'idle', plays: 'idle' };
    state.liveSignals = [];
    renderLiveWatch();
    renderLaneDashboard();
    return;
  }
  const detectedAt = new Date().toISOString();
  state.lastLaneCheck = detectedAt;
  const signals = [];
  const gameIds = currentWatchGames().filter(game => game.phase === 'live').map(game => game.id);

  const [headerResult, newsResult] = await Promise.allSettled([fetchJSON(ESPN_HEADER), fetchJSON(ESPN_NEWS)]);
  if (headerResult.status === 'fulfilled') {
    const events = laneFromHeader(headerResult.value.payload);
    markLane('header', events.length ? 'ok' : 'empty', headerResult.value.ms);
    if (events.length) {
      const tracker = new Map((state.scores?.games || []).map(game => [game.id, game]));
      for (const event of events) {
        const existing = tracker.get(event.id);
        tracker.set(event.id, { ...(existing || {}), ...event, url: existing?.url || `https://www.espn.com/nfl/game/_/gameId/${event.id}` });
      }
      state.scores = { ...(state.scores || { version: 1 }), games: [...tracker.values()], laneCheckedAt: detectedAt, status: state.scores?.status || 'ok' };
      renderScores();
    }
  } else markLane('header', 'blocked');

  if (newsResult.status === 'fulfilled') {
    markLane('news', 'ok', newsResult.value.ms);
    const articles = Array.isArray(newsResult.value.payload?.articles) ? newsResult.value.payload.articles : [];
    state.partnerArticles = articles;
    for (const article of articles) {
      const text = `${article.headline || ''}. ${article.description || ''}`;
      const signal = detectInGameSignals(text);
      if (!signal || signal.weight < 3) continue;
      const teams = (article.categories || []).filter(category => category.type === 'team')
        .map(category => category.team?.abbreviation).filter(Boolean);
      signals.push(signalEntry({
        lane: 'ESPN news feed (browser lane)', tier: 'partner', text, sourceAt: article.published || article.lastModified || null,
        evidence: article.links?.web?.href || '', signal, team: teams.join('/'), game: '',
      }));
    }
  } else markLane('news', 'blocked');

  if (gameIds.length) {
    const summaries = await Promise.allSettled(gameIds.map(id => fetchJSON(ESPN_SUMMARY(id), 10_000)));
    let summaryOk = 0;
    summaries.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      summaryOk += 1;
      markLane('summary', 'ok', result.value.ms);
      const gameId = gameIds[index];
      for (const injury of collectInjuries(result.value.payload)) {
        const text = `${injury.name} — ${injury.status}. ${injury.detail}`.trim();
        const matches = detectAllSignals(text);
        if (!matches.length) continue;
        signals.push(signalEntry({
          lane: 'ESPN summary injuries section (browser lane)', tier: 'partner', text,
          sourceAt: injury.date || null, evidence: `https://www.espn.com/nfl/game/_/gameId/${gameId}`,
          signal: matches[0], team: injury.team, player: injury.name, game: gameId,
        }));
      }
    });
    if (!summaryOk) markLane('summary', 'blocked');

    const playsResults = await Promise.allSettled(gameIds.map(id => fetchJSON(ESPN_PLAYS(id), 10_000)));
    let playsOk = 0;
    playsResults.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      playsOk += 1;
      markLane('plays', 'ok', result.value.ms);
      const gameId = gameIds[index];
      for (const play of collectPlays(result.value.payload)) {
        const signal = detectInGameSignals(play.text);
        if (!signal) continue;
        signals.push(signalEntry({
          lane: 'ESPN play-by-play (browser lane)', tier: 'partner', text: play.text,
          sourceAt: play.wallclock || null, evidence: `https://www.espn.com/nfl/game/_/gameId/${gameId}`,
          signal, game: gameId,
        }));
      }
    });
    if (!playsOk) markLane('plays', 'blocked');
  }

  const deduped = signals.filter((item, index, all) => all.findIndex(other => other.id === item.id) === index);
  const added = remember(deduped);
  if (added) for (const item of deduped) state.newIds.add(item.id);
  state.liveSignals = rankSignals([...deduped, ...state.liveSignals]
    .filter((item, index, all) => all.findIndex(other => other.id === item.id) === index).slice(0, 40));
  if (state.notifications && added) {
    for (const item of deduped.filter(entry => signalWeight(entry) >= 4).slice(0, 3)) {
      try {
        new Notification('UNVERIFIED in-game wording (partner feed)', {
          body: `${item.subject} — “${item.status}”. Not a league or club statement yet; open the page for the source.`,
        });
      } catch { /* Permission may have been revoked. */ }
    }
  }
  renderLiveWatch();
  renderLaneDashboard();
  if (added) renderLog();
}

/* ------------------------------------------------------------------ reports */
function reportCard(row) {
  const card = el('article', 'report-card');
  card.id = `report-${row.id}`;
  const top = el('div', 'report-card-top');
  const heading = el('div', 'player-line');
  heading.append(el('span', 'player-initial', row.team));
  const title = el('div');
  const isNew = NEW_IDS.has(row.id);
  title.append(el('h3', 'player-title', isNew ? `${row.player} · NEW` : row.player),
    el('div', 'player-meta', `${row.position === '—' ? 'PLAYER' : row.position}  ·  ${row.team} vs ${row.opponent}  ·  ${day(row.gameDate)}`));
  heading.append(title);
  const pill = el('span', `status-pill ${row.outcome}`, OUTCOME_LABEL[row.outcome] || 'Unverified');
  top.append(heading, pill);
  card.append(top);
  const detail = el('p', 'report-detail');
  detail.append(el('strong', '', 'Reported area: '), document.createTextNode(row.injury), el('span', 'severity-note', ' · Clinical severity not rated'));
  if (row.automatic) detail.append(el('span', 'auto-mark', 'AUTOMATIC · NFL.COM'));
  if (row.promotion) detail.append(el('span', 'auto-mark', 'AUTO-MATCHED · CLUB PAGE'));
  card.append(detail);
  if (row.promotion) {
    card.append(el('p', 'microcopy', `Promoted automatically after ${row.promotion.reads} identical reads of the club's own sentence `
      + `(${stampSeconds(row.promotion.firstSeen)} → ${stampSeconds(row.promotion.lastSeen)}). The quote below is that sentence.`));
  }
  const grid = el('div', 'report-grid');
  const observation = el('div', 'report-cell');
  observation.append(el('span', 'cell-label', 'ON-FIELD / SIDELINE'), el('span', 'cell-value', row.observations.join(' · ') || 'No observation confirmed'));
  const update = el('div', 'report-cell');
  const last = [...row.claims].reverse().find(claim => claim.kind === 'followup');
  update.append(el('span', 'cell-label', last ? 'LATEST LINKED UPDATE' : 'AFTER THE GAME'),
    el('span', 'cell-value subtle', last ? last.text : 'No later availability update included in this record. Game outcome alone does not predict the next game.'),
    el('span', 'as-of', last ? `Reported ${day(last.date)}` : `Game report ${day(row.claims[0].date)}`));
  grid.append(observation, update);
  card.append(grid);
  const details = el('details', 'source-details');
  details.append(el('summary', '', `View ${row.claims.length} source-backed ${row.claims.length === 1 ? 'claim' : 'claims'} & links`));
  const list = el('ol', 'evidence-list');
  for (const claim of row.claims) {
    const item = el('li');
    item.append(el('div', 'evidence-head', `${claim.kind === 'followup' ? 'Later report' : claim.kind === 'observation' ? 'Observation' : 'Game report'} · ${day(claim.date)}`),
      el('p', '', claim.text), el('blockquote', '', `“${claim.quote}”`), trustedLink(claim.url, 'Read the official source ↗'));
    list.append(item);
  }
  details.append(list);
  card.append(details);
  return card;
}

function renderReports() {
  if (!state.archive) return;
  state.rows = mergeIncidents(state.archive.incidents, state.live?.incidents || []);
  const current = filterIncidents(state.rows, state.filter);
  const list = $('report-list');
  const expanded = new Set([...list.querySelectorAll('.report-card')].filter(card => card.querySelector('details')?.open).map(card => card.id));
  const focused = document.activeElement?.matches('summary') ? document.activeElement.closest('.report-card')?.id : null;
  list.replaceChildren(...(current.length ? current.map(reportCard) : [notice('No reports match these filters. Try another team or outcome.')]));
  for (const id of expanded) {
    const card = document.getElementById(id);
    if (card?.querySelector('details')) card.querySelector('details').open = true;
  }
  if (focused) document.getElementById(focused)?.querySelector('summary')?.focus({ preventScroll: true });
  $('count-total').textContent = String(state.archive.incidents.length);
  $('count-returned').textContent = String(state.archive.incidents.filter(row => row.outcome === 'returned').length);
  $('result-count').textContent = `${current.length} SHOWN`;
  $('coverage-copy').textContent = `${state.archive.scope} Last verified ${day(state.archive.verifiedOn)}.`;
}

function setupTeams() {
  if (!state.archive) return;
  const teams = [...new Set([...state.archive.incidents, ...(state.live?.incidents || [])].map(row => row.team))].sort();
  const select = $('team-filter');
  const selection = select.value;
  select.replaceChildren(el('option', '', 'All teams'));
  select.firstElementChild.value = 'all';
  for (const team of teams) {
    const option = el('option', '', team);
    option.value = team;
    select.append(option);
  }
  select.value = teams.includes(selection) ? selection : 'all';
}

/* ------------------------------------------------------------------ candidates */
function candidateCard(row) {
  const card = el('article', `candidate-card candidate-${row.promotion?.state || 'pending'}`);
  const top = el('div', 'candidate-top');
  top.append(el('span', 'candidate-club', `${row.club} · ${row.clubLabel}`));
  top.append(el('span', `candidate-state state-${row.promotion?.state || 'pending'}`, (row.promotion?.state || 'pending').toUpperCase()));
  top.append(el('span', 'candidate-reads', `${row.reads} read(s)`));
  card.append(top);
  card.append(el('h3', 'candidate-player', row.player));
  card.append(el('blockquote', '', `“${row.quote}”`));
  const meta = el('div', 'candidate-meta');
  meta.append(el('span', 'signal-chip', row.signal?.label || 'matched phrase'));
  meta.append(el('span', 'log-stamp', `first seen ${stampSeconds(row.firstSeen)}`));
  if (row.gameDate) meta.append(el('span', 'candidate-game', `${row.club} vs ${row.opponent} · ${day(row.gameDate)}`));
  if (row.article) meta.append(el('span', 'candidate-article', row.article));
  card.append(meta);
  const links = el('div', 'source-links');
  links.append(tierLink(row.url, 'Open the club page ↗', 'official'));
  card.append(links);
  card.append(el('p', 'microcopy', `Gate: ${row.promotion?.gate || 'pending'}. Auto-matched text is not in the verified master list.`));
  return card;
}

function renderCandidates() {
  const box = $('candidates-list');
  if (!box || !state.candidates) return;
  const rows = state.candidates.candidates || [];
  const promoted = rows.filter(row => row.promotion?.state === 'promoted').length;
  const count = $('count-candidates');
  if (count) count.textContent = `${rows.length} FOUND · ${promoted} PROMOTED`;
  const status = $('candidates-status');
  if (status) {
    status.textContent = rows.length
      ? `${rows.length} official club sentence(s) matched, ${promoted} already promoted into the master list. `
        + 'A row is promoted only after two identical reads, a resolvable game date and the club named in its own sentence.'
      : 'The club scanner has not recorded a match yet. It reads all 32 club newsrooms on every run; a blocked club is recorded, never skipped.';
  }
  const policy = $('candidates-policy');
  if (policy) policy.textContent = state.candidates.policy || '';
  box.replaceChildren(...(rows.length ? rows.slice(0, 60).map(candidateCard) : [notice('No auto-matched club sentences on file yet.')]));
}

/* ------------------------------------------------------------------ sources */
function sourceCard(entry) {
  const card = el('article', `source-card source-${entry.tier}`);
  const top = el('div', 'source-top');
  top.append(el('span', 'source-tier', tierLabel(entry.tier)),
    el('span', `source-status status-${entry.verification.status}`, entry.verification.status.replace(/-/g, ' ')));
  card.append(top);
  card.append(el('h4', '', entry.name), el('p', 'source-org', `${entry.org} · ${entry.role.replace(/-/g, ' ')}${entry.inGame ? ' · in-game capable' : ''}`));
  const chips = el('div', 'source-chips');
  chips.append(el('span', `source-chip access-${entry.access}`, `access: ${entry.access.replace(/-/g, ' ')}`));
  chips.append(el('span', 'source-chip', `latency: ${LATENCY_LABEL[entry.latencyClass] || entry.latencyClass}`));
  chips.append(el('span', 'source-chip', `timestamps: ${entry.timestampPrecision}`));
  if (entry.autoPublish) chips.append(el('span', 'source-chip chip-strong', 'may ground a verified row'));
  else chips.append(el('span', 'source-chip', 'never grounds a row'));
  card.append(chips);
  card.append(el('p', '', entry.what));
  const facts = el('dl', 'source-facts');
  facts.append(el('dt', '', 'Can prove'), el('dd', '', entry.proves));
  facts.append(el('dt', '', 'Expected latency'), el('dd', '', entry.latency));
  facts.append(el('dt', '', 'Checked'), el('dd', '', `${entry.verification.checkedOn || 'not re-checked this session'} — ${entry.verification.method}`));
  card.append(facts);
  const links = el('div', 'source-links');
  links.append(tierLink(entry.url, 'Open the source ↗', entry.tier));
  if (entry.verification.evidence && entry.verification.evidence !== entry.url) {
    links.append(tierLink(entry.verification.evidence, 'Probe evidence ↗', entry.tier));
  }
  card.append(links);
  card.append(el('p', 'microcopy', entry.notes));
  return card;
}

function renderSources() {
  const box = $('sources-board');
  if (!box || !state.sources) return;
  const filtered = filterSources(state.sources.sources, state.sourceFilter);
  const count = $('source-count');
  if (count) count.textContent = `${filtered.length} of ${state.sources.sources.length} lanes`;
  const groups = groupSources(filtered);
  const children = [];
  for (const group of groups) {
    children.push(el('h3', `sources-heading tier-heading-${group.category}`, `${group.label} · ${group.rows.length}`));
    const list = el('div', 'source-rows');
    for (const entry of group.rows) list.append(sourceCard(entry));
    children.push(list);
  }
  if (!groups.length) children.push(notice('No lane matches these filters.'));
  children.push(el('p', 'microcopy', state.sources.policy.rule));
  box.replaceChildren(...children);
}

function setupSourceFilters() {
  const categories = [...new Set((state.sources?.sources || []).map(lane => lane.category))];
  const select = $('source-category');
  if (!select) return;
  select.replaceChildren(el('option', '', 'All categories'));
  select.firstElementChild.value = 'all';
  for (const category of categories.sort()) {
    const option = el('option', '', SOURCE_CATEGORY_LABEL[category] || category);
    option.value = category;
    select.append(option);
  }
}

/* ------------------------------------------------------------------ leads & review */
function renderLeads() {
  const box = $('leads-list');
  if (!box || !state.leads) return;
  const count = $('count-leads');
  if (count) count.textContent = String(state.leads.leads.length);
  const cards = state.leads.leads.map(lead => {
    const card = el('article', 'lead-card');
    const top = el('div', 'lead-top');
    top.append(el('span', 'lead-tier', tierLabel(lead.source.tier)),
      el('span', 'lead-team', `${lead.team}${lead.opponent ? ` vs ${lead.opponent}` : ''}${lead.gameDate ? ` · ${day(lead.gameDate)}` : ''}`));
    card.append(top);
    card.append(el('h3', '', `${lead.subject} — ${lead.reportedStatus}`), el('p', 'lead-text', lead.text));
    const meta = el('div', 'lead-meta');
    meta.append(el('span', '', `${lead.source.name} · captured ${day(lead.capturedOn)}`), tierLink(lead.source.url, 'Read the outlet ↗', lead.source.tier));
    card.append(meta, el('p', 'microcopy', `To promote: ${lead.verifyNext}`), el('p', 'microcopy', lead.notes));
    if (lead.duplicateOf) card.append(el('p', 'microcopy', `Already in the verified list as ${lead.duplicateOf} — kept here only as a re-check lead.`));
    return card;
  });
  if (!cards.length) box.replaceChildren(notice('No unofficial leads captured.'));
  else box.replaceChildren(el('p', 'microcopy', state.leads.label), ...cards);
}

function renderReview() {
  if (!state.review) return;
  const all = [...state.review.flags, ...(state.live?.flags || [])];
  $('count-flags').textContent = String(all.length);
  $('review-list').replaceChildren(...(all.length ? all.map((flag, index) => {
    const card = el('article', 'review-card');
    const head = el('div', 'review-card-top');
    head.append(el('span', 'review-label', flag.disposition === 'held' ? 'HELD FROM MASTER' : flag.disposition === 'annotated' ? 'ANNOTATED IN MASTER' : 'AUTOMATED CHECK'),
      el('span', 'review-count', String(index + 1).padStart(2, '0')));
    card.append(head, el('h3', '', flag.subject), el('p', '', flag.reason));
    const links = el('div', 'review-links');
    for (const [i, url] of (flag.links || (flag.url ? [flag.url] : [])).entries()) links.append(trustedLink(url, `Review source ${i + 1} ↗`, 'review'));
    card.append(links);
    return card;
  }) : [notice('No source irregularities are currently recorded. That does not establish complete coverage.')]));
}

/* ------------------------------------------------------------------ scores & health */
function renderScores() {
  const box = $('score-cards');
  if (!state.scores || state.scores.status === 'unavailable' || state.scores.status === 'not_checked') {
    box.replaceChildren(notice('Score sync is unavailable or has not run yet. No scores or schedule are being guessed. Open the NFL scoreboard above for the latest.'));
    $('scores-meta').textContent = 'Schedule unavailable in this snapshot';
    return;
  }
  const selection = selectScoreGames(state.scores.games);
  const stale = freshness(state.scores) !== 'ok';
  $('scores-meta').textContent = `${selection.label} · ${stale ? 'score feed delayed / partial' : `score feed checked ${stampSeconds(state.scores.checkedAt)}`}`;
  if (!selection.games.length) {
    box.replaceChildren(notice('No upcoming NFL games in the synced week. Check the full scoreboard for other dates.'));
    return;
  }
  box.replaceChildren(...selection.games.map(game => {
    const card = el('a', 'score-card');
    if (/^https:\/\/www\.espn\.com\/nfl\/game\/_\/gameId\/\d+$/.test(game.url)) {
      card.href = game.url;
      card.target = '_blank';
      card.rel = 'noopener noreferrer';
    }
    const top = el('div', 'score-card-top');
    top.append(el('span', '', game.phase === 'live' ? 'IN PROGRESS' : game.phase === 'final' ? 'FINAL' : 'UPCOMING'),
      el('span', game.phase === 'live' ? 'score-live' : '', game.phase === 'scheduled' ? stampSeconds(game.date) : game.detail || game.phase));
    card.append(top);
    for (const [club, score] of [[game.away, game.awayScore], [game.home, game.homeScore]]) {
      const line = el('div', 'score-row');
      const label = el('div', 'team-label');
      label.append(el('span', 'team-square', club.slice(0, 2)), el('span', '', club));
      line.append(label, el('span', 'score-value', score ?? '—'));
      card.append(line);
    }
    card.append(el('div', 'score-card-bottom', 'ESPN scores only · not an injury source'));
    return card;
  }));
}

function renderHealth() {
  const status = freshness(state.live);
  const names = { ok: 'Source check current', waiting: 'Awaiting game roundup', degraded: 'Source check limited', stale: 'Collector delayed', not_checked: 'Not checked yet' };
  $('feed-state').textContent = names[status];
  const watchStamp = state.watch?.checkedAt ? ` · watcher ${stampSeconds(state.watch.checkedAt)}` : '';
  $('last-check').textContent = state.live?.status === 'unavailable'
    ? 'Published source feed unavailable — no all-clear implied'
    : state.live?.checkedAt
      ? `NFL.com checked ${stampSeconds(state.live.checkedAt)} · ${state.live?.discovery?.recentRoundups || 0} recent roundup(s)${watchStamp}`
      : 'Waiting for the first scheduled check';
  $('feed-indicator').className = `metric-icon ${status === 'ok' ? 'mint' : status === 'degraded' || status === 'stale' ? 'amber' : 'pale'}`;
  $('feed-indicator').textContent = status === 'ok' ? '✓' : status === 'degraded' || status === 'stale' ? '!' : '◌';
}

/* ------------------------------------------------------------------ polling */
async function json(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(dataURL(path, document.baseURI), { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}

const validArchive = value => value?.version === 1 && typeof value.scope === 'string' && Array.isArray(value.incidents)
  && value.incidents.every(row => typeof row.id === 'string' && typeof row.player === 'string' && Array.isArray(row.claims)
    && row.claims.length && row.claims.every(claim => typeof claim.date === 'string' && typeof claim.quote === 'string' && typeof claim.url === 'string'));
const validReview = value => value?.version === 1 && Array.isArray(value.flags);
const validLive = value => value?.version === 1 && Array.isArray(value.incidents) && Array.isArray(value.flags) && typeof value.status === 'string';
const validScores = value => value?.version === 1 && Array.isArray(value.games) && typeof value.status === 'string';
const validSources = value => value?.version === 1 && Array.isArray(value.sources) && value.sources.length > 0
  && value.sources.every(entry => typeof entry.id === 'string' && ['official', 'partner', 'unofficial'].includes(entry.tier)
    && typeof entry.role === 'string' && typeof entry.name === 'string' && typeof entry.url === 'string'
    && typeof entry.category === 'string' && typeof entry.latencyClass === 'string');
const validLeads = value => value?.version === 1 && Array.isArray(value.leads)
  && value.leads.every(lead => typeof lead.id === 'string' && typeof lead.subject === 'string' && typeof lead.text === 'string'
    && lead.source && typeof lead.source.url === 'string' && lead.source.tier !== 'official');
const validLog = value => value?.version === 1 && Array.isArray(value.entries);
const validCandidates = value => value?.version === 1 && Array.isArray(value.candidates);
const validWatch = value => value?.version === 1 && Array.isArray(value.signals);

async function poll() {
  const previousLive = state.live?.incidents || [];
  const beforeIncidents = JSON.stringify(previousLive.map(row => [row.id, row.injury, row.outcome]));
  const beforeLog = (state.alertLog?.entries || []).length;
  const results = await Promise.allSettled([
    json('./data/live.json'), json('./data/scoreboard.json'), json('./data/alert-log.json'),
    json('./data/candidates.json'), json('./data/watch.json'),
  ]);
  if (results[0].status === 'fulfilled' && validLive(results[0].value)) {
    state.live = results[0].value;
    if (state.ready && state.notifications) {
      for (const item of newAutoAlerts(previousLive, state.live.incidents || [])) {
        try {
          new Notification('New NFL.com game report (official)', {
            body: `${item.player} · ${OUTCOME_LABEL[item.outcome]} in ${item.team} vs ${item.opponent}. Open the page for the linked evidence.`,
          });
        } catch { /* Permission may be revoked. */ }
      }
    }
  } else {
    state.live = { ...(state.live || { incidents: [], flags: [] }), checkedAt: new Date().toISOString(), status: 'unavailable', warnings: ['Published file could not be refreshed'] };
  }
  if (results[1].status === 'fulfilled' && validScores(results[1].value)) state.scores = results[1].value;
  else state.scores = { ...(state.scores || { games: [] }), status: 'unavailable' };
  if (results[2].status === 'fulfilled' && validLog(results[2].value)) {
    state.alertLog = results[2].value;
    const fresh = (state.alertLog.entries || []).filter(entry => !state.sessionLog.some(seen => seen.id === entry.id));
    // Server entries are remembered in the session too, so "new since your last
    // visit" survives a refresh even when the server file has been rotated.
    if (fresh.length) {
      state.sessionLog = [...fresh, ...state.sessionLog].slice(0, SESSION_CAP);
      saveSessionLog();
      const newly = newSince(fresh, state.lastVisit);
      for (const entry of newly) state.newIds.add(entry.id);
      if (state.ready && state.notifications) {
        for (const entry of newly.slice(0, 3)) {
          try {
            new Notification(`[${entry.tier.toUpperCase()}] ${entry.subject}`, { body: `${entry.text} — ${entry.lane}` });
          } catch { /* Permission may be revoked. */ }
        }
      }
    }
  }
  if (results[3].status === 'fulfilled' && validCandidates(results[3].value)) state.candidates = results[3].value;
  if (results[4].status === 'fulfilled' && validWatch(results[4].value)) state.watch = results[4].value;

  if (state.archive && (!state.ready || beforeIncidents !== JSON.stringify((state.live?.incidents || []).map(row => [row.id, row.injury, row.outcome])))) {
    setupTeams(); renderReports();
  }
  if (state.review && (!state.ready || beforeLog !== (state.alertLog?.entries || []).length)) renderReview();
  renderHealth();
  renderScores();
  renderCandidates();
  renderLog();
  renderLaneDashboard();
  renderLiveWatch();
}

/* ------------------------------------------------------------------ notifications */
function updateNotificationButton() {
  const button = $('notify-button');
  if (!button) return;
  if (!('Notification' in window) || !window.isSecureContext) {
    button.textContent = 'Browser alerts unavailable here';
    button.disabled = true;
    return;
  }
  const permission = Notification.permission;
  state.notifications = permission === 'granted' && window.localStorage?.getItem('sideline-alerts-enabled') === 'yes';
  button.textContent = state.notifications ? 'Browser alerts enabled ✓'
    : permission === 'denied' ? 'Alerts blocked in browser settings' : 'Enable browser alerts ↗';
  button.disabled = permission === 'denied';
}

async function enableAlerts() {
  if (!('Notification' in window) || !window.isSecureContext) return;
  try {
    const choice = await Notification.requestPermission();
    if (choice === 'granted') {
      localStorage.setItem('sideline-alerts-enabled', 'yes');
      state.notifications = true;
      $('notification-info').textContent = 'Enabled. Alerts name the source tier in the body; nothing from a partner or unofficial lane is ever described as official.';
    }
  } catch {
    $('notification-info').textContent = 'Browser permissions are unavailable in this preview. RSS and the alert log remain available.';
  }
  updateNotificationButton();
}

/* ------------------------------------------------------------------ wire up */
function wireFilters() {
  $('search').addEventListener('input', event => { state.filter.query = event.target.value; renderReports(); });
  $('team-filter').addEventListener('change', event => { state.filter.team = event.target.value; renderReports(); });
  $('outcome-filters').addEventListener('click', event => {
    const button = event.target.closest('button[data-outcome]');
    if (!button) return;
    state.filter.outcome = button.dataset.outcome;
    for (const tab of $('outcome-filters').querySelectorAll('button')) {
      const on = tab === button;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-pressed', String(on));
    }
    renderReports();
  });
  const logFilters = document.querySelector('.log-filters');
  if (logFilters) {
    logFilters.addEventListener('click', event => {
      const button = event.target.closest('button[data-log]');
      if (!button) return;
      state.logFilter = button.dataset.log;
      for (const tab of logFilters.querySelectorAll('button')) {
        const on = tab === button;
        tab.classList.toggle('active', on);
        tab.setAttribute('aria-pressed', String(on));
      }
      renderLog();
    });
  }
  for (const [id, key] of [['source-search', 'query'], ['source-tier', 'tier'], ['source-category', 'category'], ['source-access', 'access']]) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('input', event => { state.sourceFilter[key] = event.target.value; renderSources(); });
    node.addEventListener('change', event => { state.sourceFilter[key] = event.target.value; renderSources(); });
  }
}

async function init() {
  $('today-label').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).format(new Date()).toUpperCase();
  state.sessionLog = loadSessionLog();
  state.lastVisit = window.localStorage?.getItem(VISIT_KEY) ?? null;
  try { window.localStorage?.setItem(VISIT_KEY, new Date().toISOString()); } catch { /* private mode */ }
  wireFilters();
  wireLogTools();
  try { updateNotificationButton(); } catch { $('notify-button').disabled = true; }

  const [archive, review, sources, leads] = await Promise.allSettled([
    json('./data/archive.json'), json('./data/review.json'), json('./data/sources.json'), json('./data/leads.json'),
  ]);
  if (sources.status === 'fulfilled' && validSources(sources.value)) { state.sources = sources.value; setupSourceFilters(); }
  else $('sources-board')?.replaceChildren(notice('The source registry could not be loaded. Treat every unlabelled item as unverified.'));
  if (leads.status === 'fulfilled' && validLeads(leads.value)) state.leads = leads.value;
  else $('leads-list')?.replaceChildren(notice('The unofficial lead list could not be loaded.'));
  if (archive.status === 'fulfilled' && validArchive(archive.value)) state.archive = archive.value;
  else {
    $('report-list').replaceChildren(notice('Verified archive could not be loaded. Do not interpret this as no injuries; retry later.'));
    $('coverage-copy').textContent = 'Archive unavailable';
  }
  if (review.status === 'fulfilled' && validReview(review.value)) state.review = review.value;
  else $('review-list').replaceChildren(notice('Review queue could not be loaded.'));
  renderSources();
  renderLeads();
  await poll();
  await pollLiveLanes();
  state.ready = true;
  window.setInterval(poll, 60_000);
  // The live lanes run on their own clocks: the header lane every 10 seconds so
  // a kickoff is noticed immediately, the game lanes every 20 seconds.
  window.setInterval(async () => { if (shouldWatchForInGame(state.scores?.games || [], Date.now())) await pollLiveLanes(); }, LANE_HEADER_MS);
  window.setInterval(async () => { if (currentWatchGames().some(game => game.phase === 'live')) await pollLiveLanes(); }, LANE_GAME_MS);
  window.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
}
init();

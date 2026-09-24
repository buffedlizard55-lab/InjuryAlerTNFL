import {
  OUTCOME_LABEL, mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts, dataURL,
  tierLabel, detectInGameSignals, rankSignals, signalWeight, humanizeSeconds, latencySeconds,
  liveGames, shouldWatchForInGame, socialSearchLinks, eligiblePartnerAlerts,
} from './domain.mjs';

const $ = id => document.getElementById(id);
const state = {
  archive: null, review: null, live: null, scores: null, sources: null, leads: null, rows: [],
  filter: { query: '', team: 'all', outcome: 'all' }, ready: false, notifications: false,
  // Live lanes. `laneStatus` is honest about every lane: ok, blocked (the browser
  // could not reach it) or idle (no game in the watch window).
  laneStatus: { header: 'idle', news: 'idle' }, liveSignals: [], partnerArticles: [], lastLaneCheck: null,
};
const ESPN_HEADER = 'https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=football&league=nfl';
const ESPN_NEWS = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=25';
const LIVE_LANE_HEADER_MS = 20_000;
const LIVE_LANE_NEWS_MS = 45_000;
const validArchive = value => value?.version === 1 && typeof value.scope === 'string' && Array.isArray(value.incidents)
  && value.incidents.every(row => typeof row.id === 'string' && typeof row.player === 'string' && Array.isArray(row.claims)
    && row.claims.length && row.claims.every(claim => typeof claim.date === 'string' && typeof claim.quote === 'string' && typeof claim.url === 'string'));
const validReview = value => value?.version === 1 && Array.isArray(value.flags);
const validLive = value => value?.version === 1 && Array.isArray(value.incidents) && Array.isArray(value.flags) && typeof value.status === 'string';
const validScores = value => value?.version === 1 && Array.isArray(value.games) && typeof value.status === 'string';
const validSources = value => value?.version === 1 && Array.isArray(value.sources) && value.sources.length > 0
  && value.sources.every(entry => typeof entry.id === 'string' && ['official', 'partner', 'unofficial'].includes(entry.tier)
    && typeof entry.role === 'string' && typeof entry.name === 'string' && typeof entry.url === 'string');
const validLeads = value => value?.version === 1 && Array.isArray(value.leads)
  && value.leads.every(lead => typeof lead.id === 'string' && typeof lead.subject === 'string' && typeof lead.text === 'string'
    && lead.source && typeof lead.source.url === 'string' && lead.source.tier !== 'official');
const day = value => {
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(date) : 'Date unverified';
};
const instant = value => {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date) : 'Time unavailable';
};
function el(tag, className = '', content = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== '') node.textContent = String(content);
  return node;
}
function trustedLink(url, label, type = 'news') {
  const link = el('a', '', label);
  let valid = false;
  try {
    const parsed = new URL(url);
    const allowed = [
      'www.nfl.com', 'www.dallascowboys.com', 'www.denverbroncos.com',
      'www.buffalobills.com', 'www.atlantafalcons.com', 'www.baltimoreravens.com',
      'www.panthers.com', 'www.chicagobears.com', 'www.bengals.com',
      'www.clevelandbrowns.com', 'www.detroitlions.com', 'www.packers.com',
      'www.houstontexans.com', 'www.colts.com', 'www.jaguars.com', 'www.chiefs.com',
      'www.chargers.com', 'www.rams.com', 'www.raiders.com', 'www.dolphins.com',
      'www.vikings.com', 'www.patriots.com', 'www.saints.com', 'www.giants.com',
      'www.nyjets.com', 'www.newyorkjets.com', 'www.jets.com', 'www.eagles.com', 'www.philadelphiaeagles.com', 'www.steelers.com',
      // Real hosts for clubs whose newsroom domain differs from the short form; these three
      // were missing from this list even after the schema was fixed, which broke the link to
      // the Saints recap that grounds Martin Emerson Jr. tests/test_pipeline.py now checks
      // that this allowlist covers every host the schema trusts.
      'www.neworleanssaints.com', 'www.miamidolphins.com', 'www.tennesseetitans.com',
      'www.49ers.com', 'www.seahawks.com', 'www.buccaneers.com', 'www.titans.com',
      'www.commanders.com', 'www.azcardinals.com', 'www.cardinals.com',
    ];
    const hostOk = allowed.includes(parsed.hostname) || parsed.hostname.endsWith('.nfl.com') || (parsed.hostname.startsWith('www.') && (parsed.hostname.endsWith('broncos.com') || parsed.hostname.endsWith('bills.com')));
    valid = parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port && !parsed.search && !parsed.hash
      && hostOk
      && (parsed.pathname.startsWith('/news/') || parsed.pathname.startsWith('/videos/') || parsed.pathname.startsWith('/game-day/')
        || (type === 'review' && parsed.hostname === 'www.nfl.com' && parsed.pathname.startsWith('/players/')));
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
function notice(text) { return el('p', 'notice', text); }
// Partner and unofficial links are displayed with their tier and never treated as evidence.
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
  // Pass 5 (September 24, 2026): incidents newly promoted to the verified archive.
  '2026-09-13-atl-a-j-terrell', '2026-09-13-cle-zion-johnson', '2026-09-13-phi-cooper-dejean',
  '2026-09-13-phi-jalen-carter', '2026-09-20-chi-tyson-bagent', '2026-09-20-nyj-kiko-mauigoa',
  '2026-09-20-nyj-mason-taylor', '2026-09-20-sf-romello-height',
  // Pass 6: both rows came from club pages rather than league roundups.
  '2026-09-20-no-martin-emerson-jr', '2026-09-20-min-brett-thorson',
]);

function reportCard(row) {
  const card = el('article', 'report-card');
  card.id = `report-${row.id}`;
  const top = el('div', 'report-card-top');
  const heading = el('div', 'player-line');
  heading.append(el('span', 'player-initial', row.team));
  const title = el('div');
  const isNew = NEW_IDS.has(row.id);
  const titleText = isNew ? `${row.player} · NEW` : row.player;
  title.append(el('h3', 'player-title', titleText), el('div', 'player-meta', `${row.position === '—' ? 'PLAYER' : row.position}  ·  ${row.team} vs ${row.opponent}  ·  ${day(row.gameDate)}`));
  heading.append(title);
  const pill = el('span', `status-pill ${row.outcome}`, OUTCOME_LABEL[row.outcome] || 'Unverified');
  if (isNew) {
    const newBadge = el('span', 'auto-mark', 'NEW · 5TH PASS');
    newBadge.style.marginLeft = '8px';
    pill.append(newBadge);
  }
  top.append(heading, pill);
  card.append(top);
  const detail = el('p', 'report-detail');
  detail.append(el('strong', '', 'Reported area: '), document.createTextNode(row.injury), el('span', 'severity-note', ' · Clinical severity not rated'));
  if (row.automatic) detail.append(el('span', 'auto-mark', 'AUTOMATIC · NFL.COM'));
  card.append(detail);
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
  $('coverage-copy').textContent = `${state.archive.scope} Last verified ${day(state.archive.verifiedOn)}. Automatically matched reports appear separately when available.`;
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
function renderReview() {
  if (!state.review) return;
  const all = [...state.review.flags, ...(state.live?.flags || [])];
  $('count-flags').textContent = String(all.length);
  $('review-list').replaceChildren(...(all.length ? all.map((flag, index) => {
    const card = el('article', 'review-card');
    const head = el('div', 'review-card-top');
    head.append(el('span', 'review-label', flag.disposition === 'held' ? 'HELD FROM MASTER' : flag.disposition === 'annotated' ? 'ANNOTATED IN MASTER' : 'AUTOMATED CHECK'), el('span', 'review-count', String(index + 1).padStart(2, '0')));
    card.append(head, el('h3', '', flag.subject), el('p', '', flag.reason));
    const links = el('div', 'review-links');
    for (const [i, url] of (flag.links || (flag.url ? [flag.url] : [])).entries()) links.append(trustedLink(url, `Review source ${i + 1} ↗`, 'review'));
    card.append(links);
    return card;
  }) : [notice('No source irregularities are currently recorded. That does not establish complete coverage.')]));
}
function renderHealth() {
  const status = freshness(state.live);
  const names = { ok: 'Source check current', waiting: 'Awaiting game roundup', degraded: 'Source check limited', stale: 'Collector delayed', not_checked: 'Not checked yet' };
  $('feed-state').textContent = names[status];
  $('last-check').textContent = state.live?.status === 'unavailable' ? 'Published source feed unavailable — no all-clear implied'
    : state.live?.checkedAt ? `NFL.com checked ${instant(state.live.checkedAt)} · ${state.live?.discovery?.recentRoundups || 0} recent roundup(s)` : 'Waiting for the first scheduled check';
  $('feed-indicator').className = `metric-icon ${status === 'ok' ? 'mint' : status === 'degraded' || status === 'stale' ? 'amber' : 'pale'}`;
  $('feed-indicator').textContent = status === 'ok' ? '✓' : status === 'degraded' || status === 'stale' ? '!' : '◌';
}
function renderScores() {
  const box = $('score-cards');
  if (!state.scores || state.scores.status === 'unavailable' || state.scores.status === 'not_checked') {
    box.replaceChildren(notice('Score sync is unavailable or has not run yet. No scores or schedule are being guessed. Open the NFL scoreboard above for the latest.'));
    $('scores-meta').textContent = 'Schedule unavailable in this snapshot';
    return;
  }
  const selection = selectScoreGames(state.scores.games);
  const stale = freshness(state.scores) !== 'ok';
  const message = `${selection.label} · ${stale ? 'score feed delayed / partial' : 'score feed checked ' + instant(state.scores.checkedAt)}`;
  $('scores-meta').textContent = message;
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
      el('span', game.phase === 'live' ? 'score-live' : '', game.phase === 'scheduled' ? instant(game.date) : game.detail || game.phase));
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
async function json(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(dataURL(path, document.baseURI), { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}

function updateNotificationButton() {
  const button = $('notify-button');
  if (!('Notification' in window) || !window.isSecureContext) {
    button.textContent = 'Browser alerts unavailable here';
    button.disabled = true;
    return;
  }
  const permission = Notification.permission;
  state.notifications = permission === 'granted' && window.localStorage?.getItem('sideline-alerts-enabled') === 'yes';
  button.textContent = state.notifications ? 'Browser alerts enabled ✓' : permission === 'denied' ? 'Alerts blocked in browser settings' : 'Enable browser alerts ↗';
  button.disabled = permission === 'denied';
}
async function enableAlerts() {
  if (!('Notification' in window) || !window.isSecureContext) return;
  try {
    const choice = await Notification.requestPermission();
    if (choice === 'granted') {
      localStorage.setItem('sideline-alerts-enabled', 'yes');
      state.notifications = true;
      $('notification-info').textContent = 'Enabled. Only new game reports discovered while this page is open can trigger notices. No archive backfill.';
    }
  } catch {
    $('notification-info').textContent = 'Browser permissions are unavailable in this preview. RSS remains available.';
  }
  updateNotificationButton();
}
const incidentSignature = rows => JSON.stringify((rows || []).map(row => [row.id, row.injury, row.outcome, row.observations, row.claims]));
const reviewSignature = rows => JSON.stringify(rows || []);
async function poll() {
  const previous = state.live?.incidents || [];
  const beforeIncidents = incidentSignature(previous);
  const beforeFlags = reviewSignature(state.live?.flags);
  const results = await Promise.allSettled([json('./data/live.json'), json('./data/scoreboard.json')]);
  if (results[0].status === 'fulfilled' && validLive(results[0].value)) {
    state.live = results[0].value;
    if (state.ready && state.notifications) {
      for (const item of newAutoAlerts(previous, state.live.incidents || [])) {
        try { new Notification('New NFL.com game report', { body: `${item.player} · ${OUTCOME_LABEL[item.outcome]} in ${item.team} vs ${item.opponent}. Open the page for the linked evidence.` }); } catch { /* Permission may be revoked. */ }
      }
    }
  } else {
    state.live = { ...(state.live || { incidents: [], flags: [] }), checkedAt: new Date().toISOString(), status: 'unavailable', warnings: ['Published file could not be refreshed'] };
  }
  if (results[1].status === 'fulfilled' && validScores(results[1].value)) state.scores = results[1].value;
  else state.scores = { ...(state.scores || { games: [] }), status: 'unavailable' };
  if (state.archive && (!state.ready || beforeIncidents !== incidentSignature(state.live?.incidents))) { setupTeams(); renderReports(); }
  if (state.review && (!state.ready || beforeFlags !== reviewSignature(state.live?.flags))) renderReview();
  renderHealth();
  renderScores();
  // A refreshed scoreboard can open or close the in-game watch window, so the
  // priority rail is re-rendered on every poll, not only on its own timer.
  renderLiveWatch();
}
async function init() {
  $('today-label').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).format(new Date()).toUpperCase();
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
  $('notify-button').addEventListener('click', enableAlerts);
  try { updateNotificationButton(); } catch { $('notify-button').disabled = true; }
  const [archive, review, sources, leads] = await Promise.allSettled([
    json('./data/archive.json'), json('./data/review.json'), json('./data/sources.json'), json('./data/leads.json'),
  ]);
  if (sources.status === 'fulfilled' && validSources(sources.value)) state.sources = sources.value;
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
  // The in-game lane runs on its own clock: a live game is the highest-priority
  // thing on this page, so it is the only lane that polls faster than a minute.
  window.setInterval(pollLiveLanes, LIVE_LANE_HEADER_MS);
  window.setInterval(async () => { if (state.laneStatus.news === 'ok') await pollLiveLanes(); }, LIVE_LANE_NEWS_MS);
}
init();

/* ---------------------------------------------------------------------------
   LIVE IN-GAME WATCH — the lowest-latency lane this page can run.

   Priority: an in-game event during a game that is being played right now is
   the first thing the page looks for and the first thing it shows. Two lanes
   are polled directly from the browser:

     * ESPN scoreboard header (every 20s)  -> is a game live, period and clock
     * ESPN NFL news feed     (every 45s)  -> timestamped published articles

   Both are partner feeds, not league or club publications. Nothing they return
   is ever presented as verified: the panel says PARTNER FEED and UNVERIFIED,
   carries the provider's own timestamp, and links out. If the browser cannot
   reach a lane (offline, blocked, CORS), the lane reports that instead of
   going quiet.
   --------------------------------------------------------------------------- */
async function fetchJSON(url, timeoutMs = 10_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal, referrerPolicy: 'no-referrer' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
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
    const state_ = event.fullStatus?.type?.state || event.status || '';
    return {
      id: String(event.id || ''),
      name: event.shortName || event.name || '',
      date: event.date || '',
      phase: state_ === 'in' ? 'live' : state_ === 'post' ? 'final' : 'scheduled',
      detail: event.fullStatus?.type?.shortDetail || event.summary || '',
      clock: event.fullStatus?.displayClock || '',
      period: event.fullStatus?.displayPeriod || '',
      home: teams.find(team => team.homeAway === 'home')?.code || '',
      away: teams.find(team => team.homeAway === 'away')?.code || '',
      homeScore: teams.find(team => team.homeAway === 'home')?.score ?? null,
      awayScore: teams.find(team => team.homeAway === 'away')?.score ?? null,
    };
  });
}

function laneFromNews(articles, detectedAt) {
  return (articles || []).flatMap(article => {
    const text = `${article.headline || ''}. ${article.description || ''}`;
    const signal = detectInGameSignals(text);
    if (!signal) return [];
    const teams = (article.categories || [])
      .filter(category => category.type === 'team')
      .map(category => category.team?.abbreviation)
      .filter(Boolean);
    return [{
      id: String(article.id || article.nowId || article.headline || ''),
      headline: article.headline || 'Untitled',
      text,
      signal,
      teams,
      published: article.published || article.lastModified || null,
      url: article.links?.web?.href || article.links?.mobile?.href || '',
      detectedAt,
      tier: 'partner',
      lane: 'ESPN NFL news feed',
    }];
  });
}

function signalCard(item) {
  const card = el('article', `live-signal signal-${item.signal.status}`);
  const head = el('div', 'live-signal-top');
  const who = item.teams?.length ? item.teams.join(' / ') : (item.player ? `${item.player} · ${item.team}` : 'League');
  head.append(el('span', 'live-badge', item.tier === 'partner' ? 'PARTNER FEED · UNVERIFIED' : 'UNOFFICIAL · UNVERIFIED'),
    el('span', 'live-time', item.published ? `provider timestamp ${instant(item.published)}` : `detected ${instant(item.detectedAt)}`));
  card.append(head);
  card.append(el('h4', '', who), el('p', 'live-text', item.text.length > 280 ? `${item.text.slice(0, 277)}…` : item.text));
  const meta = el('div', 'live-meta');
  meta.append(el('span', 'signal-chip', item.signal.status === 'out' ? 'OUT / will not return wording'
    : item.signal.status === 'returned' ? 'RETURNED wording'
    : item.signal.status === 'questionable' ? 'RETURN UNCERTAIN wording'
    : item.signal.observation || 'observation wording'));
  const latency = latencySeconds(item.detectedAt, item.published);
  if (latency !== null) meta.append(el('span', 'latency-chip', `saw it ${humanizeSeconds(latency)} after the provider published`));
  if (item.url) meta.append(tierLink(item.url, 'Provider item ↗', item.tier));
  card.append(meta);
  card.append(el('p', 'microcopy', `Matched the word “${item.signal.phrase}” in ${item.lane}. Wording from a partner feed is not a league or club statement, and this is not a diagnosis or a return date.`));
  return card;
}

function renderLiveWatch() {
  const box = $('live-watch-feed');
  if (!box) return;
  const now = Date.now();
  const watch = currentWatchGames();
  const live = watch.filter(game => game.phase === 'live');
  const signals = rankSignals(state.liveSignals);
  const status = $('live-watch-status');
  const laneText = {
    ok: 'live lane reachable', blocked: 'live lane unreachable from this browser', idle: 'waiting for a live game',
  };
  if (status) {
    status.textContent = `${live.length ? `${live.length} game(s) in progress` : `${watch.length} game(s) in the watch window`}`
      + ` · header lane: ${laneText[state.laneStatus.header] || state.laneStatus.header}`
      + ` · news lane: ${laneText[state.laneStatus.news] || state.laneStatus.news}`
      + (state.lastLaneCheck ? ` · last lane check ${instant(state.lastLaneCheck)}` : '');
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
  } else if (state.laneStatus.news === 'ok') {
    children.push(notice('No in-game injury wording in the partner news lane right now. An empty lane is not an all-clear: most in-game events are announced by clubs, not by this feed.'));
  } else if (state.laneStatus.news === 'blocked') {
    children.push(notice('The partner lane could not be reached from this browser (offline, blocked, or cross-origin). The source-checked feed below is unaffected; nothing here implies a player is healthy.'));
  } else {
    children.push(notice('Live watch is idle: it only starts polling when a game is in progress and the scoreboard lane is healthy.'));
  }
  box.replaceChildren(...children);
}

async function pollLiveLanes() {
  const now = Date.now();
  if (!shouldWatchForInGame(state.scores?.games || [], now)) {
    state.laneStatus = { header: 'idle', news: 'idle' };
    state.liveSignals = [];
    renderLiveWatch();
    return;
  }
  const previous = new Set(state.liveSignals.map(item => item.id));
  const results = await Promise.allSettled([fetchJSON(ESPN_HEADER), fetchJSON(ESPN_NEWS)]);
  const detectedAt = new Date().toISOString();
  state.lastLaneCheck = detectedAt;
  // The header lane keeps the watch window honest even when the tracked
  // scoreboard.json snapshot is minutes old (CI cadence is best-effort).
  if (results[0].status === 'fulfilled') {
    const events = laneFromHeader(results[0].value);
    if (events.length) {
      state.laneStatus.header = 'ok';
      const tracker = new Map((state.scores?.games || []).map(game => [game.id, game]));
      for (const event of events) {
        const existing = tracker.get(event.id);
        tracker.set(event.id, { ...(existing || {}), ...event, url: existing?.url || `https://www.espn.com/nfl/game/_/gameId/${event.id}` });
      }
      state.scores = { ...(state.scores || { version: 1 }), games: [...tracker.values()], laneCheckedAt: detectedAt, status: state.scores?.status || 'ok' };
      renderScores();
    } else {
      state.laneStatus.header = 'blocked';
    }
  } else {
    state.laneStatus.header = 'blocked';
  }
  if (results[1].status === 'fulfilled') {
    state.laneStatus.news = 'ok';
    const articles = Array.isArray(results[1].value?.articles) ? results[1].value.articles : [];
    state.partnerArticles = articles;
    state.liveSignals = rankSignals([
      ...laneFromNews(articles, detectedAt),
      ...eligiblePartnerAlerts(articles.flatMap(article => [{
        headline: article.headline, description: article.description, published: article.published,
        url: article.links?.web?.href || '', id: String(article.id || ''),
        teamAbbreviations: (article.categories || []).filter(c => c.type === 'team').map(c => c.team?.abbreviation).filter(Boolean),
      }]), state.scores?.games || [], now),
    ].filter((item, index, all) => all.findIndex(other => other.id === item.id) === index));
  } else {
    state.laneStatus.news = 'blocked';
  }
  const fresh = state.liveSignals.filter(item => signalWeight(item.signal) >= 4 && !previous.has(item.id));
  if (state.notifications && fresh.length) {
    for (const item of fresh.slice(0, 3)) {
      try {
        new Notification('UNVERIFIED in-game wording (partner feed)', {
          body: `${item.headline} — “${item.signal.phrase}”. Not a league or club statement yet; open the page for the provider item.`,
        });
      } catch { /* Permission may have been revoked. */ }
    }
  }
  renderLiveWatch();
}

function renderSources() {
  const box = $('sources-board');
  if (!box || !state.sources) return;
  const groups = [
    ['official', 'Official — league and club'],
    ['partner', 'Partner feeds — free, keyless, not official'],
    ['unofficial', 'Unofficial — social and aggregators (leads only)'],
  ];
  const children = [];
  for (const [tier, heading] of groups) {
    const rows = state.sources.sources.filter(entry => entry.tier === tier);
    if (!rows.length) continue;
    children.push(el('h3', `sources-heading tier-heading-${tier}`, `${heading} · ${rows.length}`));
    const list = el('div', 'source-rows');
    for (const entry of rows) {
      const card = el('article', `source-card source-${tier}`);
      const top = el('div', 'source-top');
      top.append(el('span', 'source-tier', tierLabel(entry.tier)), el('span', `source-status status-${entry.verification.status}`, entry.verification.status.replace(/-/g, ' ')));
      card.append(top, el('h4', '', entry.name), el('p', 'source-org', `${entry.org} · ${entry.role.replace(/-/g, ' ')}${entry.inGame ? ' · in-game capable' : ''}`));
      card.append(el('p', '', entry.what));
      const facts = el('dl', 'source-facts');
      facts.append(el('dt', '', 'Can prove'), el('dd', '', entry.proves));
      facts.append(el('dt', '', 'Latency'), el('dd', '', entry.latency));
      facts.append(el('dt', '', 'Checked'), el('dd', '', `${entry.verification.checkedOn || 'not re-checked this session'} — ${entry.verification.method}`));
      card.append(facts);
      const links = el('div', 'source-links');
      links.append(tierLink(entry.url, 'Open the source ↗', entry.tier));
      if (entry.verification.evidence && entry.verification.evidence !== entry.url) {
        links.append(tierLink(entry.verification.evidence, 'Probe evidence ↗', entry.tier));
      }
      card.append(links);
      card.append(el('p', 'microcopy', entry.notes));
      if (entry.autoPublish) card.append(el('p', 'microcopy', 'May ground a row in the verified archive (official only).'));
      else card.append(el('p', 'microcopy', 'Can never ground a verified archive row on its own.'));
      list.append(card);
    }
    children.push(list);
  }
  children.push(el('p', 'microcopy', state.sources.policy.rule));
  box.replaceChildren(...children);
}

function renderLeads() {
  const box = $('leads-list');
  if (!box || !state.leads) return;
  const count = $('count-leads');
  if (count) count.textContent = String(state.leads.leads.length);
  const cards = state.leads.leads.map(lead => {
    const card = el('article', 'lead-card');
    const top = el('div', 'lead-top');
    top.append(el('span', 'lead-tier', tierLabel(lead.source.tier)), el('span', 'lead-team', `${lead.team}${lead.opponent ? ` vs ${lead.opponent}` : ''}${lead.gameDate ? ` · ${day(lead.gameDate)}` : ''}`));
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

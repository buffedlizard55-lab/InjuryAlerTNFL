import { OUTCOME_LABEL, mergeIncidents, filterIncidents, freshness, selectScoreGames, newAutoAlerts } from './domain.mjs';

const $ = id => document.getElementById(id);
const state = { archive: null, review: null, live: null, scores: null, rows: [], filter: { query: '', team: 'all', outcome: 'all' }, ready: false, notifications: false };
const validArchive = value => value?.version === 1 && typeof value.scope === 'string' && Array.isArray(value.incidents)
  && value.incidents.every(row => typeof row.id === 'string' && typeof row.player === 'string' && Array.isArray(row.claims)
    && row.claims.length && row.claims.every(claim => typeof claim.date === 'string' && typeof claim.quote === 'string' && typeof claim.url === 'string'));
const validReview = value => value?.version === 1 && Array.isArray(value.flags);
const validLive = value => value?.version === 1 && Array.isArray(value.incidents) && Array.isArray(value.flags) && typeof value.status === 'string';
const validScores = value => value?.version === 1 && Array.isArray(value.games) && typeof value.status === 'string';
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
    valid = parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port && !parsed.search && !parsed.hash
      && ['www.nfl.com', 'www.dallascowboys.com'].includes(parsed.hostname)
      && (parsed.pathname.startsWith('/news/') || (type === 'review' && parsed.hostname === 'www.nfl.com' && parsed.pathname.startsWith('/players/')));
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

function reportCard(row) {
  const card = el('article', 'report-card');
  card.id = `report-${row.id}`;
  const top = el('div', 'report-card-top');
  const heading = el('div', 'player-line');
  heading.append(el('span', 'player-initial', row.team));
  const title = el('div');
  title.append(el('h3', 'player-title', row.player), el('div', 'player-meta', `${row.position === '—' ? 'PLAYER' : row.position}  ·  ${row.team} vs ${row.opponent}  ·  ${day(row.gameDate)}`));
  heading.append(title);
  top.append(heading, el('span', `status-pill ${row.outcome}`, OUTCOME_LABEL[row.outcome] || 'Unverified'));
  card.append(top);
  const detail = el('p', 'report-detail');
  detail.append(el('strong', '', 'Reported area: '), document.createTextNode(row.injury));
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
  $('report-list').replaceChildren(...(current.length ? current.map(reportCard) : [notice('No reports match these filters. Try another team or outcome.')]));
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
    const response = await fetch(new URL(path, document.baseURI), { cache: 'no-store', signal: controller.signal });
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
async function poll() {
  const previous = state.live?.incidents || [];
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
  if (state.archive) { setupTeams(); renderReports(); }
  if (state.review) renderReview();
  renderHealth();
  renderScores();
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
  const [archive, review] = await Promise.allSettled([json('./data/archive.json'), json('./data/review.json')]);
  if (archive.status === 'fulfilled' && validArchive(archive.value)) state.archive = archive.value;
  else {
    $('report-list').replaceChildren(notice('Verified archive could not be loaded. Do not interpret this as no injuries; retry later.'));
    $('coverage-copy').textContent = 'Archive unavailable';
  }
  if (review.status === 'fulfilled' && validReview(review.value)) state.review = review.value;
  else $('review-list').replaceChildren(notice('Review queue could not be loaded.'));
  await poll();
  state.ready = true;
  window.setInterval(poll, 60_000);
}
init();

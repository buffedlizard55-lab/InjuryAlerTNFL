// Pure presentation rules. No scores are used to infer injury status.
// The in-game vocabulary is imported from the generated module so the browser
// and the collectors cannot disagree about what a phrase means.
import { IN_GAME_RULES, CONTEXTS } from './vocabulary.mjs';

export { IN_GAME_RULES, CONTEXTS };

export function dataURL(path, base, now = Date.now()) {
  const url = new URL(path, base);
  // Pages edge caches sometimes retain an older artifact at the same path.
  // A shared minute bucket revalidates the changing feeds without generating
  // one origin request for every page view or polling client.
  if (path === './data/live.json' || path === './data/scoreboard.json') {
    url.searchParams.set('check', String(Math.floor(now / 60_000)));
  }
  return url;
}

export const OUTCOME_LABEL = Object.freeze({
  out: 'Ruled out', did_not_return: 'Did not return', returned: 'Returned', unconfirmed: 'Return unconfirmed',
});

export function mergeIncidents(archive = [], live = []) {
  const byId = new Map();
  for (const item of live) {
    if (item?.automatic === true && Array.isArray(item.claims) && item.claims.length) byId.set(item.id, item);
  }
  // A manually source-checked timeline must never be replaced by a shorter
  // automated one for the same game/player.
  for (const item of archive) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => {
    const dateA = a.claims.at(-1)?.date ?? a.gameDate;
    const dateB = b.claims.at(-1)?.date ?? b.gameDate;
    return dateB.localeCompare(dateA) || b.gameDate.localeCompare(a.gameDate) || a.player.localeCompare(b.player);
  });
}

export function filterIncidents(rows, { query = '', team = 'all', outcome = 'all' } = {}) {
  const q = query.trim().toLocaleLowerCase();
  return rows.filter(row => (team === 'all' || row.team === team) && (outcome === 'all' || row.outcome === outcome)
    && (!q || [row.player, row.team, row.opponent, row.injury, row.position].some(text => String(text).toLocaleLowerCase().includes(q))));
}

export function freshness(feed, now = Date.now(), maxAgeMinutes = 20) {
  const checked = Date.parse(feed?.checkedAt ?? '');
  if (!Number.isFinite(checked)) return 'not_checked';
  if (checked > now + 5 * 60_000 || now - checked > maxAgeMinutes * 60_000) return 'stale';
  if (feed?.status === 'ok') return 'ok';
  if (feed?.status === 'waiting') return 'waiting';
  return 'degraded';
}

function localDay(value) {
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) return '';
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
}

export function selectScoreGames(games = [], now = Date.now()) {
  const today = localDay(now);
  const dated = games.filter(game => localDay(game.date)).sort((a, b) => a.date.localeCompare(b.date));
  const current = dated.filter(game => localDay(game.date) === today);
  if (current.length) return { label: 'Today', games: current.slice(0, 8) };
  const future = dated.filter(game => Date.parse(game.date) > now && localDay(game.date) > today);
  if (!future.length) return { label: 'No upcoming games in this feed', games: [] };
  const day = localDay(future[0].date);
  return { label: 'Next game day', games: future.filter(game => localDay(game.date) === day).slice(0, 8) };
}

export function newAutoAlerts(previous, current, now = Date.now()) {
  const known = new Set(previous.map(item => item.id));
  return current.filter(item => {
    if (!item.automatic || known.has(item.id)) return false;
    const kickoff = Date.parse(item.gameStart ?? '');
    return Number.isFinite(kickoff) && kickoff <= now && now - kickoff <= 36 * 60 * 60_000;
  });
}

// ---------------------------------------------------------------------------
// Source tiers. Every lane is shown with its tier: an unofficial or partner
// item is never presented as a verified league/club statement.
// ---------------------------------------------------------------------------
export const TIER_LABEL = Object.freeze({
  official: 'OFFICIAL — league or club',
  partner: 'PARTNER FEED — ESPN public API',
  unofficial: 'UNOFFICIAL — reported, not verified',
});

export function tierLabel(tier) {
  return TIER_LABEL[tier] || 'UNCLASSIFIED — do not rely on';
}

// ---------------------------------------------------------------------------
// In-game vocabulary. The closed list lives in data/vocabulary.json and reaches
// this file through assets/vocabulary.mjs, so the browser, the club scanner and
// the game-window watcher all read the same phrases. A matched phrase is an
// observation or an availability phrase somebody else wrote; it is never a
// diagnosis, a severity or a cause.
// ---------------------------------------------------------------------------
export function detectAllSignals(text) {
  const value = String(text ?? '');
  if (value.length < 12 || value.length > 600) return [];
  const found = [];
  for (const rule of IN_GAME_RULES) {
    for (const pattern of rule.patterns) {
      const match = pattern.exec(value);
      if (match) {
        found.push(Object.freeze({
          status: rule.status, observation: rule.observation || '', label: rule.label,
          weight: rule.weight, phrase: match[0], matchedAt: match.index,
        }));
        break;
      }
    }
  }
  return found.sort((left, right) => right.weight - left.weight || left.matchedAt - right.matchedAt);
}

export function detectInGameSignals(text) {
  return detectAllSignals(text)[0] ?? null;
}

// Availability bands the UI sorts and colours by. Highest wins.
export const SIGNAL_WEIGHT = Object.freeze({ out: 5, questionable: 4, evaluated: 3, returned: 2, observed: 1 });

export function signalWeight(signal) {
  return SIGNAL_WEIGHT[signal?.status] ?? 0;
}

export function rankSignals(items = []) {
  return [...items].sort((a, b) => signalWeight(b.signal) - signalWeight(a.signal)
    || String(b.detectedAt || '').localeCompare(String(a.detectedAt || '')));
}

// ---------------------------------------------------------------------------
// Latency accounting. "Detected at" is when this page saw the text; it is not
// the moment of injury and is never shown as one.
// ---------------------------------------------------------------------------
export function latencySeconds(detectedAt, sourceAt) {
  const detected = Date.parse(detectedAt ?? '');
  const source = Date.parse(sourceAt ?? '');
  if (!Number.isFinite(detected) || !Number.isFinite(source)) return null;
  return Math.max(0, Math.round((detected - source) / 1000));
}

export function humanizeSeconds(seconds, fallback = 'unknown') {
  if (!Number.isFinite(seconds)) return fallback;
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} d`;
}

// A game is "in the watch window" if it is being played, if it kicked off within
// the last windowMs, or if it starts within the next preKickoffMs. The pre-kickoff
// margin exists so the page is already polling when the opening whistle goes, which
// is the difference between a first-quarter injury and a second-quarter one.
export function liveGames(games = [], now = Date.now(), windowMs = 4 * 60 * 60_000, preKickoffMs = 30 * 60_000) {
  return games.filter(game => {
    const kickoff = Date.parse(game?.date ?? '');
    if (!Number.isFinite(kickoff)) return false;
    if (game.phase === 'live') return true;
    if (game.phase === 'final') return false;
    return kickoff - preKickoffMs <= now && now - kickoff <= windowMs;
  });
}

export function shouldWatchForInGame(games = [], now = Date.now()) {
  return liveGames(games, now).length > 0;
}

// ---------------------------------------------------------------------------
// One-click unofficial search. These are links a human follows; nothing is
// scraped and nothing from them enters the verified feed.
// ---------------------------------------------------------------------------
export function socialSearchLinks(query, team = '') {
  const text = encodeURIComponent(`NFL injury ${team} ${query}`.trim());
  const tag = encodeURIComponent('nfl');
  return [
    { name: 'X live search', tier: 'unofficial', url: `https://x.com/search?q=${text}%20(injury%20OR%20injured%20OR%20cart)&f=live` },
    { name: 'Reddit search', tier: 'unofficial', url: `https://www.reddit.com/search/?q=${text}&sort=new` },
    { name: 'Bluesky search', tier: 'unofficial', url: `https://bsky.app/search?q=${text}` },
    { name: 'Mastodon #nfl', tier: 'unofficial', url: `https://mastodon.social/tags/${tag}` },
    { name: 'Instagram tag', tier: 'unofficial', url: 'https://www.instagram.com/explore/tags/nflinjury/' },
    { name: 'TikTok search', tier: 'unofficial', url: `https://www.tiktok.com/search?q=${text}` },
    { name: 'Facebook search', tier: 'unofficial', url: `https://www.facebook.com/search/posts?q=${text}` },
    { name: 'Google News', tier: 'unofficial', url: `https://news.google.com/search?q=${text}` },
  ];
}

// A partner item becomes an alert only if its own text carries in-game wording
// AND it is tied to a game that is live or just finished on the same day.
export function eligiblePartnerAlerts(articles = [], games = [], now = Date.now()) {
  const window = liveGames(games, now);
  if (!window.length) return [];
  const teamsInPlay = new Set(window.flatMap(game => [game.home, game.away]));
  return articles.flatMap(article => {
    const signal = detectInGameSignals(`${article.headline || ''} ${article.description || ''}`);
    if (!signal || signalWeight(signal) < 3) return [];
    const teams = (article.teamAbbreviations || article.teams || []).filter(team => teamsInPlay.has(team));
    if (!teams.length) return [];
    return [{ ...article, signal, teams, tier: 'partner' }];
  });
}

// ---------------------------------------------------------------------------
// Time. Every timestamp this project shows is the moment it was *seen*, and it
// is shown to the second. Provider timestamps keep whatever precision the lane
// actually publishes: the browser never invents sub-second or clock-time
// precision a feed did not give it.
// ---------------------------------------------------------------------------
export function isoSeconds(value) {
  if (value === null || value === undefined || value === '') return null;
  const text = String(value).trim().replace('Z', '+00:00');
  const parsed = new Date(text);
  if (!Number.isFinite(parsed.getTime())) return null;
  return parsed.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function stampSeconds(value, { zone = undefined } = {}) {
  const iso = isoSeconds(value);
  if (!iso) return 'time unavailable';
  const date = new Date(iso);
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: zone, year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).formatToParts(date).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  return `${parts.month} ${parts.day}, ${parts.year} ${parts.hour}:${parts.minute}:${parts.second}${zone ? ` ${zone}` : ' UTC'}`;
}

export function secondsBetween(laterIso, earlierIso) {
  const later = Date.parse(isoSeconds(laterIso) ?? '');
  const earlier = Date.parse(isoSeconds(earlierIso) ?? '');
  if (!Number.isFinite(later) || !Number.isFinite(earlier)) return null;
  return Math.max(0, Math.round((later - earlier) / 1000));
}

// ---------------------------------------------------------------------------
// The alert log. The server keeps a durable file (data/alert-log.json); the
// browser keeps the entries it saw itself in localStorage so a refresh cannot
// lose them, and shows exactly which of them were new since the last visit.
// ---------------------------------------------------------------------------
export function mergeAlertLog(serverEntries = [], sessionEntries = [], cap = 300) {
  const seen = new Map();
  for (const entry of [...(sessionEntries || []), ...(serverEntries || [])]) {
    if (!entry || typeof entry !== 'object') continue;
    const key = String(entry.id ?? `${entry.detectedAt}|${entry.lane}|${entry.subject}`);
    const existing = seen.get(key);
    // The first sighting wins: a detection time is never rewritten by a later poll.
    if (!existing || String(entry.detectedAt) < String(existing.detectedAt)) seen.set(key, entry);
  }
  return [...seen.values()]
    .sort((left, right) => String(right.detectedAt).localeCompare(String(left.detectedAt)))
    .slice(0, cap);
}

export function newSince(entries = [], sinceIso = null) {
  if (!sinceIso) return [];
  const since = Date.parse(isoSeconds(sinceIso) ?? '');
  if (!Number.isFinite(since)) return [];
  return entries.filter(entry => {
    const at = Date.parse(isoSeconds(entry?.detectedAt) ?? '');
    return Number.isFinite(at) && at > since;
  });
}

export function logLine(entry) {
  const parts = [];
  if (entry?.sourceAt) {
    const latency = secondsBetween(entry.detectedAt, entry.sourceAt);
    parts.push(`provider timestamp ${stampSeconds(entry.sourceAt)}${latency === null ? '' : ` · seen ${humanizeSeconds(latency)} later`}`);
  } else {
    parts.push('provider timestamp not published on this lane');
  }
  return parts.join(' · ');
}

// ---------------------------------------------------------------------------
// Source registry views. The registry is organised, not sorted: tier first,
// then category, then the lanes themselves, with counts a reader can check.
// ---------------------------------------------------------------------------
export const SOURCE_CATEGORY_LABEL = Object.freeze({
  'official-league': 'Official · league',
  'official-club': 'Official · club newsroom',
  'official-club-game-page': 'Official · club game page',
  'official-protocol': 'Official · protocol & medical',
  'partner-espn': 'Partner · ESPN public feeds',
  'partner-other': 'Partner · other free feeds',
  'unofficial-social': 'Unofficial · social',
  'unofficial-aggregator': 'Unofficial · aggregators & wires',
  'unofficial-beat': 'Unofficial · beat reporters',
  'unofficial-video': 'Unofficial · video',
});

export const LATENCY_LABEL = Object.freeze({
  seconds: 'seconds', minutes: 'minutes', hours: 'hours', daily: 'same day',
  weekly: 'weekly', blocked: 'blocked', 'link-out': 'link only',
});

export function groupSources(sources = []) {
  const order = ['official-league', 'official-club', 'official-club-game-page', 'official-protocol',
    'partner-espn', 'partner-other', 'unofficial-beat', 'unofficial-aggregator', 'unofficial-social', 'unofficial-video'];
  const byCategory = new Map();
  for (const lane of sources) {
    const key = lane?.category ?? 'unknown';
    if (!byCategory.has(key)) byCategory.set(key, []);
    byCategory.get(key).push(lane);
  }
  return order
    .filter(category => byCategory.has(category))
    .map(category => ({
      category,
      label: SOURCE_CATEGORY_LABEL[category] ?? category,
      rows: byCategory.get(category).sort((left, right) =>
        String(left.name).localeCompare(String(right.name))),
    }));
}

export function filterSources(sources = [], { query = '', tier = 'all', category = 'all', access = 'all' } = {}) {
  const needle = query.trim().toLocaleLowerCase();
  return sources.filter(lane => (tier === 'all' || lane.tier === tier)
    && (category === 'all' || lane.category === category)
    && (access === 'all' || lane.access === access)
    && (!needle || [lane.name, lane.org, lane.what, lane.proves, lane.id]
      .some(field => String(field ?? '').toLocaleLowerCase().includes(needle))));
}

export function laneHealth(lane, now = Date.now(), maxAgeMinutes = 30) {
  if (!lane?.checkedAt) return 'unknown';
  const checked = Date.parse(isoSeconds(lane.checkedAt) ?? '');
  if (!Number.isFinite(checked)) return 'unknown';
  if (now - checked > maxAgeMinutes * 60_000) return 'stale';
  return lane.status === 'ok' ? 'ok' : lane.status === 'blocked' ? 'blocked' : 'idle';
}

// Pure presentation rules. No scores are used to infer injury status.
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
// In-game vocabulary. This is deliberately a closed list of phrases a provider
// actually has to write before anything is shown. It classifies text; it never
// invents a diagnosis, a severity, or a cause. Returns null when the text says
// nothing about availability, so play-by-play chatter stays silent.
// ---------------------------------------------------------------------------
const IN_GAME_RULES = [
  { status: 'out', match: /\b(?:will not return|did not return|does not return|ruled out|is out for the (?:game|remainder)|out for the remainder of the game)\b/i },
  { status: 'returned', match: /\b(?:returned to the game|has returned|returned to the field|back on the field)\b/i },
  { status: 'questionable', match: /\b(?:questionable to return|return is questionable|doubtful to return)\b/i },
  { status: 'observed', observation: 'Cart or stretcher', match: /\b(?:cart(?:ed)? off|on a stretcher|immobilized)\b/i },
  { status: 'observed', observation: 'Medical tent', match: /\b(?:blue (?:medical )?tent|medical tent)\b/i },
  { status: 'evaluated', observation: 'Concussion evaluation', match: /\b(?:concussion protocol|evaluated for a concussion)\b/i },
  { status: 'observed', observation: 'Injury mentioned', match: /\b(?:injured|injury|hurt|limped|went down)\b/i },
];

export function detectInGameSignals(text) {
  const value = String(text ?? '');
  if (value.length < 12 || value.length > 600) return null;
  for (const rule of IN_GAME_RULES) {
    if (rule.match.test(value)) return Object.freeze({ status: rule.status, observation: rule.observation || '', phrase: rule.match.exec(value)[0] });
  }
  return null;
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

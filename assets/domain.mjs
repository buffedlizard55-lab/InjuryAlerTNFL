// Pure presentation rules. No scores are used to infer injury status.
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

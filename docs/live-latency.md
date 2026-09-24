# Lanes, tiers and latency

This page explains what "low latency" can honestly mean for a static, free, unofficial
project, and which lane is responsible for what.

## The three tiers

| Tier | Who | Used for | Can ground a verified archive row |
| --- | --- | --- | --- |
| official | NFL.com, the 32 club newsrooms | in-game roundups, per-game in-game pages, game recaps/reports, practice notebooks, injury news items, IR/roster moves, the weekly (pregame) injury report | **yes** |
| partner | ESPN public site endpoints (scoreboard, scoreboard header, news, injuries, summary) | live game state, timestamped leads, cross-checks | no |
| unofficial | X, Instagram, Facebook, TikTok, Reddit (link-outs), Bluesky (search blocked), Mastodon, Google News, CBS live tracker, DraftKings Network, NBC/Rotoworld, CBS player news, Heavy, beat wires | leads, discovery, context | no |

The registry (`data/sources.json`, 67 lanes) records, for every lane: what it is,
what it can prove, its tier, its category (league, club, protocol, ESPN, other
partner, beat, aggregator, social, video, play-by-play), its latency class and
timestamp precision, its access mode (JSON, HTML, link-out, blocked), its probe
method and evidence, whether it is in-game capable, whether it may auto-publish —
and, since Pass 8, its **browser reachability** (`browserProbe`) in exactly four
states: `allowed` (this page's own JavaScript reached the host), `blocked` (a
refusal was measured: NFL game-centre JSON `401`, Reddit `403`, Bluesky search
`403`), `not-applicable` (link-out lanes that are never fetched) or `not-tested`
(no claim made). The existing `verification` field records what the *verifier's*
server-side fetch reached — a different client from the reader's browser, and
server fetches are not subject to CORS — so browser-reachability claims come
from `browserProbe` alone.
`scripts/schema.py` enforces the rules; a lane that is neither official nor partner
is forced into a lead role, the category must match the tier prefix, a link-out lane
must declare link-out latency, a `browserProbe.allowed` lane must be keyless JSON,
HTML or RSS, and nothing outside the official tier is allowed to auto-publish.

### The log — why a refresh never loses history

Every scan writes to `data/alert-log.json` through `scripts/alertlog.py`: append-only,
capped at 1,200 entries, newest first, deduplicated by a stable digest id
(`kind` + `lane` + `subject` + `text` + provider timestamp). Entries are second
precision, carry their kind (`live-signal`, `club-candidate`, `club-promotion`,
`roundup-match`, `lane-status`, `lane-failure`, `roster-followup`), their tier, and a
`latencySeconds` only when a provider timestamp exists. Because the id ignores the
detection time, polling the same sentence every 20 seconds cannot flood the log, while
a genuinely new sentence gets a new id. The browser merges that file with a
`localStorage` session log (`sideline-signal-session-log-v1`, first detection wins),
so reloading the page shows what was already seen instead of starting empty, and the
log can be exported as JSON. `feed.xml` carries up to 40 of the newest logged alerts,
each tagged with its tier.

## Why the fastest lane is in the browser

Measured on 2026-09-24, the `*/5` GitHub Actions schedule fired about once every
4-6 hours (17:04Z, 12:03Z, 06:23Z, 01:22Z). GitHub throttles scheduled workflows, and
a static Pages deployment has no server that can push. So the responsive path is the
open page, and `scripts/watch_live.py` provides the same lane as a long-running local
worker (`--minutes 300 --interval 20`: scoreboard header → live games → summary
injuries → play-by-play, writing `data/watch.json` and the log with a per-lane status
so a blocked lane shows as blocked instead of silent; it exits after 45 minutes with
no live game rather than polling an empty league forever):

| Lane | Interval | Starts when | What it shows |
| --- | --- | --- | --- |
| ESPN scoreboard header | 10 s | 30 min before kickoff until 4 h after | which games are live, period/clock/score |
| ESPN game lanes (news, summary, play-by-play) | 20 s | while a game is in the watch window | headlines/descriptions and play text containing explicit in-game wording, with the play's own wall-clock timestamp |
| `data/live.json` + `data/scoreboard.json` + `data/alert-log.json` + `data/candidates.json` + `data/watch.json` | 30 s | always, and immediately on tab focus | the durable CI record, the log, the club-scan candidates, the latest watch state, and the tracked fallbacks (30-second cache-bust bucket — never a per-second URL loop) |
| social search links | on demand (click) | always | X/Reddit/Bluesky/Mastodon/Instagram/TikTok/Facebook/Google News |

**Background tabs:** browsers throttle timers in hidden tabs, so the effective
interval above is the *foreground* one. `assets/app.js` listens for
`visibilitychange` and re-runs the live lanes (and re-polls the tracked files) the
moment the tab becomes visible again — the first thing a returning reader sees is a
fresh read, not the last frozen one.

The play-by-play lane reads ESPN's public core endpoint
(`sports.core.api.espn.com/.../competitions/{id}/plays`), which returns each play with
a `wallclock` field — the provider's own UTC time for the play. A play description is
only surfaced when it carries one of the availability phrases above, so play chatter
stays silent by construction; when it does match, the card's latency is measured
against the play's wall-clock time rather than against the page load.

### In-game vocabulary (the only thing that is ever surfaced)

The browser classifier is a closed list defined once in `data/vocabulary.json`
(generated to `assets/vocabulary.mjs`): outcome phrases `will not return`, `may not
return`, `did not return`, `ruled out`, `questionable to return`, `doubtful to
return`; availability phrases `carted off`, `stretcher`, `blue tent`/`medical
tent`, `concussion protocol`, **field evaluation** (“under evaluation”), **got up /
back on his feet**, and **return** phrases (`returned to the game`, `re-entered`,
`back in the game`, `evaluated and returned`); plus a weak `injured/hurt/went down`
observation. Text shorter than 12 or longer than 600 characters is ignored, a play
description that carries none of these phrases returns nothing, and replay chatter
(“the replay is under review”) deliberately matches nothing. Every card
prints the matched phrase, the provider timestamp, the observed latency, and the tier.

### Honest failure modes

- A lane that cannot be reached (offline, blocked, cross-origin) says
  `unreachable from this browser` instead of going quiet.
- An empty lane is never an all-clear; the page says so next to it.
- Notifications for partner wording are titled **UNVERIFIED** and name the feed.
- Nothing from a partner or unofficial lane is ever written into `data/archive.json`.

## What the archived ledger actually shows

The archive stores one claim per dated observation, so the *shape* of the delay is
readable even without clock-level telemetry. Three examples, taken from
`data/archive.json` and re-verifiable through the audit links:

| Incident | First official record | Later detail | Gap |
| --- | --- | --- | --- |
| Jadarian Price (SEA, chest) | NFL.com Week 2 roundup, game day Sept 20: "did not return" | Seahawks injury update after the game: X-rays negative; Sept 21 roundup: shoulder, "nothing serious"; Sept 23 club page: he will practice | the league sentence lands game day, the label changed **chest → shoulder** over three days |
| Jayden Reed (GB, neck) | NFL.com Week 2 roundup, game day Sept 20: ruled out after a stretcher exit | Sept 21: back injury per Schefter; Sept 22: stayed overnight in New Jersey; Sept 23: ruled out for Thursday | same-day for the game status, three days to reconstruct what happened |
| Mike Onwenu (NE, ankle) | NFL.com Week 2 roundup, game day Sept 20: "ruled out in the first half" | Sept 21: Vrabel confirms; Sept 22: placed on injured reserve | game-day availability, next-day cause, two-day roster consequence |

The consistent pattern: **clubs are minutes, the league is hours, aggregators look
fast but are not verifiable, and anatomy labels move after the fact.** That is why the
page leads with the browser lane, keeps club and league material as the verified
record, and files every label change into the review queue instead of silently
rewriting it.

## CI capture steps (Pass 8)

`publish.yml` now runs two fail-soft capture steps after the refresh, on every
publish (cron-throttled to roughly 4-6 h in practice, plus every push to `main`):

- `python scripts/watch_live.py --once` — one in-game watch cycle (header → live
  games → summary injuries → play-by-play) writing `data/watch.json` and appending
  `live-signal` / `lane-status` / `lane-failure` entries to the log with the
  provider wall-clock times as their `providerTime`.
- `python scripts/clubscan.py --per-club 3 --budget 160 --no-promote` — a bounded
  per-club news scan (3 fresh article reads per club, 160 requests/run) shipping a
  fresh `data/candidates.json` in the artifact. `--no-promote` is deliberate:
  promotion still requires the two-independent-reads rule to run in the repository,
  so CI can **surface** candidates but can never add to the verified list.

Both are `continue-on-error`: a blocked provider writes an honest *unavailable*
state and a `lane-failure` log entry instead of failing the build. Both paths were
exercised in an isolated copy with no network: watch produced `unavailable` + one
log entry, clubscan produced blocked/budget-skipped club states + three log entries,
nothing crashed, nothing was published as verified. The deployed `data/alert-log.json`
is therefore the heartbeat of these steps — an empty deployed log is a warning
sign, not a neutral state.

## What would move the needle next

1. A long-running poller (or paid scheduler) reading the same free endpoints every
   15-30 s and committing only official-grounded rows — removes the "page must be
   open" limitation. `scripts/watch_live.py` is the prototype (CI now runs it once
   per publish); it needs a host that stays up (a VPS, a container, or a paid
   scheduler) for anything tighter than the Pages cron.
2. A per-club discovery pass (news index → game report → in-game sentence) to fill
   the games listed in `README.md`.
3. Optional adapter for a licensed play-by-play feed if one ever becomes available;
   `api.nfl.com` game-centre JSON currently returns 401 for anonymous readers and is
   registered as **blocked** rather than assumed.

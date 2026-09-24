# Lanes, tiers and latency

This page explains what "low latency" can honestly mean for a static, free, unofficial
project, and which lane is responsible for what.

## The three tiers

| Tier | Who | Used for | Can ground a verified archive row |
| --- | --- | --- | --- |
| official | NFL.com, the 32 club newsrooms | in-game roundups, per-game in-game pages, game recaps/reports, practice notebooks, injury news items, IR/roster moves, the weekly (pregame) injury report | **yes** |
| partner | ESPN public site endpoints (scoreboard, scoreboard header, news, injuries, summary) | live game state, timestamped leads, cross-checks | no |
| unofficial | X, Instagram, Facebook, TikTok, Reddit (link-outs), Bluesky (search blocked), Mastodon, Google News, CBS live tracker, DraftKings Network, NBC/Rotoworld, CBS player news, Heavy, beat wires | leads, discovery, context | no |

The registry (`data/sources.json`) records, for every lane: what it is, what it can
prove, its latency, its probe method and evidence, whether it is in-game capable, and
whether it may auto-publish. `scripts/schema.py` enforces the rules; a lane that is
neither official nor partner is forced into a lead role, and nothing outside the
official tier is allowed to auto-publish.

## Why the fastest lane is in the browser

Measured on 2026-09-24, the `*/5` GitHub Actions schedule fired about once every
4-6 hours (17:04Z, 12:03Z, 06:23Z, 01:22Z). GitHub throttles scheduled workflows, and
a static Pages deployment has no server that can push. So the responsive path is the
open page:

| Lane | Interval | Starts when | What it shows |
| --- | --- | --- | --- |
| ESPN scoreboard header | 20 s | 30 min before kickoff until 4 h after | which games are live, period/clock/score |
| ESPN NFL news | 45 s | while a game is in the watch window | headlines/descriptions containing explicit in-game wording |
| `data/live.json` + `data/scoreboard.json` | 60 s | always | the durable CI record and the tracked fallbacks |
| social search links | on demand (click) | always | X/Reddit/Bluesky/Mastodon/Instagram/TikTok/Facebook/Google News |

### In-game vocabulary (the only thing that is ever surfaced)

The browser classifier is a closed list: `will not return`, `did not return`, `ruled
out`, `questionable to return`, `doubtful to return`, `carted off`, `stretcher`,
`blue tent`/`medical tent`, `concussion protocol`, plus a weak `injured/hurt/went
down` observation. Text shorter than 12 or longer than 600 characters is ignored, and
a play description that carries none of these phrases returns nothing. Every card
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

## What would move the needle next

1. A long-running poller (or paid scheduler) reading the same free endpoints every
   15-30 s and committing only official-grounded rows — removes the "page must be
   open" limitation.
2. A per-club discovery pass (news index → game report → in-game sentence) to fill
   the games listed in `README.md`.
3. Optional adapter for a licensed play-by-play feed if one ever becomes available;
   `api.nfl.com` game-centre JSON currently returns 401 for anonymous readers and is
   registered as **blocked** rather than assumed.

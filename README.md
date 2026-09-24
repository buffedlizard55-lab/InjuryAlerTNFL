# Sideline Signal — source-backed NFL in-game injury reporting

**Website:** [buffedlizard55-lab.github.io/InjuryAlerTNFL/](https://buffedlizard55-lab.github.io/InjuryAlerTNFL/) · [source audit](docs/source-audit.md) · [lane + latency design](docs/live-latency.md)

An independent, mobile-friendly NFL scoreboard and **in-game injury alert** prototype. It separates **what was observed**, **what happened in that game**, and **later reported availability** — and it labels every lane it reads as **official**, **partner**, or **unofficial** so a reader never mistakes a social post for a club statement.

- **103 verified incidents** (2026 Weeks 1-2), each grounded in dated excerpts from NFL.com or a club newsroom. **270 claims across 52 official URLs**, re-checked on **2026-09-24**.
- **35 review flags** — 3 held (2 identity mismatches, 1 withdrawn row) and 32 annotated conflicts/grading notes, all linked on both sides.
- **46 registered sources** with a probe record each: 21 official, 7 partner, 18 unofficial. Twenty-five lanes were added in this pass; none was listed until its content had been retrieved and read (or its refusal to serve an anonymous reader had been measured). The pair added last records a hard boundary: a club practice injury report proves a current label but never when the injury happened, and a coach's transcript can confirm an injury exists without placing it in a game.
- **15 unofficial leads** (CBS tracker, beat reporters, aggregators, Chargers Wire) recorded with the exact next check needed; none of it is in the verified list.
- Based on the [NFL scoreboard example](https://buffedlizard55-lab.github.io/NFL-scoreboard/) and built to avoid the pregame/in-game conflation in the [injury report example](https://buffedlizard55-lab.github.io/NFLInjuryReport/).

## Priority order on the page

1. **Live in-game watch** — while a game is in play the browser polls a partner header lane every **20 s** and a partner news lane every **45 s**, and shows only text whose own wording says *will not return*, *did not return*, *ruled out*, *questionable to return*, *carted off*, *stretcher*, *medical tent*, or *concussion protocol*. Each card carries the provider's timestamp, how long after publication the page saw it, a **PARTNER FEED · UNVERIFIED** badge, and a link. Play-by-play chatter is silent by construction: the classifier returns nothing unless a provider actually wrote an availability phrase.
2. **Scoreboard** — public ESPN scoreboard for schedule/scores **only**; it never creates an injury claim.
3. **Verified incidents** — the source-checked archive, filterable by player, club and outcome, with excerpts and links.
4. **Sources, tier by tier** — every lane with what it can prove, what it can never prove, its latency, and its probe record (including the lanes that are **blocked** or **link-out-only**).
5. **Unofficial leads** — what other outlets reported, clearly not verified, each with the promotion check.
6. **Review queue** — conflicts, duplicate-name traps and label disagreements kept side by side.

### Source tiers

| Tier | Examples | May ground a verified row? |
| --- | --- | --- |
| **Official** — league or club | NFL.com roundups & weekly injury report, all 32 club newsrooms, Seattle's and Green Bay's per-game in-game update pages, club game-day recaps and game reports | **Yes** — the only tier that can |
| **Partner** — free, keyless, not official | ESPN public scoreboard, scoreboard header, news, injuries feed, summary/play-by-play | No. Live context and leads only |
| **Unofficial** — social, beat, aggregators | X/Instagram/Facebook/TikTok/Reddit (link-outs), Bluesky (search blocked), Mastodon, Google News, CBS live tracker, DraftKings Network, NBC/Rotoworld, Heavy, beat wires | No. Leads only, never auto-published |

Hard rules encoded in `scripts/schema.py` and `assets/domain.mjs`: a non-official lane cannot be flagged `autoPublish`; an unofficial lane must use a lead role; a leads file may not contain official material; and the registry must always list the boundary lanes (auth-gated NFL game-centre JSON, ESPN's play-by-play payload, X, Reddit) with their true status.

## What runs automatically

- GitHub Actions (cron `*/5` + main pushes + manual dispatch) reads NFL.com's roundup index and in-game roundups. The conservative parser checks player identity, team heading, a real NFL game, the publication date and an explicit single-player return/out phrase; grouped, missing or contradictory claims are withheld. It does **not** use an LLM to invent a prognosis.
- **Measured cadence (2026-09-24):** the scheduled workflow now fires, but GitHub throttles it to roughly one run every **4-6 hours** (17:04Z, 12:03Z, 06:23Z, 01:22Z). A five-minute cron is *not* five-minute delivery — which is exactly why the priority lane runs **in the browser**, not in CI.
- The open page polls `data/live.json` and `data/scoreboard.json` every 60 s with a minute-bucket cache-buster, and runs the in-game lanes on their own fast clock. Notifications (optional) work only while the page is open: new CI-matched reports, and new **unverified** partner wording with the tier spelled out in the notification body.
- A failed provider check or old artifact shows a warning; an empty incident list never means nobody was injured. `data/archive.json` is the verified master list and CI cannot add to it.
- Offline builds use clearly marked empty fallbacks; `tests/fixtures/` is synthetic parser test data and is never published.

## Run and inspect locally

Python 3.11+ and Node 20+; **no runtime packages**.

```sh
python -m unittest discover -s tests -v      # 20 tests
node --test tests/ui.test.mjs                # 12 tests
python scripts/build.py --output _site
python3 -m http.server 8000 --bind 0.0.0.0 --directory _site
```

`http://localhost:8000/` is only for local testing. On GitHub Pages all browser requests use relative paths, except the two partner lanes the browser calls directly (CSP `connect-src` allows only `site.api.espn.com` and `site.web.api.espn.com`). On a network-capable machine you can also run the collector and the online excerpt re-check:

```sh
python scripts/refresh.py --live /tmp/live.json --scoreboard /tmp/scores.json
python scripts/verify_sources.py --strict   # re-fetch and compare every stored excerpt
```

### Repository map

- `index.html`, `assets/` — accessible static site, no user report form.
- `data/archive.json` — 103 verified incidents. `data/review.json` — 35 flags. `data/sources.json` — the 46-lane registry. `data/leads.json` — 15 unofficial leads. Tracked `data/live.json` / `data/scoreboard.json` are honest *not yet checked* fallbacks.
- `assets/domain.mjs` — pure presentation rules: source-tier labels, the in-game vocabulary classifier, signal ranking, latency maths, the pre-kickoff watch window, the one-click social search links and the partner-alert gate.
- `scripts/` — `refresh.py` (collector + ESPN score adapter), `schema.py` (fail-closed validators for archive, review, sources and leads), `build.py` (Pages artifact + auto-only RSS), `verify_sources.py`, `diagnose_audit.py`, `unblock_deployments.py`, `wait_for_legacy_pages.py`.
- `.github/workflows/test.yml` runs the suites on PRs (with a continue-on-error online excerpt re-check that annotates drift); `publish.yml` refreshes and deploys on cron/push.

## Verification and language rules

1. One player + one dated game per ID; a pregame OUT designation is never merged with an in-game ruled-out event. A "returned" always refers to **that game**, never clearance for next week.
2. Every displayed archive claim carries a direct league or club URL, a short supporting quote, a report date and an independently readable claim. The 217 excerpts that existed before this pass were re-fetched and re-compared online on 2026-09-24; the 53 added here were taken from pages retrieved during this pass, and `scripts/verify_sources.py --strict` re-checks all 270 in CI, printing the nearest live sentence for any excerpt it cannot match and filing one annotation per drifted claim. NFL.com articles can be reworded after publication, so quotes are re-verified rather than assumed.
3. A blue tent, cart, stretcher or walking off is an **observation**, never a diagnosis or a severity score. Diagnoses are attributed to a coach or a reporter. Predictions keep their qualifiers.
4. Disagreements, mismatched player links and moving anatomical labels go to the review queue with both sides linked. Nothing is inferred from the absence of a report.

## This pass (Pass 1 of 3)

**On the "20 new entries" goal:** this pass adds **2 new verified incidents and 53 new dated claims**, not 20 new incidents, and the gap is structural rather than a shortcut. Every league "notable injuries" bullet published for Weeks 1-2 is already in the archive, so new *incidents* must come one club page at a time, and each one needs a sentence that (a) sits on an allowed official host and (b) actually places the injury inside a game. This pass fetched and read club pages for the Chargers, Raiders, Vikings, Broncos, Dolphins, Jaguars, Bengals and Titans; most either repeat pregame statuses or confirm an injury without saying when it happened. Those cases are recorded as leads with the exact next check, not padded into the ledger. Reaching twenty incidents is a discovery-throughput problem — the per-club routine is now written down (see the limitations below), and the two rows that did land show the shape that works: the Saints' game-day recap and the Vikings' roster-move story.


- **Sources (new):** the registry now carries **44** lanes; the 23 newest were added only after their content was retrieved and read — including Seattle's and Green Bay's per-game in-game pages, club game-day recaps and game reports, practice notebooks and injury news items, and on the unofficial side the CBS live tracker, DraftKings Network, NBC/Rotoworld player news, CBS player news, Heavy, Chargers Wire, the Las Vegas Review-Journal, the Colorado Springs Gazette and Sports Betting Dime. Lanes that refuse a free read (NFL game-centre JSON `401`, Reddit `403`, Bluesky search `403`, api.nfl.com) are listed as **blocked** rather than quietly dropped, and X/Instagram/Facebook/TikTok are **link-out-only** because no keyless read tier exists.
- **Latency (new):** a browser-side in-game lane (20 s header / 45 s news) that starts 30 minutes before kickoff and reports lane failures instead of going quiet; the in-game vocabulary classifier; latency chips showing how long after the provider's timestamp the wording was seen; and the measured CI cadence above.
- **Master list:** two incidents could be grounded this pass, and both came from club pages rather than league roundups: **Martin Emerson Jr.** (Saints game-day recap, shoulder, first half of the Week 2 win) and **Brett Thorson** (vikings.com roster-move story: "Thorson suffered a hamstring injury Sunday at Chicago"). **53 new dated claims** were added across existing rows from the Sept 21, 22 and 23 league roundups plus club pages (Onwenu IR and Vrabel's confirmation, Banks Jr. surgery, Goedert MCL, Dowdle day-to-day, Reed's overnight stay and Thursday ruling, Dart's meniscus/MCL/PCL damage, Coleman's sprained ankle, Kolar's and Njoku's IR confirmation from the club itself, Holani cleared to return, and more). Every other candidate researched this pass — Awosika, Tomlinson, Stukes, Dobbins, Bradford, Cole Strange, Ingram-Dawkins' club label — has **official text that never places the injury inside a game**, so each is in the leads lane with the exact next check rather than in the archive.
- **Code:** club `/game-day/` recap paths are now allowed as official evidence; three club domains were corrected to their real hosts (`neworleanssaints.com`, `miamidolphins.com`, `tennesseetitans.com`); `build.py` validates and ships the registry and leads; 8 new tests cover the registry, the leads discipline and the live-watch rules (Python 18 → 20, browser 6 → 12).

## Important limitations / next session priorities

- **Not real-time and not complete.** Even with the browser lane, this is a client-side view of free feeds: no push to closed browsers, no email/SMS, no guarantee a provider's wording appears at all. NFL.com roundups lag minutes to hours and omit players; club pages are the earliest official voice but only some clubs publish them. Critical decisions should use club/NFL announcements directly.
- **The official in-game corpus for Weeks 1-2 is exhausted.** Every league "notable injuries" bullet for both weeks is already in the archive, so the remaining rows require per-club mining. Coverage measured on 2026-09-24: **29 of 32 clubs** appear at least once (Week 1: 22 clubs, Week 2: 26), and **Cincinnati, Las Vegas and Tennessee have no archived incident at all** — their club game reports, recaps and notebooks are the highest-yield place to look next. The Jaguars' game-report shape (one page covering both sidelines) is the pattern to copy, together with each club's practice notebook.
- **Reach the 20 new incident entries by mining clubs, not guesses.** This pass could ground one new row and 50 new claims. To add incidents, the collector needs a per-club discovery pass (club news index → game report/notebook → in-game sentence) with the same fail-closed rules; running that pipeline over the 12 games above is the concrete next step.
- **Scheduled runs are throttled by GitHub** to hours, not minutes (measured above). Any genuinely low-latency server-side lane needs a long-running worker (or a paid scheduler), which a static Pages deployment cannot provide. Until then the browser lane is the responsive path and the CI lane is the durable record.
- **The per-club discovery routine (written down so the next pass is mechanical).** For every club without an archived incident — Cincinnati, Las Vegas and Tennessee today — and then for any game whose club pages are unread: (1) open the club news index (`https://www.<club>.com/news/`) and the game-day hub; (2) fetch that week's **game recap**, **game report**, **postgame notebook/quick hits**, **coach press conference transcript** and **roster-move story**; (3) search each page for the in-game vocabulary (`did not return`, `ruled out`, `left the game`, `carted`, `stretcher`, `tent`, `protocol`, `evaluated and returned`, `suffered ... Sunday`) and keep only sentences that place the injury inside the game; (4) copy the exact sentence into a claim only after the page loads (club pages get reworded, as the Chargers' Week 2 takeaways page shows); (5) record everything that falls short in `data/leads.json` with the next check, and any label conflict in `data/review.json`. Two formats pay best: the club game-day recap (Saints) and roster-move stories that name the game day (Vikings).
- **No automated longitudinal prognosis, and no severity score.** Observations (cart, tent, protocol) are recorded as observations. There is no clinically valid automated severity estimate, and this project will not invent one.
- **Scores and live context use unsupported public ESPN endpoints.** No contractual guarantee; if they fail the page says so and shows the tracked fallback. Respect the providers' terms; X, Instagram, Facebook and TikTok are linked out, not scraped.
- **Pages configuration:** a *legacy main/root* Pages source still exists and once overwrote a generated-artifact deploy with the tracked fallback. `publish.yml` waits for the same-commit legacy build and closes stale `github-pages` deployments first; the integration cannot change the Pages source via API. An administrator should select **GitHub Actions** as the sole source to remove the workaround.
- **Identity and label conflicts stay visible:** Kam Curl and Zach Bako-Bewele are held on name/slug mismatches; Kiko Mauigoa's slug conflict, the Darnold hip/glute label, the Njoku knee/fibula change, the Price chest/shoulder change, the new Dobbins hip/hamstring/cramps conflict, the Thorson origin conflict and the Stukes in-game-origin question are all annotated rather than resolved by guesswork.

This is an **unofficial** project, unaffiliated with the NFL, its clubs, or ESPN, and is not medical advice.

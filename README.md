# Sideline Signal — source-backed NFL in-game injury reporting

**Website:** [buffedlizard55-lab.github.io/InjuryAlerTNFL/](https://buffedlizard55-lab.github.io/InjuryAlerTNFL/) · [60-entry source audit](docs/source-audit.md)

An independent, mobile-friendly NFL scoreboard and injury alert prototype. It separates **what was observed**, **what happened in that game**, and **later reported availability**. Each of the 60 archive entries links short evidence excerpts to NFL.com or official club reporting. Sixteen irregularities are linked in a separate review queue (ten held, six annotated). The archive was checked on **September 23, 2026**; it is *not* a complete injury census or a live medical status database.

Based on the [NFL scoreboard example](https://buffedlizard55-lab.github.io/NFL-scoreboard/) and designed to avoid the pregame-status / in-game-status conflation in the [injury report example](https://buffedlizard55-lab.github.io/NFLInjuryReport/). No source is treated as infallible.

## What runs automatically

- GitHub Actions (scheduled every five minutes, plus on main updates) reads NFL.com's public news roundup index and recent **in-game roundup** articles. The conservative parser checks a linked player's identity, team heading, an actual NFL game, the publication date, and an *explicit single-player* return/out phrase. Grouped, missing, contradictory, or unverifiable claims are withheld. It does **not** use an LLM to invent a prognosis.
- The ESPN public scoreboard supplies schedule/scores **only**. It is not an injury source. Its availability is checked independently of NFL.com. All data is assembled into a Pages artifact; no token, backend, user-supplied report, or commit of scraped articles is required.
- The open page polls the generated feeds every minute, with a shared minute-bucket URL parameter to bypass stale Pages edge copies of changing JSON. Browser notifications (optional) work only with the page open and permission granted. They fire only for *new* automatically matched reports from games started within 36 hours; the initial archive does not cause a notification. RSS (`feed.xml`) contains automatic reports, not the historical archive.
- A failed provider check or old artifact displays a warning; an empty incident list does **not** imply that nobody was injured. The scoreboard never creates an injury claim. `data/archive.json` is the verified master list; CI cannot silently add unsupported rows to it. New automated matches are in the deployed, ephemeral `data/live.json` only.

## Run and inspect locally

Python 3.11+ and Node 20+; **no runtime packages**. The collector needs network access to NFL.com and the ESPN public scoreboard; offline builds use clearly marked empty fallbacks.

```sh
python -m unittest discover -s tests -v
node --test tests/ui.test.mjs
python scripts/build.py --output _site
python3 -m http.server 8000 --bind 0.0.0.0 --directory _site
```

`http://localhost:8000/` is only for local testing, not a browser-side API endpoint. On GitHub Pages all browser requests use relative paths. To test a network run (on a machine with access), run:

```sh
python scripts/refresh.py --live /tmp/injury-live.json --scoreboard /tmp/injury-scores.json
python scripts/build.py --output _site --live /tmp/injury-live.json --scoreboard /tmp/injury-scores.json
```

### Repository map

- `index.html`, `assets/` — accessible static site. No user report form.
- `data/archive.json` — 60 game-specific source-checked examples, each with dated claims and official league/team links. `data/review.json` — sixteen separately flagged source issues. Tracked `data/live.json` and `data/scoreboard.json` are honest *not yet checked* fallbacks for first deployment.
- `scripts/refresh.py` — strict discovery, URL/player checks, date/game cross-check, ESPN score adapter and fail-closed output. `scripts/schema.py` enforces source URLs and event/claim chronology. `scripts/build.py` makes the Pages artifact and auto-only RSS. `scripts/verify_sources.py --strict` can re-fetch and compare every short excerpt; a source outage is flagged rather than counted as a match. `scripts/diagnose_audit.py` prints the served text around any excerpt the online audit cannot ground, and `scripts/unblock_deployments.py` closes stale `github-pages` environment deployments.
- `.github/workflows/test.yml` tests the PR; `publish.yml` refreshes and deploys on main / schedule. No workflow pushes commits to another branch.
- `tests/fixtures/` is **synthetic parser test data**, not real game history and never published.

## Verification and language rules

1. One player + one dated game per ID; don't merge a pregame OUT designation with an in-game ruled-out event. A subsequent “returned” always refers to **that game**, not clearance for next week.
2. Every displayed archive claim has a direct league or team news URL, a short supporting quote, a report date, and an independently readable claim. All 123 quotes were re-fetched and re-compared against their live pages on September 23, 2026; those re-checks caught and corrected four pre-existing excerpts: three whose wording crossed an inline link boundary (the Mike Evans and Avonte Maddox Monday-report quotes and the Jonathon Brooks surgery quote now quote only the contiguous sentence their URLs plainly state) and the Dart coach-confirmation sentence, which NFL.com reworded after publication — the ledger now quotes the sentence as the page serves it, caught by the CI re-check with the [diagnostic tool](scripts/diagnose_audit.py). The [audit](docs/source-audit.md) is the manual review index. An NFL.com *news article* is NFL editorial reporting, not necessarily an official team-issued game-status notice. NFL.com [injuries](https://www.nfl.com/injuries/) is a **pregame** report, not a real-time in-game API.
3. A blue tent, cart, stretcher, or walking off is an **observation**, never a diagnosis or severity score. Confirmed diagnoses are explicitly attributed to a coach or NFL Network reporting. Predictions retain qualifiers (“expected,” “will be placed”); they are not reported as completed transactions or return dates.
4. Disagreements, mismatched player URLs and moving anatomical labels go to the [review queue](data/review.json), with links to both sides. The parser only auto-publishes a narrow class of direct claims and never guesses from absence of a report.

## Important limitations / next session priorities

- **Not real-time or complete.** NFL.com roundup posts can lag play by minutes/hours or omit players; scheduled GitHub Actions are best-effort and may be delayed, disabled after inactivity, or rate-limited. A five-minute cron is *not* a five-minute delivery guarantee. Pages is static; no push notifications to closed browsers or email/SMS. Critical decisions should use team/NFL announcements directly.
- **No automated longitudinal prognosis.** The collector presently handles explicit game outcomes in NFL.com in-game roundups. Individual team statements, TV injury reports, local beat reporters and later clearances need separately validated adapters with entity resolution and conflict review before automatic publication. There is no clinically valid automated severity estimate. *Next session:* integrate official club newsroom/game-day status feeds, source timestamps, and a persistent audited update ledger; add real-event fixture tests and discrepancy monitoring across sources; accept the club-recap phrase "missed the remainder of the game" as an explicit did-not-return grounding so held entries such as Cobie Durant can be promoted with both sources linked; and route practice-week reports with explicit in-game anchors (e.g., Jonah Coleman) through the follow-up adapter's source classes.
- **Scores use a public, unsupported ESPN endpoint.** There is no contractual availability guarantee; game matching stops if scores cannot be verified. Consider a licensed official game feed for production and obtain permissions for higher-frequency collection. Respect site terms/rate limits.
- **Pages configuration:** GitHub reports a *legacy main/root* Pages source. After one merge, that legacy build overwrote a successful generated-artifact deployment with the tracked, explicitly *not checked* fallback. The publish workflow now waits for the **same-commit** legacy Pages build to finish before deploying its refreshed artifact, and its first job closes **stale `github-pages` environment deployments** ([scripts/unblock_deployments.py](scripts/unblock_deployments.py)): on September 23 a deploy-pages deployment was left `waiting` when it raced a legacy build, and because deployments to one environment serialize, every later publish job queued forever behind that zombie while the legacy path kept publishing — the tracker now closes such stale deployments (older than ten minutes) before deploying, and fails loudly with admin instructions if it lacks permission. The integration cannot change the Pages build setting via API (`403 Resource not accessible by integration`). A repository administrator should ideally select **GitHub Actions** as the sole Pages source to remove this workaround entirely.
- **Scheduled runs have never fired.** The `*/5` cron on the publish workflow produced zero `schedule` events up to September 23, 2026 — refreshes so far happen only on main pushes. GitHub registers new crons late and disables schedules on inactive repositories; verify the schedule actually ticks (Actions filter `event:schedule`) before relying on five-minute freshness. The static site stays available either way; its archive is tracked and its live feed honestly reports when it has not been checked.
- **Research scope:** sixty selected, distinct 2026 in-game events across Weeks 1-2 (preseason-style scans of every roundup from Sept. 10-23), not all NFL injuries. Known leads that did not meet the in-game bar — Myles Garrett (no in-game anchor found), Ronnie Rivers, Mansoor Delane, Cooper McDonald, Jake Tonges, Nick Cross, Cobie Durant, Jonah Coleman — are listed in the [audit](docs/source-audit.md) with concrete next steps for the next pass. Even sourced stories can later be corrected — as the CI re-check proved when NFL.com reworded the Dart confirmation sentence after publication. Old claims remain a historical record with source dates, not a current health assertion. A human can inspect every link in the audit; no user entry is required.

This is an **unofficial** project, unaffiliated with the NFL, its clubs, or ESPN, and is not medical advice.

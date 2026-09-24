# Next steps and limits

Everything here is written so a later session can act without rediscovering it.
The short version: **the pipeline and the taxonomy are done; coverage is the
work.** Nothing in this file is a wish for a feature the project cannot support
honestly.

## 1. The 20-incident goal: a discovery-throughput problem

This pass added **2 verified incidents and 53 dated claims**, not 20 incidents.
That gap is not a shortcut — it is what the verification rules cost:

- Every league "notable injuries" bullet for **Weeks 1-2 is already archived**, so
  new *incidents* can only come from club pages.
- A row needs a sentence that (a) sits on an allowed official host (`nfl.com` or a
  club newsroom) and (b) actually places the injury **inside a game**. Pregame
  participation tables, coach transcripts and roster moves routinely fail (b).
- Clubs reword pages. The Chargers' Week 2 "5 Takeaways" page as published no
  longer contains the sentence a syndicated copy of it carried about Cole Strange
  and Kayode Awosika, so that sentence cannot be cited.

### The routine that works (one club at a time)

1. `https://www.<club>.com/news/` and the game-day hub for the week.
2. Fetch, in this order: **game-day recap**, **game report**, **postgame quick
   hits / notebook**, **coach press conference transcript**, **roster-move story**.
3. Keep only sentences containing in-game wording: `did not return`, `ruled out`,
   `left the game`, `carted`, `stretcher`, `tent`, `protocol`, `evaluated and
   returned`, `suffered ... Sunday`. Copy the sentence verbatim.
4. Anything that falls short goes into `data/leads.json` with the next check, and
   any label conflict into `data/review.json`. Do not pad the ledger.
5. Re-run `python scripts/selfcheck.py` and the test suites.

Two page shapes pay best, and both are official: the **club game-day recap**
(Saints → Martin Emerson Jr.) and the **roster-move story that names the game day**
(Vikings → Brett Thorson). Budget roughly one fetch per candidate.

### Where to look first

Coverage measured at the end of this pass: **29 of 32 clubs** appear at least once
(Week 1: 22 clubs, Week 2: 26).

| Gap | What is missing | First pages to try |
| --- | --- | --- |
| **Cincinnati** | no archived incident at all | `bengals.com/news/` postgame quick hits for Weeks 1-2; the Sept 24 "Iosivas to IR with torn thumb ligaments" item has no in-game sentence yet |
| **Las Vegas** | no archived incident at all; Treydan Stukes' concussion protocol is official but the link to the Chargers game is third-party | `raiders.com` Week 2 press-conference text, Week 3 injury report, "By the Numbers" |
| **Tennessee** | no archived incident at all; Cedric Gray's concussion came from a UTV accident, which is out of scope | `tennesseetitans.com` quick-hits series and Week 1/2 recaps |
| Chargers line | Kayode Awosika (fibula) and Cole Strange (evaluated, returned) are in-match events that only third parties describe fully | a chargers.com practice report or presser transcript |
| Broncos backfield | J.K. Dobbins: league and club both say hip, local coverage says hamstring then cramps; the exit is third-party | a broncos.com sentence naming the moment |
| Dolphins | Caleb Douglas's ankle is confirmed by the club transcript but never placed in the game | a Dolphins game-day or notebook page |

## 2. Latency: what a static site cannot do

- The browser lane is the only low-latency lane this architecture can offer
  (20 s header / 45 s news while a game is in the watch window). A closed tab
  receives nothing.
- GitHub Actions scheduled runs are throttled: measured on 2026-09-24 the `*/5`
  cron fired at **17:04Z, 12:03Z, 06:23Z, 01:22Z** — roughly every 4-6 hours.
- A genuinely server-side 15-30 s lane needs a long-running worker or a paid
  scheduler (a static Pages deployment cannot host one). If that is ever added, it
  must keep the same fail-closed rules: official hosts only for rows, and the
  review queue for conflicts.
- `api.nfl.com` game-centre JSON returns **401** for anonymous readers today, so
  the official play-by-play lane in the registry is `blocked`, not assumed. The
  free alternatives (ESPN's public endpoints) are partner tier and can never
  ground a row.

## 3. Verification debt to keep paying

- `scripts/verify_sources.py --strict` re-fetches every excerpt in CI and files one
  annotation per drifted claim. It is `continue-on-error` because a provider outage
  must not fail a build — but a *drift* warning is a work item, not noise.
- Club and league pages get reworded after publication. A citation that was exact
  when written can stop being readable; that is how the withdrawn Puka Nacua row
  happened. Re-read before re-quoting.
- Unofficial leads must never be promoted without a fresh read of the outlet page
  **and** an official grounding sentence, and a lead that duplicates a verified row
  must carry `duplicateOf`.

## 4. Repository hygiene

- **Pages source:** a legacy *main / root* Pages build still exists and races the
  generated artifact. The publish workflow waits for the same-commit legacy build
  and closes stale `github-pages` deployments first. A repository administrator
  should set **GitHub Actions** as the sole Pages source and delete that
  workaround.
- Keep `_site/` and other generated output out of Git; the published data is
  rebuilt in CI.
- The test workflow now runs on `pull_request` to `main` and on pushes to any
  `arena/**` branch, and it includes `scripts/selfcheck.py`, so a branch that
  publishes something the site could misrepresent fails before a PR exists.

## 5. What this project must never do

- Never turn an observation (cart, stretcher, tent, protocol) into a diagnosis or
  a severity score.
- Never let a partner or unofficial lane ground a verified row, and never let an
  unofficial lane auto-publish.
- Never infer a return date from a practice listing or a prediction from silence.
- Never present a pregame designation as an in-game event — that conflation is the
  specific failure this project exists to avoid.

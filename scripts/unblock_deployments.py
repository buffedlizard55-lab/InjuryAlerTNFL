"""Close stale github-pages environment deployments that block deploy-pages.

A deploy-pages deployment left in waiting/in_progress/queued — for example
when a legacy "pages build and deployment" run raced it — serializes every
later deployment to the same environment, so publish jobs queue forever while
the legacy path keeps publishing. Workflow jobs without an `environment:` key
are not gated by that queue, so the publish workflow runs this helper first
and closes stale deployments before its publish job starts.

Exit code 1 if a stale deployment could not be closed (the run then fails
visibly instead of waiting on a blocked queue).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

STALE_STATES = {"waiting", "in_progress", "queued", "pending"}
GUARD_SECONDS = 600  # never touch a deployment younger than this


def should_close(state: str, age_seconds: float) -> bool:
    """True when a deployment is old enough and unsettled enough to close."""
    return state in STALE_STATES and age_seconds >= GUARD_SECONDS


def api(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True)


def deployment_state(deployment_id: int) -> str:
    out = api(f"repos/{os.environ['GH_REPO']}/deployments/{deployment_id}/statuses?per_page=1")
    if out.returncode != 0:
        return "unknown"
    rows = json.loads(out.stdout)
    return rows[0]["state"] if rows else "unknown"


def main() -> int:
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("GH_REPO/GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1
    now = time.time()
    blocked: list[str] = []
    closed = 0
    out = api(f"repos/{repo}/deployments?environment=github-pages&per_page=30")
    if out.returncode != 0:
        print(f"::error title=Stale Pages deployments::Could not list deployments: {out.stderr.strip()[:200]}")
        return 1
    for dep in json.loads(out.stdout):
        created = datetime.fromisoformat(dep["created_at"].replace("Z", "+00:00"))
        age = now - created.timestamp()
        state = deployment_state(dep["id"])
        if not should_close(state, age):
            continue
        desc = f"stale {state} deployment closed by publish workflow after {int(age // 60)} min"
        r = api("-X", "POST", f"repos/{repo}/deployments/{dep['id']}/statuses",
                "-f", "state=inactive", "-f", f"description={desc}")
        if r.returncode == 0:
            closed += 1
            print(f"closed deployment {dep['id']} (was {state}, {int(age // 60)} min old)")
        else:
            blocked.append(f"{dep['id']} ({state})")
            print(f"FAILED to close deployment {dep['id']} ({state}): {r.stderr.strip()[:160]}")
    if blocked:
        print("::error title=Stale Pages deployments::Could not deactivate stale "
              f"deployment(s) {', '.join(blocked)}; the github-pages environment queue stays "
              "blocked and deploy-pages cannot proceed. A repository admin must reject the "
              "pending deployment under Settings > Environments > github-pages.")
        return 1
    print(f"stale-deployment scan: {closed} closed, nothing blocking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

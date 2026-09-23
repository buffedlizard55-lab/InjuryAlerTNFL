#!/usr/bin/env python3
"""Let legacy Pages finish before the generated artifact deploys.

This is only needed while this repository has both main/root legacy Pages and a
scheduled Actions Pages artifact. For a push, the legacy dynamic workflow may
finish *after* deploy-pages and overwrite the generated scores with the tracked
not_checked fallbacks. A scheduled/dispatch build has no competing branch build.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time


def legacy_run(payload: dict, sha: str) -> dict | None:
    """Find the automatic Pages build for this exact main commit, not an old run."""
    for run in payload.get("workflow_runs", []):
        if (run.get("name") == "pages build and deployment"
                and run.get("event") == "dynamic"
                and run.get("head_sha") == sha):
            return run
    return None


def api_json(endpoint: str) -> dict:
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def wait_for_legacy(sha: str, repo: str, *, timeout: int = 240) -> None:
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required to inspect the competing Pages build")
    if api_json(f"repos/{repo}/pages").get("build_type") != "legacy":
        print("Pages source is not legacy; no competing branch build to wait for.")
        return
    endpoint = f"repos/{repo}/actions/runs?event=dynamic&head_sha={sha}&per_page=20"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = api_json(endpoint)
        run = legacy_run(payload, sha)
        if run and run.get("status") == "completed":
            print(f"Legacy Pages build completed ({run.get('conclusion')}); publishing generated artifact last.", flush=True)
            # The workflow can complete before the edge serves its artifact.
            time.sleep(12)
            return
        print("Waiting for legacy Pages build on this main commit...", flush=True)
        time.sleep(8)
    raise TimeoutError("Legacy Pages build did not finish; refusing a race with the generated artifact")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    wait_for_legacy(args.sha, args.repo)

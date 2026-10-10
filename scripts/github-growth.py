#!/usr/bin/env python3
"""Save owner-visible GitHub metrics without treating clones as real users."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def get(endpoint):
    completed = subprocess.run(["gh", "api", endpoint], text=True, capture_output=True)
    if completed.returncode:
        return {"status": "NOT RUN", "reason": "GitHub endpoint unavailable with current credentials"}
    return {"status": "PASS", "data": json.loads(completed.stdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="lsh235/FaultDebugMCP")
    parser.add_argument("--output", type=Path, default=Path("output/growth"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    repo = get("repos/" + args.repo)
    data = repo.get("data", {})
    snapshot = {"observed_at_utc": now.isoformat(), "repository": args.repo,
                "stars": data.get("stargazers_count"), "forks": data.get("forks_count"),
                "repository_status": repo["status"],
                "views": get("repos/" + args.repo + "/traffic/views"),
                "clones": get("repos/" + args.repo + "/traffic/clones"),
                "referrers": get("repos/" + args.repo + "/traffic/popular/referrers"),
                "interpretation": "Rolling GitHub traffic windows overlap. Automated clones and owner/CI activity are not identified as external users. Do not sum weekly windows or infer visitor-to-star conversion."}
    path = args.output / (now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"output": str(path), "stars": snapshot["stars"],
                      "status": snapshot["repository_status"]}))


if __name__ == "__main__":
    main()

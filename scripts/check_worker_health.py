#!/usr/bin/env python3
"""Fail closed when the external worker heartbeat is absent or stale."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-age-seconds", type=float, default=30)
    args = parser.parse_args()
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "smart-data-agent-worker-health/v1":
        raise SystemExit("worker_health_schema_invalid")
    heartbeat = datetime.fromisoformat(str(payload.get("heartbeat_at") or "").replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
    if not payload.get("ready") or age < 0 or age > args.max_age_seconds:
        raise SystemExit("worker_heartbeat_stale")
    print(json.dumps({"ready": True, "worker_id": payload.get("worker_id"), "age_seconds": round(age, 3)}))


if __name__ == "__main__":
    main()

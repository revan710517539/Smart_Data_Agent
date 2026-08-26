from __future__ import annotations

import argparse
import os

from backend.platform.automation import AutomationWorker
from backend.platform.bootstrap import build_local_platform, build_production_platform
from backend.platform.runtime_config import emit_runtime_capability_summary, load_runtime_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Smart Data Agent durable worker outside the API process.")
    parser.add_argument("--test-sqlite-db", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--worker-id", default=os.getenv("SMART_DATA_AGENT_WORKER_ID", "data-worker"))
    args = parser.parse_args()
    if args.test_sqlite_db is not None:
        services = build_local_platform(args.test_sqlite_db)
    else:
        runtime_config = load_runtime_config()
        emit_runtime_capability_summary(runtime_config)
        services = build_production_platform(runtime_config)
    worker = AutomationWorker(services.automation_runtime, poll_seconds=args.poll_seconds, worker_id=args.worker_id)
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()
        services.close()


if __name__ == "__main__":
    main()

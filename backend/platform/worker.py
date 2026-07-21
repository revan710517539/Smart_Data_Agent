from __future__ import annotations

import argparse
import os

from backend.platform.automation import AutomationWorker
from backend.platform.bootstrap import build_local_platform, build_production_platform
from backend.platform.runtime_config import load_runtime_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Smart Data Agent durable worker outside the API process.")
    parser.add_argument("--db", default=".smart_data_agent.sqlite")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--worker-id", default=os.getenv("SMART_DATA_AGENT_WORKER_ID", "crawler-worker"))
    args = parser.parse_args()
    runtime_config = load_runtime_config()
    services = (
        build_production_platform(runtime_config)
        if runtime_config.environment in {"staging", "production"} and runtime_config.database_url
        else build_local_platform(args.db)
    )
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

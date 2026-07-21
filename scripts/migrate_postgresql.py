from __future__ import annotations

import argparse
import json
import os

from backend.platform.database import apply_postgresql_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the generated Smart Data Agent PostgreSQL schema.")
    parser.add_argument("--database-url", default=os.getenv("SMART_DATA_AGENT_DATABASE_URL", ""))
    args = parser.parse_args()
    result = apply_postgresql_schema(args.database_url)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

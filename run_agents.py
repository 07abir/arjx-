"""Run MarketPilot's AI workflow for a product already saved in SQLite."""

import argparse
import asyncio
import json

from agents.manager import run_product_workflow
from config import get_settings
from database.db import initialize_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a MarketPilot analysis and listing preview.")
    parser.add_argument("--product-id", type=int, required=True, help="Existing SQLite product ID")
    args = parser.parse_args()
    settings = get_settings()
    initialize_database(settings.database_path)
    report = asyncio.run(run_product_workflow(args.product_id, database_path=settings.database_path))
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


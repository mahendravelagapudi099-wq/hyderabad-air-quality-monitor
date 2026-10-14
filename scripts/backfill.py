"""Backfill script for Hyderabad Air Quality Monitor.

Fetches up to 30 days of historical data from OpenAQ v3 API,
validates, cleans, upserts into the database, and flags anomalies.
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.ingestion import IngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backfill")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical air quality data.")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.BACKFILL_DAYS,
        help=f"Number of historical days to backfill (default: {settings.BACKFILL_DAYS})",
    )
    parser.add_argument(
        "--max-locations",
        type=int,
        default=None,
        help="Optional maximum number of locations to process.",
    )
    args = parser.parse_args()

    logger.info("Initializing Backfill Pipeline (days=%d, max_locations=%s)...", args.days, args.max_locations)

    try:
        settings.validate()
        pipeline = IngestionPipeline()
        summary = pipeline.run(days_back=args.days, max_locations=args.max_locations)
        print("\n" + "=" * 60)
        print("BACKFILL SUMMARY")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k:22}: {v}")
        print("=" * 60 + "\n")
    except Exception as e:
        logger.error("Backfill failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

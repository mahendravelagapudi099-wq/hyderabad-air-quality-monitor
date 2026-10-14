"""Daily pipeline execution script for Hyderabad Air Quality Monitor.

Fetches latest data plus the last 3 days to catch delayed or corrected records,
validates, cleans, upserts without duplicates, runs anomaly detection, and logs metrics.
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.database import get_session
from src.ingestion import IngestionPipeline
from src.models import Measurement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily air quality ingestion pipeline.")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.DAILY_REFETCH_DAYS,
        help=f"Days to fetch (default: {settings.DAILY_REFETCH_DAYS})",
    )
    parser.add_argument(
        "--max-locations",
        type=int,
        default=None,
        help="Optional maximum number of locations to process.",
    )
    args = parser.parse_args()

    logger.info("Starting Daily Ingestion Pipeline (window: past %d days)...", args.days)

    try:
        settings.validate()
        pipeline = IngestionPipeline()
        summary = pipeline.run(days_back=args.days, max_locations=args.max_locations)

        print("\n" + "=" * 60)
        print("PIPELINE RUN SUMMARY")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k:22}: {v}")
        print("=" * 60 + "\n")

        # Smoke check
        with get_session() as session:
            total_records = session.query(Measurement).count()
            logger.info("Smoke Check: Total measurements in database: %d", total_records)
            if total_records == 0:
                logger.warning("Smoke Check Warning: Database contains 0 records after run.")

    except Exception as e:
        logger.error("Daily pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

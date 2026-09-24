import os
import sys
import time
import argparse
import logging

from src.pipeline import OlaIncentivePipeline
from src.config import GDRIVE_FOLDER_ID, LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("OlaETL.Main")

def main():
    parser = argparse.ArgumentParser(description="LetzRyd Ola Incentive Ingestion Pipeline")
    parser.add_argument("--run-once", action="store_true", default=True, help="Run single sync cycle and exit (default)")
    parser.add_argument("--poll", action="store_true", help="Run continuously in polling daemon mode")
    parser.add_argument("--interval", type=int, default=3600, help="Polling interval in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--local-file", type=str, default=None, help="Process a local Excel file directly")
    parser.add_argument("--folder-id", type=str, default=GDRIVE_FOLDER_ID, help="Google Drive folder ID")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of already processed files")
    parser.add_argument("--init-db", action="store_true", help="Initialize database schema and exit")

    args = parser.parse_args()

    pipeline = OlaIncentivePipeline(folder_id=args.folder_id)

    if args.init_db:
        logger.info("Initializing database schema...")
        pipeline.loader.init_schema()
        logger.info("Database schema initialized successfully.")
        return

    if args.local_file:
        logger.info(f"Running manual ingestion of local file: {args.local_file}")
        res = pipeline.ingest_local_file(args.local_file, force=args.force)
        logger.info(f"Result: {res}")
        return

    if args.poll:
        logger.info(f"Starting pipeline daemon mode. Polling folder '{args.folder_id}' every {args.interval}s...")
        while True:
            try:
                pipeline.run(force=args.force)
            except Exception as e:
                logger.error(f"Error in sync loop: {e}", exc_info=True)
            logger.info(f"Sleeping for {args.interval} seconds...")
            time.sleep(args.interval)
    else:
        # Single cycle run (ideal for Cloud Run Jobs, Cloud Functions, and cron)
        res = pipeline.run(force=args.force)
        logger.info(f"Execution complete: {res}")

if __name__ == "__main__":
    main()

import os
import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime

from .config import GDRIVE_FOLDER_ID, GOOGLE_APPLICATION_CREDENTIALS
from .drive_scanner import DriveScanner
from .excel_processor import ExcelProcessor
from .db_loader import DBLoader

logger = logging.getLogger("OlaETL.Pipeline")

class OlaIncentivePipeline:
    """
    Main orchestrator for scanning Google Drive, processing weekly Excel workbooks,
    and atomically loading data into PostgreSQL.
    """

    def __init__(self, folder_id: str = GDRIVE_FOLDER_ID, credentials_path: Optional[str] = GOOGLE_APPLICATION_CREDENTIALS):
        self.folder_id = folder_id
        self.credentials_path = credentials_path
        self.scanner = DriveScanner(folder_id, credentials_path)
        self.loader = DBLoader()
        self.download_dir = os.path.join(os.getcwd(), "temp_downloads")

    def run(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes a single check and ingestion cycle across all files in the Google Drive folder.
        """
        logger.info(f"Starting Ola Incentive Ingestion Cycle for Drive Folder: {self.folder_id}")
        self.loader.init_schema()

        files = self.scanner.list_xlsx_files()
        if not files:
            logger.info("No .xlsx files found in Google Drive folder.")
            return {"status": "NO_FILES", "processed": 0, "skipped": 0, "failed": 0}

        results = {"processed": 0, "skipped": 0, "failed": 0, "files": []}

        for file_info in files:
            file_id = file_info['id']
            file_name = file_info['name']
            logger.info(f"Evaluating Drive File: '{file_name}' (ID: {file_id})")

            if not force and self.loader.is_file_processed(file_id):
                logger.info(f"Skipping already ingested file: '{file_name}' (ID: {file_id})")
                results['skipped'] += 1
                results['files'].append({"file_name": file_name, "status": "SKIPPED"})
                continue

            temp_dest = os.path.join(self.download_dir, f"{file_id}_{file_name}")
            log_id = None
            try:
                # 1. Download
                self.scanner.download_file(file_id, temp_dest)

                # 2. Parse & validate sheets
                parsed = ExcelProcessor.parse_workbook(temp_dest, file_id, file_name)

                # 3. Create initial log entry
                log_id = self.loader.create_log_entry(
                    file_id=file_id,
                    file_name=file_name,
                    drive_modified_time=file_info.get('modifiedTime'),
                    week_start=parsed['week_start'],
                    week_end=parsed['week_end']
                )

                # 4. Atomic load into DB
                self.loader.load_parsed_data(log_id, parsed)

                results['processed'] += 1
                results['files'].append({
                    "file_name": file_name,
                    "status": "SUCCESS",
                    "week": f"{parsed['week_start']} to {parsed['week_end']}",
                    "counts": parsed['counts']
                })
                logger.info(f"Successfully processed and loaded '{file_name}'")

            except Exception as e:
                err_msg = f"{e}\n{traceback.format_exc()}"
                logger.error(f"Error processing file '{file_name}': {err_msg}")
                if log_id:
                    self.loader.update_log_failed(log_id, str(e))
                else:
                    # Create failed log entry if one wasn't created yet
                    try:
                        failed_id = self.loader.create_log_entry(file_id, file_name, None, None, None)
                        self.loader.update_log_failed(failed_id, str(e))
                    except Exception as le:
                        logger.error(f"Could not record failure to database: {le}")

                results['failed'] += 1
                results['files'].append({"file_name": file_name, "status": "FAILED", "error": str(e)})

            finally:
                # Clean up temporary download file
                if os.path.exists(temp_dest):
                    try:
                        os.remove(temp_dest)
                    except Exception:
                        pass

        logger.info(f"Cycle completed: {results['processed']} processed, {results['skipped']} skipped, {results['failed']} failed.")
        return results

    def ingest_local_file(self, local_path: str, file_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """
        Ingests a local Excel file directly without fetching from Drive (for testing or manual backfills).
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")

        file_name = os.path.basename(local_path)
        if not file_id:
            file_id = f"local_{os.path.splitext(file_name)[0]}"

        logger.info(f"Processing local file: '{file_name}' (ID: {file_id})")
        self.loader.init_schema()

        if not force and self.loader.is_file_processed(file_id):
            logger.info(f"File {file_id} has already been ingested. Use force=True to re-ingest.")
            return {"file_name": file_name, "status": "SKIPPED"}

        parsed = ExcelProcessor.parse_workbook(local_path, file_id, file_name)
        log_id = self.loader.create_log_entry(
            file_id=file_id,
            file_name=file_name,
            drive_modified_time=None,
            week_start=parsed['week_start'],
            week_end=parsed['week_end']
        )
        self.loader.load_parsed_data(log_id, parsed)
        return {
            "file_name": file_name,
            "status": "SUCCESS",
            "week": f"{parsed['week_start']} to {parsed['week_end']}",
            "counts": parsed['counts']
        }

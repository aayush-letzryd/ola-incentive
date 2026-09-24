import logging
from datetime import datetime, date
from typing import Dict, Any, Optional
import psycopg2
import psycopg2.extras
import pandas as pd

from .config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

logger = logging.getLogger("OlaETL.DBLoader")

class DBLoader:
    """
    Handles atomic loading of parsed sheets into PostgreSQL tables and pipeline run logging.
    """

    def __init__(self, host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS):
        self.conn_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password
        }

    def get_connection(self):
        return psycopg2.connect(**self.conn_params)

    def init_schema(self, schema_file_path: Optional[str] = None):
        """Ensures all 5 tables, indexes, and views exist."""
        if not schema_file_path:
            import os
            schema_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")

        with open(schema_file_path, "r", encoding="utf-8") as f:
            ddl = f.read()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
        logger.info("Schema initialized and verified.")

    def is_file_processed(self, file_id: str) -> bool:
        """Checks if the file has already been successfully processed."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM public.sheet_ola_incentive_pipeline_logs
                    WHERE file_id = %s AND execution_status = 'SUCCESS'
                    LIMIT 1;
                """, (file_id,))
                res = cur.fetchone()
                return res is not None

    def create_log_entry(self, file_id: str, file_name: str, drive_modified_time: Optional[datetime], week_start: Optional[date], week_end: Optional[date]) -> int:
        """Creates an IN_PROGRESS pipeline log entry and returns its ID."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.sheet_ola_incentive_pipeline_logs (
                        file_id, file_name, drive_modified_time, week_start_date, week_end_date,
                        execution_status, started_at
                    ) VALUES (%s, %s, %s, %s, %s, 'IN_PROGRESS', CURRENT_TIMESTAMP)
                    RETURNING id;
                """, (file_id, file_name, drive_modified_time, week_start, week_end))
                log_id = cur.fetchone()[0]
            conn.commit()
            return log_id

    def update_log_success(self, log_id: int, counts: Dict[str, int], week_start: date, week_end: date):
        """Marks the pipeline run as SUCCESS with row counts."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE public.sheet_ola_incentive_pipeline_logs
                    SET 
                        status_rows_count = %s,
                        bank_statement_rows_count = %s,
                        summary_rows_count = %s,
                        ola_report_rows_count = %s,
                        total_rows_count = %s,
                        week_start_date = %s,
                        week_end_date = %s,
                        execution_status = 'SUCCESS',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (
                    counts['status'],
                    counts['bank_statement'],
                    counts['summary'],
                    counts['ola_report'],
                    counts['total'],
                    week_start,
                    week_end,
                    log_id
                ))
            conn.commit()

    def update_log_failed(self, log_id: int, error_msg: str):
        """Marks the pipeline run as FAILED with error message."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE public.sheet_ola_incentive_pipeline_logs
                    SET 
                        execution_status = 'FAILED',
                        error_message = %s,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (error_msg, log_id))
            conn.commit()

    def load_parsed_data(self, log_id: int, parsed_data: Dict[str, Any]):
        """
        Atomically replaces data for source_file_id across all 4 tables and records success.
        """
        file_id = parsed_data['file_id']
        file_name = parsed_data['file_name']
        week_start = parsed_data['week_start']
        week_end = parsed_data['week_end']
        counts = parsed_data['counts']

        df_status = parsed_data['status']
        df_bank = parsed_data['bank_statement']
        df_summary = parsed_data['summary']
        df_ola = parsed_data['ola_report']

        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # 1. Delete prior data for this file_id (idempotent replacement)
                cur.execute("DELETE FROM public.sheet_ola_incentive_status WHERE source_file_id = %s;", (file_id,))
                cur.execute("DELETE FROM public.sheet_ola_incentive_bank_statement WHERE source_file_id = %s;", (file_id,))
                cur.execute("DELETE FROM public.sheet_ola_incentive_summary WHERE source_file_id = %s;", (file_id,))
                cur.execute("DELETE FROM public.sheet_ola_incentive_ola_report WHERE source_file_id = %s;", (file_id,))

                # 2. Insert Status Tab
                if not df_status.empty:
                    cols = ['date', 'type', 'car_number', 'car_model', 'date_for', 'amount_raw',
                            'sub_category', 'payment_type', 'status', 'actual_incentive',
                            'actual_ondemand', 'instapay_transfer', 'total_online_payment',
                            'source_file_name', 'source_file_id', 'week_start_date', 'week_end_date']
                    records = [tuple(x) for x in df_status[cols].to_numpy()]
                    query = f"""
                        INSERT INTO public.sheet_ola_incentive_status ({','.join(cols)})
                        VALUES %s;
                    """
                    psycopg2.extras.execute_values(cur, query, records, page_size=1000)

                # 3. Insert Bank Statement Tab
                if not df_bank.empty:
                    cols = ['date', 'utr', 'amount', 'vehicles', 'city', 'status', 'reason',
                            'actual_incentive', 'actual_ondemand', 'instapay_transfer', 'total_online_payment',
                            'source_file_name', 'source_file_id', 'week_start_date', 'week_end_date']
                    records = [tuple(x) for x in df_bank[cols].to_numpy()]
                    query = f"""
                        INSERT INTO public.sheet_ola_incentive_bank_statement ({','.join(cols)})
                        VALUES %s;
                    """
                    psycopg2.extras.execute_values(cur, query, records, page_size=1000)

                # 4. Insert Summary Tab
                if not df_summary.empty:
                    cols = ['date', 'report_type', 'actual_incentive', 'actual_ondemand',
                            'instapay_transfer', 'total_online_payment', 'source_file_name',
                            'source_file_id', 'week_start_date', 'week_end_date']
                    records = [tuple(x) for x in df_summary[cols].to_numpy()]
                    query = f"""
                        INSERT INTO public.sheet_ola_incentive_summary ({','.join(cols)})
                        VALUES %s;
                    """
                    psycopg2.extras.execute_values(cur, query, records, page_size=1000)

                # 5. Insert Ola Report Tab
                if not df_ola.empty:
                    cols = ['date', 'type', 'car_number', 'car_model', 'date_for', 'amount_raw',
                            'status', 'sub_category', 'payment_type', 'source_file_name',
                            'source_file_id', 'week_start_date', 'week_end_date']
                    records = [tuple(x) for x in df_ola[cols].to_numpy()]
                    query = f"""
                        INSERT INTO public.sheet_ola_incentive_ola_report ({','.join(cols)})
                        VALUES %s;
                    """
                    psycopg2.extras.execute_values(cur, query, records, page_size=1000)

                # 6. Mark log entry as SUCCESS
                cur.execute("""
                    UPDATE public.sheet_ola_incentive_pipeline_logs
                    SET 
                        status_rows_count = %s,
                        bank_statement_rows_count = %s,
                        summary_rows_count = %s,
                        ola_report_rows_count = %s,
                        total_rows_count = %s,
                        week_start_date = %s,
                        week_end_date = %s,
                        execution_status = 'SUCCESS',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """, (
                    counts['status'],
                    counts['bank_statement'],
                    counts['summary'],
                    counts['ola_report'],
                    counts['total'],
                    week_start,
                    week_end,
                    log_id
                ))

            conn.commit()
            logger.info(f"Database transaction committed successfully for log_id={log_id}, file={file_name}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction failed, rolled back for file={file_name}: {e}")
            self.update_log_failed(log_id, str(e))
            raise
        finally:
            conn.close()

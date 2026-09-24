import os
import re
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("OlaETL.ExcelProcessor")

class ExcelProcessor:
    """
    Parses and transforms Ola Incentive weekly Excel workbooks.
    Standardizes schema, unpivots the Summary sheet, and computes Monday-Sunday week boundaries.
    """

    REQUIRED_SHEETS = ['status', 'bank statement', 'summary', 'ola report']

    @staticmethod
    def _find_sheet_name(sheet_names, target):
        target_clean = target.strip().lower()
        for s in sheet_names:
            if s.strip().lower() == target_clean:
                return s
        return None

    @classmethod
    def determine_week_boundary(cls, df_status: pd.DataFrame, df_summary_raw: pd.DataFrame, df_ola: pd.DataFrame) -> Tuple[date, date]:
        """
        Determines the exact week period (Monday to Sunday) by inspecting dates inside the file.
        """
        valid_dates = []

        # 1. Check 'Date for' in Status sheet
        if 'Date for' in df_status.columns:
            v = pd.to_datetime(df_status['Date for'], errors='coerce').dropna()
            for d in v:
                if pd.notna(d):
                    valid_dates.append(d.date())

        # 2. Check 'Date for' in Ola Report sheet
        for col in df_ola.columns:
            if col.strip().lower() == 'date for':
                v = pd.to_datetime(df_ola[col], errors='coerce').dropna()
                for d in v:
                    if pd.notna(d):
                        valid_dates.append(d.date())

        # 3. Check dates in Summary sheet
        for idx in range(2, len(df_summary_raw)):
            val = df_summary_raw.iloc[idx, 0]
            if pd.isna(val) or str(val).strip().lower() in ['total', 'diff', 'difference', 'variance']:
                continue
            try:
                d = pd.to_datetime(val, errors='coerce')
                if pd.notna(d):
                    valid_dates.append(d.date())
            except Exception:
                continue

        if not valid_dates:
            raise ValueError("Unable to determine week dates: no valid date found in Status, Ola Report, or Summary sheets.")

        min_d = min(valid_dates)
        # Week starts on Monday (Monday = 0 in Python)
        monday = min_d - timedelta(days=min_d.weekday())
        # Week ends on Sunday (Sunday = Monday + 6 days)
        sunday = monday + timedelta(days=6)

        logger.info(f"Resolved week boundary: {monday} (Monday) to {sunday} (Sunday)")
        return monday, sunday

    @classmethod
    def parse_workbook(cls, file_path: str, file_id: str, file_name: str) -> Dict[str, Any]:
        """
        Reads all 4 tabs from the workbook, cleans and normalizes them into ready-to-load DataFrames.
        """
        logger.info(f"Opening workbook: {file_path}")
        excel_file = pd.ExcelFile(file_path)
        actual_sheet_names = excel_file.sheet_names

        # Validate sheet existence
        resolved_sheets = {}
        for req in cls.REQUIRED_SHEETS:
            matched = cls._find_sheet_name(actual_sheet_names, req)
            if not matched:
                raise ValueError(f"Missing required sheet '{req}'. Found sheets: {actual_sheet_names}")
            resolved_sheets[req] = matched

        # Load raw dataframes
        df_status_raw = pd.read_excel(excel_file, sheet_name=resolved_sheets['status']).dropna(how='all')
        df_bank_raw = pd.read_excel(excel_file, sheet_name=resolved_sheets['bank statement']).dropna(how='all')
        df_summary_raw = pd.read_excel(excel_file, sheet_name=resolved_sheets['summary'], header=None)
        df_ola_raw = pd.read_excel(excel_file, sheet_name=resolved_sheets['ola report']).dropna(how='all')

        # Clean column names
        df_status_raw.columns = [str(c).strip() for c in df_status_raw.columns]
        df_bank_raw.columns = [str(c).strip() for c in df_bank_raw.columns]
        df_ola_raw.columns = [str(c).strip() for c in df_ola_raw.columns]

        # Determine Monday to Sunday week boundary
        week_start, week_end = cls.determine_week_boundary(df_status_raw, df_summary_raw, df_ola_raw)

        # 1. Transform Status tab
        df_status = cls._process_status(df_status_raw, file_id, file_name, week_start, week_end)

        # 2. Transform Bank Statement tab
        df_bank = cls._process_bank_statement(df_bank_raw, file_id, file_name, week_start, week_end)

        # 3. Transform Summary tab (unpivoting into date, report_type category, amounts)
        df_summary = cls._process_summary(df_summary_raw, file_id, file_name, week_start, week_end)

        # 4. Transform Ola Report tab
        df_ola = cls._process_ola_report(df_ola_raw, file_id, file_name, week_start, week_end)

        counts = {
            "status": len(df_status),
            "bank_statement": len(df_bank),
            "summary": len(df_summary),
            "ola_report": len(df_ola),
            "total": len(df_status) + len(df_bank) + len(df_summary) + len(df_ola)
        }

        logger.info(
            f"Parsed file successfully: Status={counts['status']}, Bank={counts['bank_statement']}, "
            f"Summary={counts['summary']}, OlaReport={counts['ola_report']} (Total: {counts['total']} rows)"
        )

        return {
            "file_id": file_id,
            "file_name": file_name,
            "week_start": week_start,
            "week_end": week_end,
            "counts": counts,
            "status": df_status,
            "bank_statement": df_bank,
            "summary": df_summary,
            "ola_report": df_ola
        }

    @staticmethod
    def _clean_numeric(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors='coerce').fillna(0.0)

    @classmethod
    def _process_status(cls, df: pd.DataFrame, file_id: str, file_name: str, week_start: date, week_end: date) -> pd.DataFrame:
        df = df.copy()
        # Drop rows where essential identifiers are empty
        df = df[df['Car number'].notna() | df['Amount Raw'].notna()]

        res = pd.DataFrame()
        res['date'] = pd.to_datetime(df.get('Date'), errors='coerce').dt.date
        res['type'] = df.get('Type').astype(str).replace({'nan': None, 'None': None})
        res['car_number'] = df.get('Car number').astype(str).str.strip().replace({'nan': None, 'None': None})
        res['car_model'] = df.get('Car model').astype(str).str.strip().replace({'nan': None, 'None': None})
        res['date_for'] = pd.to_datetime(df.get('Date for'), errors='coerce').dt.date
        res['amount_raw'] = cls._clean_numeric(df.get('Amount Raw', 0))
        res['sub_category'] = df.get('Sub Category').astype(str).replace({'nan': None, 'None': None})
        res['payment_type'] = df.get('Payment type').astype(str).replace({'nan': None, 'None': None})
        res['status'] = df.get('Status').astype(str).replace({'nan': None, 'None': None})
        res['actual_incentive'] = cls._clean_numeric(df.get('Actual Incentive', 0))
        res['actual_ondemand'] = cls._clean_numeric(df.get('Actual Ondemand', 0))
        res['instapay_transfer'] = cls._clean_numeric(df.get('instapay_transfer', 0))
        res['total_online_payment'] = cls._clean_numeric(df.get('Total Online payment', 0))
        res['source_file_name'] = file_name
        res['source_file_id'] = file_id
        res['week_start_date'] = week_start
        res['week_end_date'] = week_end
        return res

    @classmethod
    def _process_bank_statement(cls, df: pd.DataFrame, file_id: str, file_name: str, week_start: date, week_end: date) -> pd.DataFrame:
        df = df.copy()
        # Drop rows without UTR or Amount
        df = df[df['UTR'].notna() | df['AMOUNT'].notna()]

        res = pd.DataFrame()
        res['date'] = pd.to_datetime(df.get('DATE'), errors='coerce').dt.date
        res['utr'] = df.get('UTR').astype(str).str.strip().replace({'nan': None, 'None': None})
        res['amount'] = cls._clean_numeric(df.get('AMOUNT', 0))
        res['vehicles'] = df.get('Vehicles').astype(str).str.strip().replace({'nan': None, 'None': None})
        res['city'] = df.get('City').astype(str).str.strip().replace({'nan': None, 'None': None})
        res['status'] = df.get('Status').astype(str).replace({'nan': None, 'None': None})
        res['reason'] = df.get('Reason').astype(str).replace({'nan': None, 'None': None})
        res['actual_incentive'] = cls._clean_numeric(df.get('Actual Incentive', 0))
        res['actual_ondemand'] = cls._clean_numeric(df.get('Actual Ondemand', 0))
        res['instapay_transfer'] = cls._clean_numeric(df.get('instapay_transfer', 0))
        res['total_online_payment'] = cls._clean_numeric(df.get('Total Online payment', 0))
        res['source_file_name'] = file_name
        res['source_file_id'] = file_id
        res['week_start_date'] = week_start
        res['week_end_date'] = week_end
        return res

    @classmethod
    def _process_summary(cls, df_raw: pd.DataFrame, file_id: str, file_name: str, week_start: date, week_end: date) -> pd.DataFrame:
        """
        Unpivots Summary sheet into normalized rows:
        Columns: date, report_type ('Ola report' | 'Bank statement'), actual_incentive, actual_ondemand,
                 instapay_transfer, total_online_payment, source_file_name, source_file_id, week_start_date, week_end_date
        """
        rows = []
        for idx in range(2, len(df_raw)):
            date_val = df_raw.iloc[idx, 0]
            if pd.isna(date_val):
                continue
            date_str = str(date_val).strip().lower()
            if date_str in ['diff', 'difference', 'variance']:
                continue

            # Handle the Total row from Excel
            if date_str == 'total':
                rows.append({
                    'date': week_end,
                    'report_type': 'Ola report',
                    'actual_incentive': float(df_raw.iloc[idx, 1]) if pd.notna(df_raw.iloc[idx, 1]) else 0.0,
                    'actual_ondemand': float(df_raw.iloc[idx, 2]) if pd.notna(df_raw.iloc[idx, 2]) else 0.0,
                    'instapay_transfer': float(df_raw.iloc[idx, 3]) if pd.notna(df_raw.iloc[idx, 3]) else 0.0,
                    'total_online_payment': float(df_raw.iloc[idx, 4]) if pd.notna(df_raw.iloc[idx, 4]) else 0.0,
                    'is_total': True,
                    'source_file_name': file_name,
                    'source_file_id': file_id,
                    'week_start_date': week_start,
                    'week_end_date': week_end
                })
                rows.append({
                    'date': week_end,
                    'report_type': 'Bank statement',
                    'actual_incentive': float(df_raw.iloc[idx, 5]) if pd.notna(df_raw.iloc[idx, 5]) else 0.0,
                    'actual_ondemand': float(df_raw.iloc[idx, 6]) if pd.notna(df_raw.iloc[idx, 6]) else 0.0,
                    'instapay_transfer': float(df_raw.iloc[idx, 7]) if pd.notna(df_raw.iloc[idx, 7]) else 0.0,
                    'total_online_payment': float(df_raw.iloc[idx, 8]) if pd.notna(df_raw.iloc[idx, 8]) else 0.0,
                    'is_total': True,
                    'source_file_name': file_name,
                    'source_file_id': file_id,
                    'week_start_date': week_start,
                    'week_end_date': week_end
                })
                continue

            try:
                parsed_date = pd.to_datetime(date_val).date()
            except Exception:
                continue

            # Block 1: Ola report category (cols 1..4)
            rows.append({
                'date': parsed_date,
                'report_type': 'Ola report',
                'actual_incentive': float(df_raw.iloc[idx, 1]) if pd.notna(df_raw.iloc[idx, 1]) else 0.0,
                'actual_ondemand': float(df_raw.iloc[idx, 2]) if pd.notna(df_raw.iloc[idx, 2]) else 0.0,
                'instapay_transfer': float(df_raw.iloc[idx, 3]) if pd.notna(df_raw.iloc[idx, 3]) else 0.0,
                'total_online_payment': float(df_raw.iloc[idx, 4]) if pd.notna(df_raw.iloc[idx, 4]) else 0.0,
                'is_total': False,
                'source_file_name': file_name,
                'source_file_id': file_id,
                'week_start_date': week_start,
                'week_end_date': week_end
            })

            # Block 2: Bank statement category (cols 5..8)
            rows.append({
                'date': parsed_date,
                'report_type': 'Bank statement',
                'actual_incentive': float(df_raw.iloc[idx, 5]) if pd.notna(df_raw.iloc[idx, 5]) else 0.0,
                'actual_ondemand': float(df_raw.iloc[idx, 6]) if pd.notna(df_raw.iloc[idx, 6]) else 0.0,
                'instapay_transfer': float(df_raw.iloc[idx, 7]) if pd.notna(df_raw.iloc[idx, 7]) else 0.0,
                'total_online_payment': float(df_raw.iloc[idx, 8]) if pd.notna(df_raw.iloc[idx, 8]) else 0.0,
                'is_total': False,
                'source_file_name': file_name,
                'source_file_id': file_id,
                'week_start_date': week_start,
                'week_end_date': week_end
            })

        return pd.DataFrame(rows)

    @classmethod
    def _process_ola_report(cls, df: pd.DataFrame, file_id: str, file_name: str, week_start: date, week_end: date) -> pd.DataFrame:
        df = df.copy()
        # Clean column mapping
        col_map = {c.strip().lower(): c for c in df.columns}

        # Filter empty rows
        car_col = col_map.get('car number')
        amt_col = col_map.get('amount raw')
        if car_col and amt_col:
            df = df[df[car_col].notna() | df[amt_col].notna()]

        res = pd.DataFrame()
        date_col = col_map.get('date')
        res['date'] = pd.to_datetime(df[date_col], errors='coerce').dt.date if date_col else None
        res['type'] = df[col_map['type']].astype(str).replace({'nan': None, 'None': None}) if 'type' in col_map else None
        res['car_number'] = df[col_map['car number']].astype(str).str.strip().replace({'nan': None, 'None': None}) if 'car number' in col_map else None
        res['car_model'] = df[col_map['car model']].astype(str).str.strip().replace({'nan': None, 'None': None}) if 'car model' in col_map else None
        res['date_for'] = pd.to_datetime(df[col_map['date for']], errors='coerce').dt.date if 'date for' in col_map else None
        res['amount_raw'] = cls._clean_numeric(df[col_map['amount raw']]) if 'amount raw' in col_map else 0.0
        res['status'] = df[col_map['status']].astype(str).replace({'nan': None, 'None': None}) if 'status' in col_map else None
        res['sub_category'] = df[col_map['sub category']].astype(str).replace({'nan': None, 'None': None}) if 'sub category' in col_map else None
        res['payment_type'] = df[col_map['payment type']].astype(str).replace({'nan': None, 'None': None}) if 'payment type' in col_map else None
        res['source_file_name'] = file_name
        res['source_file_id'] = file_id
        res['week_start_date'] = week_start
        res['week_end_date'] = week_end
        return res

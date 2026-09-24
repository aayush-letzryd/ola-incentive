# Ola Incentive Automated Ingestion & Transformation Pipeline

[![ETL Pipeline](https://img.shields.io/badge/Pipeline-PostgreSQL%20%7C%20Google%20Drive-blue.svg)](https://github.com/aayush-letzryd/ola-incentive)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://python.org)
[![Cloud Run Ready](https://img.shields.io/badge/GCP-Cloud%20Run%20%2B%20Scheduler-orange.svg)](https://cloud.google.com/run)

Production-grade automated pipeline designed for **LetzRyd** to discover, ingest, normalize, and reconcile weekly Ola Incentive Excel workbooks from Google Drive directly into the PostgreSQL database.

---

## 📌 Executive Summary & Requirements

LetzRyd receives weekly Ola Incentive Excel workbooks uploaded to a designated Google Drive folder. Each file represents an operating week (Monday to Sunday) and contains four key tabs:
1. **Status**: Granular transaction status matched against fleet vehicles.
2. **Bank statement**: Raw incoming bank credits, IMPS/UTR transfers, and matched payouts.
3. **Summary**: Daily aggregates comparing Ola Report vs Bank Statement across key financial metrics.
4. **Ola Report**: Raw daily platform reports, fees, platform collections, and car model records.

### Key Operational Challenges Solved
* **Arbitrary Filenames**: Files can be uploaded with arbitrary names (e.g. `24-08-2026 (1).xlsx`, `07-09-2026.xlsx`, `ola_incentives_w37.xlsx`). The pipeline inspects internal date fields (`Date for` and sheet dates) to dynamically deduce the exact Monday–Sunday operating week.
* **Unpivoting the "Weird" Summary Sheet**: The raw `Summary` tab has multi-level headers with side-by-side metric blocks. The pipeline automatically normalizes this into a clean relational table categorized by `report_type` (`Ola report` vs `Bank statement`).
* **Zero Duplication & Idempotency**: Safe atomic replacement per file/week. Re-running the pipeline or reprocessing files never produces duplicate rows.
* **Audit & Execution Logging**: Complete pipeline tracking in `sheet_ola_incentive_pipeline_logs` recording run status, timestamps, row counts per sheet, and error traces.

---

## 🏛 Architecture & Data Flow

```
                      +-----------------------------+
                      |     Google Drive Folder     |
                      |   (New / Updated .xlsx)     |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |     DriveScanner Engine     |
                      |  * Public Scraper (Zero Auth|
                      |  * Service Account API      |
                      +--------------+--------------+
                                     | (Download)
                                     v
                      +-----------------------------+
                      |    ExcelProcessor Engine    |
                      |  * Dynamic Week Detection   |
                      |  * Sheet Schema Validation  |
                      |  * Unpivot Summary Tab      |
                      +--------------+--------------+
                                     | (Normalized DataFrames)
                                     v
                      +-----------------------------+
                      |       DBLoader Engine       |
                      |  * Atomic Transaction       |
                      |  * Batch Copy (execute_values)
                      +--------------+--------------+
                                     |
         +---------------------------+---------------------------+
         |                           |                           |
         v                           v                           v
+------------------+       +-------------------+       +--------------------+
| Status Table     |       | Bank Statement    |       | Summary Table      |
| (sheet_status)   |       | (sheet_bank_stmt) |       | (Unpivoted metrics)|
+------------------+       +-------------------+       +--------------------+
         |                           |                           |
         +---------------------------+---------------------------+
                                     |
                                     v
                     +----------------------------------+
                     | Ola Report Table & Pipeline Logs |
                     | (Full audit trail & row counts)  |
                     +----------------------------------+
```

---

## 📊 Database Schema & Tables

All tables reside in the `public` schema in PostgreSQL:

| Table Name | Description | Key Columns |
| :--- | :--- | :--- |
| `sheet_ola_incentive_status` | Status tab containing vehicle matching and payouts | `date`, `car_number`, `date_for`, `amount_raw`, `status`, `actual_incentive`, `actual_ondemand`, `instapay_transfer`, `total_online_payment`, `week_start_date` |
| `sheet_ola_incentive_bank_statement` | Bank statement credits and IMPS UTR transfers | `date`, `utr`, `amount`, `vehicles`, `city`, `status`, `reason`, `actual_incentive`, `actual_ondemand`, `instapay_transfer`, `week_start_date` |
| `sheet_ola_incentive_summary` | Normalized daily summary categorized by report type | `date`, `report_type` (`Ola report` / `Bank statement`), `actual_incentive`, `actual_ondemand`, `instapay_transfer`, `total_online_payment`, `week_start_date` |
| `sheet_ola_incentive_ola_report` | Raw Ola platform transaction report | `date`, `type`, `car_number`, `car_model`, `date_for`, `amount_raw`, `status`, `sub_category`, `payment_type`, `week_start_date` |
| `sheet_ola_incentive_pipeline_logs` | Audit log of every pipeline execution cycle | `file_id`, `file_name`, `status_rows_count`, `bank_statement_rows_count`, `summary_rows_count`, `ola_report_rows_count`, `total_rows_count`, `execution_status`, `started_at`, `completed_at` |

---

## 🔄 Summary Tab Transformation (Unpivoting)

The raw `Summary` tab in the Excel workbook is formatted as:
```text
Row 1: [ Date ] [ ---------- Ola report ---------- ] [ -------- Bank statement -------- ]
Row 2: [      ] [ Incentive | Ondemand | InstaPay | Total ] [ Incentive | Ondemand | InstaPay | Total ]
Row 3: [2026-09-07] [  96616   |    0     |    0     |   0   ] [  97351.2 |    0     |    0     |   0   ]
```

The pipeline unpivots each day into **two normalized rows**:
```text
Date        | report_type     | actual_incentive | actual_ondemand | instapay_transfer | total_online_payment
2026-09-07  | Ola report      | 96616.00         | 0.00            | 0.00              | 0.00
2026-09-07  | Bank statement  | 97351.24         | 0.00            | 0.00              | 0.00
```
This enables clean SQL aggregations, time-series dashboards (Metabase, Looker Studio), and automated variance checks.

---

## 📅 Dynamic Week Determination

Because filenames vary, the pipeline deduces the operational week directly from the internal records:
1. Gathers dates from `Date for` in `Status` and `Ola Report` tabs.
2. Identifies the minimum date.
3. Computes `week_start_date = min_date - min_date.weekday()` (Monday).
4. Computes `week_end_date = week_start_date + 6 days` (Sunday).
5. Tags every record across all 4 tables with `week_start_date` and `week_end_date`.

---

## 🚀 Deployment Approaches in GCP

We recommend **Option 1 (Cloud Run Jobs + Cloud Scheduler)** as the production gold standard for serverless data pipelines on GCP.

### Option 1: Cloud Run Jobs + Cloud Scheduler (Recommended)

* **Architecture**: A lightweight container packaged with the pipeline code deployed to Cloud Run Jobs, invoked 2–3 times daily by Cloud Scheduler.
* **Cost**: ~$0.00 / month (runs in seconds, fully covered under GCP Free Tier).
* **Reliability**: No long-running VMs to maintain, built-in retry mechanisms, native Cloud Logging.

#### Step 1: Deploy with the automated script
```bash
chmod +x deploy_gcp.sh
GCP_PROJECT_ID="your-gcp-project-id" GCP_REGION="asia-south1" ./deploy_gcp.sh
```

#### Step 2: Manual Trigger / Test
```bash
gcloud run jobs execute ola-incentive-etl-job --region asia-south1
```

#### Schedule Details
* **Cron Expression**: `0 9,15,21 * * *` (Runs at 09:00, 15:00, and 21:00 UTC, i.e., 2:30 PM, 8:30 PM, 2:30 AM IST).
* Can be customized to run at any frequency (e.g., hourly or once daily).

---

### Option 2: GitHub Actions Scheduler (Zero-Infra Alternative)

This repository includes a turnkey GitHub Actions workflow at [`.github/workflows/scheduled_etl.yml`](.github/workflows/scheduled_etl.yml).

1. Go to repository **Settings > Secrets and variables > Actions**.
2. Add the following repository secrets:
   * `DB_HOST`: `35.200.196.113`
   * `DB_PORT`: `5432`
   * `DB_NAME`: `postgres`
   * `DB_USER`: `postgres`
   * `DB_PASS`: Your PostgreSQL password
   * `GDRIVE_FOLDER_ID`: `1BXtva5QfEOGvVmCKBxJxgpJnDDLpSBbC`
3. The workflow runs automatically 3 times a day (`0 4,10,16 * * *` UTC) and can also be triggered manually on demand via the **Run workflow** button.

---

### Option 3: Host on Existing VM / Server via Cron

If LetzRyd prefers to run the pipeline on the existing backend VM:
```bash
# Add to crontab:
crontab -e

# Run at 10:00, 16:00, and 22:00 IST every day
0 10,16,22 * * * cd /opt/ola-incentive && /opt/ola-incentive/.venv/bin/python main.py --run-once >> /var/log/ola_etl.log 2>&1
```

---

## 💻 Local Setup & Development

### 1. Clone & Setup Environment
```bash
git clone git@github.com:aayush-letzryd/ola-incentive.git
cd ola-incentive

python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and configure your credentials:
```ini
DB_HOST=35.200.196.113
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASS=your_password
GDRIVE_FOLDER_ID=1BXtva5QfEOGvVmCKBxJxgpJnDDLpSBbC
LOG_LEVEL=INFO
```

### 3. CLI Commands
```bash
# Run single ingestion cycle across Google Drive folder
python main.py --run-once

# Force re-ingestion of already processed files
python main.py --run-once --force

# Ingest a specific local Excel file
python main.py --local-file "C:\Users\anura\Downloads\07-09-2026.xlsx"

# Run as continuous background daemon polling every hour
python main.py --poll --interval 3600

# Initialize or verify database schema only
python main.py --init-db
```

---

## 📈 Monitoring & Health Checks

Verify pipeline status at any time directly in PostgreSQL:
```sql
-- Check last 10 execution cycles
SELECT 
    id,
    file_name,
    week_start_date,
    week_end_date,
    status_rows_count,
    bank_statement_rows_count,
    summary_rows_count,
    ola_report_rows_count,
    total_rows_count,
    execution_status,
    completed_at
FROM public.sheet_ola_incentive_pipeline_logs
ORDER BY id DESC
LIMIT 10;
```

---

## 🛡 License & Confidentiality
Proprietary software developed for **LetzRyd**. All rights reserved.

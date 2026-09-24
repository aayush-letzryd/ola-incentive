-- ========================================================================
-- Ola Incentive Data Pipeline DDL & Schema Definitions
-- Target Database: PostgreSQL 14+ / Cloud SQL
-- ========================================================================

-- 1. Status Tab Table
CREATE TABLE IF NOT EXISTS public.sheet_ola_incentive_status (
    id BIGSERIAL PRIMARY KEY,
    date DATE,
    type VARCHAR(100),
    car_number VARCHAR(50),
    car_model VARCHAR(100),
    date_for DATE,
    amount_raw NUMERIC(14,2),
    sub_category VARCHAR(100),
    payment_type VARCHAR(50),
    status VARCHAR(50),
    actual_incentive NUMERIC(14,2) DEFAULT 0,
    actual_ondemand NUMERIC(14,2) DEFAULT 0,
    instapay_transfer NUMERIC(14,2) DEFAULT 0,
    total_online_payment NUMERIC(14,2) DEFAULT 0,
    source_file_name VARCHAR(255) NOT NULL,
    source_file_id VARCHAR(255) NOT NULL,
    week_start_date DATE,
    week_end_date DATE,
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ola_status_source_file ON public.sheet_ola_incentive_status(source_file_id);
CREATE INDEX IF NOT EXISTS idx_ola_status_date_for ON public.sheet_ola_incentive_status(date_for);
CREATE INDEX IF NOT EXISTS idx_ola_status_car_number ON public.sheet_ola_incentive_status(car_number);
CREATE INDEX IF NOT EXISTS idx_ola_status_week_start ON public.sheet_ola_incentive_status(week_start_date);

-- 2. Bank Statement Tab Table
CREATE TABLE IF NOT EXISTS public.sheet_ola_incentive_bank_statement (
    id BIGSERIAL PRIMARY KEY,
    date DATE,
    utr TEXT,
    amount NUMERIC(14,2) DEFAULT 0,
    vehicles VARCHAR(100),
    city VARCHAR(50),
    status VARCHAR(50),
    reason VARCHAR(255),
    actual_incentive NUMERIC(14,2) DEFAULT 0,
    actual_ondemand NUMERIC(14,2) DEFAULT 0,
    instapay_transfer NUMERIC(14,2) DEFAULT 0,
    total_online_payment NUMERIC(14,2) DEFAULT 0,
    source_file_name VARCHAR(255) NOT NULL,
    source_file_id VARCHAR(255) NOT NULL,
    week_start_date DATE,
    week_end_date DATE,
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ola_bank_source_file ON public.sheet_ola_incentive_bank_statement(source_file_id);
CREATE INDEX IF NOT EXISTS idx_ola_bank_date ON public.sheet_ola_incentive_bank_statement(date);
CREATE INDEX IF NOT EXISTS idx_ola_bank_utr ON public.sheet_ola_incentive_bank_statement(utr);
CREATE INDEX IF NOT EXISTS idx_ola_bank_vehicles ON public.sheet_ola_incentive_bank_statement(vehicles);
CREATE INDEX IF NOT EXISTS idx_ola_bank_week_start ON public.sheet_ola_incentive_bank_statement(week_start_date);

-- 3. Normalized Summary Tab Table (Unpivoted into date + report_type category)
CREATE TABLE IF NOT EXISTS public.sheet_ola_incentive_summary (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    report_type VARCHAR(100) NOT NULL, -- 'Ola report' or 'Bank statement'
    actual_incentive NUMERIC(14,2) DEFAULT 0,
    actual_ondemand NUMERIC(14,2) DEFAULT 0,
    instapay_transfer NUMERIC(14,2) DEFAULT 0,
    total_online_payment NUMERIC(14,2) DEFAULT 0,
    is_total BOOLEAN DEFAULT FALSE,
    source_file_name VARCHAR(255) NOT NULL,
    source_file_id VARCHAR(255) NOT NULL,
    week_start_date DATE,
    week_end_date DATE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ola_summary_source_file ON public.sheet_ola_incentive_summary(source_file_id);
CREATE INDEX IF NOT EXISTS idx_ola_summary_date ON public.sheet_ola_incentive_summary(date);
CREATE INDEX IF NOT EXISTS idx_ola_summary_report_type ON public.sheet_ola_incentive_summary(report_type);
CREATE INDEX IF NOT EXISTS idx_ola_summary_is_total ON public.sheet_ola_incentive_summary(is_total);
CREATE INDEX IF NOT EXISTS idx_ola_summary_week_start ON public.sheet_ola_incentive_summary(week_start_date);

-- 4. Ola Report Tab Table
CREATE TABLE IF NOT EXISTS public.sheet_ola_incentive_ola_report (
    id BIGSERIAL PRIMARY KEY,
    date DATE,
    type VARCHAR(100),
    car_number VARCHAR(50),
    car_model VARCHAR(100),
    date_for DATE,
    amount_raw NUMERIC(14,2) DEFAULT 0,
    status VARCHAR(50),
    sub_category VARCHAR(100),
    payment_type VARCHAR(50),
    source_file_name VARCHAR(255) NOT NULL,
    source_file_id VARCHAR(255) NOT NULL,
    week_start_date DATE,
    week_end_date DATE,
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ola_report_source_file ON public.sheet_ola_incentive_ola_report(source_file_id);
CREATE INDEX IF NOT EXISTS idx_ola_report_date ON public.sheet_ola_incentive_ola_report(date);
CREATE INDEX IF NOT EXISTS idx_ola_report_date_for ON public.sheet_ola_incentive_ola_report(date_for);
CREATE INDEX IF NOT EXISTS idx_ola_report_car_number ON public.sheet_ola_incentive_ola_report(car_number);
CREATE INDEX IF NOT EXISTS idx_ola_report_week_start ON public.sheet_ola_incentive_ola_report(week_start_date);

-- 5. Ingestion Pipeline Runs & Audit Logs Table
CREATE TABLE IF NOT EXISTS public.sheet_ola_incentive_pipeline_logs (
    id BIGSERIAL PRIMARY KEY,
    file_id VARCHAR(255) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    drive_modified_time TIMESTAMPTZ,
    week_start_date DATE,
    week_end_date DATE,
    status_rows_count INTEGER DEFAULT 0,
    bank_statement_rows_count INTEGER DEFAULT 0,
    summary_rows_count INTEGER DEFAULT 0,
    ola_report_rows_count INTEGER DEFAULT 0,
    total_rows_count INTEGER DEFAULT 0,
    execution_status VARCHAR(50) NOT NULL, -- 'SUCCESS', 'FAILED', 'IN_PROGRESS', 'SKIPPED'
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ola_pipeline_file_id ON public.sheet_ola_incentive_pipeline_logs(file_id);
CREATE INDEX IF NOT EXISTS idx_ola_pipeline_status ON public.sheet_ola_incentive_pipeline_logs(execution_status);
CREATE INDEX IF NOT EXISTS idx_ola_pipeline_week ON public.sheet_ola_incentive_pipeline_logs(week_start_date);

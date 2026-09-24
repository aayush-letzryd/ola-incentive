#!/bin/bash
# ========================================================================
# LetzRyd Ola Incentive Pipeline - GCP Deployment Script
# Provisions:
# 1. Cloud Run Job (Serverless Container Runner)
# 2. Cloud Scheduler (Triggers the Job 3 times daily)
# ========================================================================

set -e

# Configuration (Customize as needed)
PROJECT_ID=${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}
REGION=${GCP_REGION:-"asia-south1"}
JOB_NAME="ola-incentive-etl-job"
REPO_NAME="ola-repo"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/ola-incentive-etl:latest"
SCHEDULER_JOB_NAME="ola-incentive-daily-trigger"
CRON_SCHEDULE="0 9,15,21 * * *" # Runs 3 times a day at 09:00, 15:00, 21:00 UTC
TIMEZONE="Asia/Kolkata"

if [ -z "$PROJECT_ID" ]; then
    echo "ERROR: GCP_PROJECT_ID is not set and could not be detected from gcloud config."
    echo "Usage: GCP_PROJECT_ID=your-project-id ./deploy_gcp.sh"
    exit 1
fi

echo "=========================================================="
echo "Deploying Ola Incentive Pipeline to GCP"
echo "Project ID : ${PROJECT_ID}"
echo "Region     : ${REGION}"
echo "Repository : ${REPO_NAME}"
echo "Image      : ${IMAGE_NAME}"
echo "Job Name   : ${JOB_NAME}"
echo "Scheduler  : ${CRON_SCHEDULE} (${TIMEZONE})"
echo "=========================================================="

# 1. Enable Required GCP APIs
echo "Step 1: Enabling necessary Google Cloud APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project="${PROJECT_ID}"

# 2. Ensure Artifact Registry Docker Repository Exists
echo "Step 2: Checking Artifact Registry repository..."
if ! gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Creating Artifact Registry repository '${REPO_NAME}' in ${REGION}..."
    gcloud artifacts repositories create "${REPO_NAME}" \
        --repository-format=docker \
        --location="${REGION}" \
        --description="Docker repository for Ola Incentive pipeline" \
        --project="${PROJECT_ID}"
fi

# 3. Build and Push Container Image using Cloud Build
echo "Step 3: Building container image via Cloud Build..."
gcloud builds submit --tag "${IMAGE_NAME}" --project="${PROJECT_ID}"

DEFAULT_PASS='8S5]U3@L^Xz)\FH}'
PASS_TO_USE="${DB_PASS:-$DEFAULT_PASS}"

# 3. Deploy or Update Cloud Run Job
echo "Step 3: Deploying Cloud Run Job..."
gcloud run jobs deploy "${JOB_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${REGION}" \
    --tasks=1 \
    --max-retries=1 \
    --task-timeout=15m \
    --memory=1Gi \
    --cpu=1 \
    --set-env-vars="DB_HOST=${DB_HOST:-35.200.196.113},DB_PORT=${DB_PORT:-5432},DB_NAME=${DB_NAME:-postgres},DB_USER=${DB_USER:-postgres},DB_PASS=${PASS_TO_USE},GDRIVE_FOLDER_ID=${GDRIVE_FOLDER_ID:-1BXtva5QfEOGvVmCKBxJxgpJnDDLpSBbC},LOG_LEVEL=INFO" \
    --project="${PROJECT_ID}"

# 4. Create Service Account for Cloud Scheduler if needed
echo "Step 4: Setting up Cloud Scheduler Service Account..."
SA_NAME="ola-pipeline-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="Ola Incentive Pipeline Invoker" \
        --project="${PROJECT_ID}"
fi

# Grant Cloud Run Invoker role
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.invoker" >/dev/null

# 5. Create or Update Cloud Scheduler Job
echo "Step 5: Provisioning Cloud Scheduler Job..."
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Updating existing scheduler job..."
    gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
        --location="${REGION}" \
        --schedule="${CRON_SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SA_EMAIL}" \
        --project="${PROJECT_ID}"
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
        --location="${REGION}" \
        --schedule="${CRON_SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SA_EMAIL}" \
        --project="${PROJECT_ID}"
fi

echo "=========================================================="
echo "Deployment Complete!"
echo "To test the job manually immediately:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT_ID}"
echo "=========================================================="

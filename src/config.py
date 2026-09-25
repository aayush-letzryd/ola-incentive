import os
import sys
from dotenv import load_dotenv

# Automatically search for .env in current directory or parent directories
load_dotenv()

DB_HOST = os.getenv("DB_HOST") or "35.200.196.113"
DB_PORT = int(os.getenv("DB_PORT") or "5432")
DB_NAME = os.getenv("DB_NAME") or "postgres"
DB_USER = os.getenv("DB_USER") or "postgres"
DB_PASS = os.getenv("DB_PASS") or r"8S5]U3@L^Xz)\FH}"

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID") or "1BXtva5QfEOGvVmCKBxJxgpJnDDLpSBbC"
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

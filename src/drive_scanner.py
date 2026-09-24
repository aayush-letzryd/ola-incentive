import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger("OlaETL.DriveScanner")

class DriveScanner:
    """
    Handles discovery and downloading of files from Google Drive.
    Supports both Google Drive API (Service Account) and direct public web scraping fallback.
    """

    def __init__(self, folder_id: str, credentials_path: Optional[str] = None):
        self.folder_id = folder_id
        self.credentials_path = credentials_path
        self.drive_service = None

        if self.credentials_path and os.path.exists(self.credentials_path):
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
                self.drive_service = build('drive', 'v3', credentials=creds)
                logger.info("Initialized Google Drive API client using Service Account credentials.")
            except Exception as e:
                logger.warning(f"Failed to initialize Drive API client: {e}. Falling back to public web scraper.")

    def list_xlsx_files(self) -> List[Dict]:
        """Lists all .xlsx files in the configured folder."""
        if self.drive_service:
            return self._list_files_api()
        return self._list_files_public_web()

    def _list_files_api(self) -> List[Dict]:
        """Lists files using official Google Drive API."""
        try:
            query = f"'{self.folder_id}' in parents and mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' and trashed = false"
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, modifiedTime, size)",
                orderBy="modifiedTime desc"
            ).execute()
            items = results.get('files', [])
            logger.info(f"Drive API returned {len(items)} files from folder.")
            return items
        except Exception as e:
            logger.error(f"Error listing files via Drive API: {e}. Attempting public web scraper fallback...")
            return self._list_files_public_web()

    def _list_files_public_web(self) -> List[Dict]:
        """Lists files by parsing the public Google Drive folder page."""
        url = f"https://drive.google.com/drive/folders/{self.folder_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to access Google Drive folder {self.folder_id}: HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, 'html.parser')
        files = []
        seen_ids = set()

        # Strategy 1: Find text nodes ending with .xlsx and resolve parent data-id
        for item in soup.find_all(string=re.compile(r'\.xlsx$', re.IGNORECASE)):
            fname = item.strip()
            parent = item.find_parent(attrs={"data-id": True})
            if parent:
                fid = parent.get("data-id")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    files.append({
                        "id": fid,
                        "name": fname,
                        "modifiedTime": None,
                        "size": None
                    })

        # Strategy 2: Fallback to searching data-id elements directly
        if not files:
            for div in soup.find_all(attrs={"data-id": True}):
                fid = div.get("data-id")
                text = div.get_text(strip=True)
                tooltip = div.get("data-tooltip", "")
                full_str = f"{tooltip} {text}"
                
                m = re.search(r'([\w\s\(\)\-\.]+\.xlsx)', full_str, re.IGNORECASE)
                if m and fid not in seen_ids:
                    fname = m.group(1).strip()
                    # Strip common prefix artifacts if any
                    for prefix in ['Microsoft Excel', 'Shared']:
                        if fname.lower().startswith(prefix.lower()):
                            fname = fname[len(prefix):].strip()
                    seen_ids.add(fid)
                    files.append({
                        "id": fid,
                        "name": fname,
                        "modifiedTime": None,
                        "size": None
                    })

        logger.info(f"Public Drive scraper discovered {len(files)} .xlsx file(s) in folder.")
        return files

    def download_file(self, file_id: str, dest_path: str) -> str:
        """Downloads a file from Google Drive to local destination."""
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        if self.drive_service:
            try:
                import io
                from googleapiclient.http import MediaIoBaseDownload
                request = self.drive_service.files().get_media(fileId=file_id)
                with io.FileIO(dest_path, 'wb') as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                logger.info(f"Downloaded file {file_id} via Drive API to {dest_path}")
                return dest_path
            except Exception as e:
                logger.warning(f"Drive API download failed: {e}. Falling back to direct URL download...")

        # Direct HTTP download fallback
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        session = requests.Session()
        resp = session.get(download_url, stream=True, timeout=60)
        
        # Check for virus scan confirmation token on larger files
        for k, v in resp.cookies.items():
            if k.startswith('download_warning'):
                download_url_confirmed = f"{download_url}&confirm={v}"
                resp = session.get(download_url_confirmed, stream=True, timeout=60)
                break

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download file {file_id}: HTTP {resp.status_code}")

        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)

        # Validate that the file is a valid zip/xlsx archive
        with open(dest_path, 'rb') as f:
            header = f.read(2)
            if header != b'PK':
                raise ValueError(f"Downloaded file {dest_path} is not a valid Excel (.xlsx) file.")

        logger.info(f"Downloaded file {file_id} to {dest_path} ({os.path.getsize(dest_path):,} bytes)")
        return dest_path

"""Đồng bộ tài liệu từ một thư mục Google Drive (kể cả thư mục con).

    python manage.py sync_drive [--force] [--folder <ID>]

Cần: GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_DRIVE_FOLDER_ID và gói
google-api-python-client + google-auth. Thiếu cấu hình → in hướng dẫn và thoát 0.
"""

import io
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from files.extract import extract_text, is_supported
from files.models import Document

FOLDER_MIME = "application/vnd.google-apps.folder"
# Google Docs/Sheets/Slides không tải trực tiếp được → export sang văn bản.
EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
LIST_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink, size)"

INSTRUCTIONS = """
Chưa cấu hình đồng bộ Google Drive. Cách thiết lập:

  1. Vào https://console.cloud.google.com → tạo (hoặc chọn) một project,
     bật "Google Drive API" (APIs & Services → Library).
  2. APIs & Services → Credentials → Create credentials → Service account.
     Mở service account vừa tạo → tab Keys → Add key → JSON, tải file khoá
     về máy chủ (ví dụ /etc/task-manager/drive-sa.json, không commit vào git).
  3. Trên Google Drive, mở thư mục tài liệu của Khoa → Chia sẻ (Share) →
     thêm email của service account (dạng ...@...iam.gserviceaccount.com)
     với quyền "Người xem" (Viewer).
  4. Lấy ID thư mục: phần cuối của URL
     https://drive.google.com/drive/folders/<ID_THƯ_MỤC>
  5. Đặt biến môi trường rồi chạy lại lệnh:
       export GOOGLE_SERVICE_ACCOUNT_FILE=/etc/task-manager/drive-sa.json
       export GOOGLE_DRIVE_FOLDER_ID=<ID_THƯ_MỤC>
       python manage.py sync_drive
  6. Cài thư viện nếu chưa có:
       pip install google-api-python-client google-auth

Gợi ý: đặt cron chạy định kỳ, ví dụ mỗi giờ:
  0 * * * * cd /duong/dan/task-manager && .venv/bin/python manage.py sync_drive
""".strip("\n")


def build_drive_service(credentials_file):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


class DriveSyncer:
    """Logic đồng bộ, tách riêng để có thể test với service giả lập."""

    def __init__(self, service, log=print, force=False):
        self.service = service
        self.log = log
        self.force = force
        self.stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "folders": 0}

    # -- Liệt kê --------------------------------------------------------
    def list_children(self, folder_id):
        token = None
        safe_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        while True:
            resp = self.service.files().list(
                q=f"'{safe_id}' in parents and trashed = false",
                fields=LIST_FIELDS,
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            yield from resp.get("files", [])
            token = resp.get("nextPageToken")
            if not token:
                break

    def iter_files(self, root_id):
        seen, stack = set(), [root_id]
        while stack:
            folder_id = stack.pop()
            if folder_id in seen:
                continue
            seen.add(folder_id)
            self.stats["folders"] += 1
            for item in self.list_children(folder_id):
                if item.get("mimeType") == FOLDER_MIME:
                    stack.append(item["id"])
                else:
                    yield item

    # -- Tải nội dung ----------------------------------------------------
    def fetch_text(self, item):
        mime = item.get("mimeType", "")
        name = item.get("name", "")
        files = self.service.files()
        if mime in EXPORTS:
            export_mime, ext = EXPORTS[mime]
            data = files.export_media(fileId=item["id"], mimeType=export_mime).execute()
            return extract_text(io.BytesIO(data), name + ext, export_mime)
        if mime.startswith("application/vnd.google-apps."):
            return ""  # Forms, Drawings, shortcut… không có nội dung văn bản.
        if not is_supported(name, mime):
            return ""
        if int(item.get("size") or 0) > MAX_DOWNLOAD_BYTES:
            self.log(f"  - Bỏ qua nội dung (file quá lớn): {name}")
            return ""
        data = files.get_media(fileId=item["id"], supportsAllDrives=True).execute()
        return extract_text(io.BytesIO(data), name, mime)

    # -- Đồng bộ ---------------------------------------------------------
    def sync_item(self, item):
        modified = parse_datetime(item["modifiedTime"]) if item.get("modifiedTime") else None
        doc = Document.objects.filter(drive_file_id=item["id"]).first()
        name = (item.get("name") or "(không tên)")[:255]
        url = (item.get("webViewLink") or "")[:500]
        mime = (item.get("mimeType") or "")[:150]

        if doc and not self.force and modified and doc.drive_modified_time == modified:
            if doc.name != name or doc.drive_url != url:
                doc.name, doc.drive_url = name, url
                doc.save(update_fields=["name", "drive_url", "updated_at"])
                self.stats["updated"] += 1
            else:
                self.stats["skipped"] += 1
            return

        text = self.fetch_text(item)
        created = doc is None
        if created:
            doc = Document(drive_file_id=item["id"], source=Document.Source.DRIVE)
        doc.name = name
        doc.drive_url = url
        doc.mime_type = mime
        doc.drive_modified_time = modified
        doc.extracted_text = text
        doc.save()  # cập nhật luôn search_vector
        self.stats["created" if created else "updated"] += 1
        self.log(f"  {'+' if created else '~'} {name} ({len(text):,} ký tự)")

    def sync(self, folder_id):
        for item in self.iter_files(folder_id):
            try:
                self.sync_item(item)
            except Exception as exc:  # noqa: BLE001 – một file lỗi không dừng cả lượt
                self.stats["errors"] += 1
                self.log(f"  ! Lỗi với file {item.get('name')}: {exc}")
        return self.stats


class Command(BaseCommand):
    help = "Đồng bộ tài liệu từ thư mục Google Drive (kể cả thư mục con) và trích xuất nội dung để tìm kiếm."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Tải lại mọi file kể cả khi không thay đổi trên Drive.")
        parser.add_argument("--folder", help="ID thư mục Drive (mặc định: GOOGLE_DRIVE_FOLDER_ID).")

    def handle(self, *args, force=False, folder=None, **options):
        credentials_file = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
        folder_id = folder or getattr(settings, "GOOGLE_DRIVE_FOLDER_ID", "")
        if not credentials_file or not folder_id:
            self.stdout.write(self.style.WARNING(INSTRUCTIONS))
            return
        try:
            import google.oauth2.service_account  # noqa: F401
            import googleapiclient.discovery  # noqa: F401
        except ImportError:
            self.stdout.write(self.style.WARNING(
                "Chưa cài thư viện Google API. Chạy:\n"
                "  pip install google-api-python-client google-auth\n"
                "rồi chạy lại: python manage.py sync_drive"
            ))
            return
        if not os.path.exists(credentials_file):
            self.stderr.write(self.style.ERROR(
                f"Không tìm thấy file khoá service account: {credentials_file}\n"
                "Kiểm tra lại biến môi trường GOOGLE_SERVICE_ACCOUNT_FILE."
            ))
            return

        self.stdout.write(f"Đang đồng bộ thư mục Drive {folder_id} …")
        try:
            service = build_drive_service(credentials_file)
            stats = DriveSyncer(service, log=self.stdout.write, force=force).sync(folder_id)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(
                f"Không kết nối được Google Drive: {exc}\n"
                "Kiểm tra file khoá, Drive API đã bật và thư mục đã chia sẻ cho email service account."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Xong: {stats['created']} mới, {stats['updated']} cập nhật, "
            f"{stats['skipped']} không đổi, {stats['errors']} lỗi "
            f"(đã duyệt {stats['folders']} thư mục)."
        ))

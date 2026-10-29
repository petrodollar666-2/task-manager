# Quản lý công việc Khoa

Django 5.1 + PostgreSQL 16.

## Chạy thử

```bash
brew services start postgresql@16      # nếu Postgres chưa chạy
cd ~/task-manager
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo   # tài khoản + dữ liệu mẫu (--reset để tạo lại)
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

Mở http://localhost:8000. Máy khác cùng mạng LAN dùng http://<IP-máy-này>:8000.

| Tài khoản | Mật khẩu | Vai trò |
|---|---|---|
| admin | admin | Sếp: xem tất cả, vào trang Quản trị |
| giaovien1 … giaovien4 | giống tên đăng nhập | Giảng viên: chỉ thấy việc của mình |

## Lệnh khác

- `.venv/bin/pytest -q`: chạy toàn bộ test.
- `.venv/bin/python manage.py sync_drive`: đồng bộ Google Drive (chạy không tham số để xem hướng dẫn cấu hình).
- `.venv/bin/python manage.py reindex_documents`: trích xuất lại nội dung và lập lại chỉ mục tìm kiếm.

Bước mẫu của đầu việc và tuyến ký mẫu của tờ trình sửa trong Quản trị (Bước mẫu / Tuyến ký mẫu).

Mật khẩu `admin`/`giaovien1` chỉ dùng để thử. Trước khi dùng thật cần đổi mật khẩu, đặt `DEBUG=0`, `SECRET_KEY` và `ALLOWED_HOSTS`.

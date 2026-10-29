#!/usr/bin/env bash
# Chạy web ở chế độ công khai qua Cloudflare Tunnel (link tạm *.trycloudflare.com).
# Dùng: ./run_public.sh      (Ctrl+C để dừng)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

# 1. Postgres
if ! pg_isready -q; then
  brew services start postgresql@16 >/dev/null
  sleep 3
fi

# 2. Cấu hình production (SECRET_KEY lưu cục bộ, không đưa lên đâu)
if [ ! -f .secret_key ]; then
  .venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))" > .secret_key
fi
export SECRET_KEY="$(cat .secret_key)"
export DEBUG=0
export ALLOWED_HOSTS=".trycloudflare.com,localhost,127.0.0.1"
export CSRF_TRUSTED_ORIGINS="https://*.trycloudflare.com"

.venv/bin/python manage.py migrate --noinput >/dev/null
.venv/bin/python manage.py collectstatic --noinput >/dev/null

# 3. Web server (gunicorn) chạy nền
.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 \
  --access-logfile - > gunicorn.log 2>&1 &
GUNICORN_PID=$!
trap 'kill $GUNICORN_PID 2>/dev/null || true' EXIT

# 4. Tunnel: in link công khai
echo "Đang mở tunnel... link sẽ hiện bên dưới (dạng https://xxxx.trycloudflare.com)"
caffeinate -i cloudflared tunnel --url http://127.0.0.1:8000

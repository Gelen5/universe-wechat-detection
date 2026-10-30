#!/usr/bin/env bash
set -euo pipefail

site=/etc/nginx/sites-available/universe-wechat-detection
snippet="${1:-/tmp/nginx-admin-auth.location.conf}"
secret=/etc/nginx/.universe-admin-basic-secret
passwd=/etc/nginx/.universe-admin.htpasswd
username="${ADMIN_BASIC_AUTH_USERNAME:-gelen5@163.com}"
backup="${site}.pre-admin-auth-$(date +%Y%m%d%H%M%S)"

test "$(id -u)" -eq 0
test -f "$site"
test -f "$snippet"
cp -p "$site" "$backup"
if [ ! -s "$secret" ]; then
    umask 077
    openssl rand -hex 24 > "$secret"
fi
printf '%s:%s\n' "$username" "$(openssl passwd -apr1 -stdin < "$secret")" > "$passwd"
chmod 600 "$secret"
chown root:www-data "$passwd"
chmod 640 "$passwd"

python3 - "$site" "$snippet" <<'PY'
from pathlib import Path
import sys

site, snippet = map(Path, sys.argv[1:])
content = site.read_text()
marker = "    location = /api/qihaoshou/generate {"
if "auth_basic_user_file /etc/nginx/.universe-admin.htpasswd;" not in content:
    if marker not in content:
        raise SystemExit("nginx insertion point missing")
    site.write_text(content.replace(marker, snippet.read_text() + marker, 1))
PY

if ! nginx -t; then
    cp -p "$backup" "$site"
    nginx -t
    exit 1
fi
systemctl reload nginx
echo "Admin Basic Auth enabled; previous configuration: $backup"

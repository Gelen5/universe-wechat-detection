#!/usr/bin/env bash
# Keep admin APIs role-protected by the application while avoiding a second
# browser Basic Auth prompt when opening the activity dashboard and details.
set -euo pipefail
site=/etc/nginx/sites-enabled/universe-wechat-detection
backup="/etc/nginx/sites-available/universe-wechat-detection.enabled-pre-activity-auth-$(date +%Y%m%d%H%M%S)"
cp -p "$site" "$backup"
python3 - "$site" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); data = path.read_text()
marker = '    location ^~ /api/admin/ {'
location = '''    # Activity dashboard uses the application administrator session.
    location ^~ /api/admin/activity {
        proxy_pass http://universe_app;
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

'''
if 'location ^~ /api/admin/activity {' not in data:
    if marker not in data: raise SystemExit('admin nginx location missing')
    path.write_text(data.replace(marker, location + marker, 1))
PY
if ! nginx -t; then cp -p "$backup" "$site"; nginx -t; exit 1; fi
systemctl reload nginx
echo "Activity dashboard uses administrator session; backup: $backup"

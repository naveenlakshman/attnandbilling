# PythonAnywhere Deployment Checklist

Use this checklist when deploying code to production on PythonAnywhere.

## 1) Open PythonAnywhere Bash Console

```bash
cd /home/<your-username>/<your-app-folder>
pwd
ls -la
```

## 2) Create Production DB Backup (Before Any Change)

```bash
cd /home/<your-username>/<your-app-folder>
cp instance/database.db instance/database_predeploy_$(date +%Y%m%d_%H%M%S).db
ls -lh instance/database_predeploy_*.db
```

## 3) Pull Latest Code

If using git:

```bash
cd /home/<your-username>/<your-app-folder>
git pull origin main
```

## 4) Activate Virtual Environment

```bash
cd /home/<your-username>/<your-app-folder>
source venv/bin/activate
python --version
```

## 5) Install/Update Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 6) Run Safe Schema Init (Idempotent)

```bash
cd /home/<your-username>/<your-app-folder>
source venv/bin/activate
python -c "from db import init_db; init_db(); print('init_db_ok=True')"
```

Expected output:

```text
init_db_ok=True
```

## 7) Quick Schema Verification

```bash
python << 'EOF'
import sqlite3
con = sqlite3.connect('instance/database.db')
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'lms_master%'")
print('master_tables=', [r[0] for r in cur.fetchall()])
cur.execute("PRAGMA table_info(lms_chapters)")
print('has_is_archived=', 'is_archived' in [r[1] for r in cur.fetchall()])
con.close()
EOF
```

## 8) Reload Web App

1. Go to PythonAnywhere Web tab.
2. Open your web app.
3. Click Reload.

## 9) Smoke Test URLs

- /login
- /lms_admin/dashboard
- /lms_admin/master/chapters
- /student/dashboard
- /student/program/<program_id>

## 10) Check Error Log

```bash
tail -n 80 /var/log/<your-username>.pythonanywhere.com.error.log
```

Look for ImportError, sqlite3.OperationalError, or traceback entries.

## Rollback (If Anything Breaks)

```bash
cd /home/<your-username>/<your-app-folder>
cp instance/database.db instance/database_failed_$(date +%Y%m%d_%H%M%S).db
cp instance/database_predeploy_<timestamp>.db instance/database.db
```

Then reload the web app again from PythonAnywhere Web tab.

## Notes

- Do not upload local instance/database.db over production unless intentionally restoring.
- init_db() is safe to re-run and should not drop existing data.
- Keep at least one pre-deployment backup per release.

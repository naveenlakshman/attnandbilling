"""Patch only name formatting in the existing scheduled-reminder image."""
from pathlib import Path

path = Path('/app/modules/billing/auto_reminders.py')
source = path.read_text(encoding='utf-8')
old = '(row["student_name"] or "Student").split()[0]'
marker = 'from datetime import date, datetime, timedelta\n'
if source.count(old) != 1 or source.count(marker) != 1:
    raise SystemExit('The scheduled reminder source differs from the reviewed name-formatting pattern.')
source = source.replace(old, 'student_full_name(row["student_name"])')
source = source.replace(marker, marker+'from services.student_messages import student_full_name\n', 1)
compile(source, str(path), 'exec')
path.write_text(source, encoding='utf-8')

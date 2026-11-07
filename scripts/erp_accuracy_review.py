"""Read a SQLite backup without writes; produce correction/reconciliation previews.

python scripts/erp_accuracy_review.py --snapshot instance/database_02.db \
    --legacy-institute 1 --output scratch/erp-accuracy-review/preview.json
Never connect this command to a live application database. No apply mode exists.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.erp_schema import init_sqlite_schema
from services import finance_ledger as ledger
from services.recovery_preview import preview


def review(path,institute_id):
    source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    source.execute('PRAGMA query_only=ON')
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    try:
        source.backup(c)
    finally:source.close()
    c.create_function('parse_date',1,lambda v:str(v or '')[:10])
    # Only the disposable memory copy is normalized for old single-institute
    # backups. The explicit legacy institute flag is not evidence of branch.
    for table in ['invoices','receipts','bad_debt_writeoffs','expenses','students','branches','users']:
        columns={r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
        if 'institute_id' not in columns:
            c.execute('ALTER TABLE '+table+' ADD COLUMN institute_id INTEGER')
            c.execute('UPDATE '+table+' SET institute_id=?',(institute_id,))
    if 'reference_no' not in {r['name'] for r in c.execute('PRAGMA table_info(bad_debt_writeoffs)')}:
        c.execute('ALTER TABLE bad_debt_writeoffs ADD COLUMN reference_no TEXT')
    init_sqlite_schema(c)
    result=preview(c,institute_id)
    result['source']=str(Path(path).resolve())
    result['source_modified']=False
    candidates=[]
    for s in c.execute('SELECT id,branch_id,joined_date FROM students WHERE institute_id=?',(institute_id,)).fetchall():
        logs=[dict(r) for r in c.execute("SELECT id,user_id,branch_id,created_at FROM activity_logs WHERE record_id=? AND lower(module_name)='students' AND lower(action_type)='create'",(s['id'],)).fetchall()]
        candidates.append(dict(entity='student_registration_candidate',student_id=s['id'],existing=s['branch_id'],proposed=None,
            evidence={'student_create_logs':logs,'joined_date':s['joined_date']},confidence='unresolved',
            conflicts=['Course admission/bundle/repeat-invoice identity and original admission creator require confirmation'],apply=False))
    result['registration_candidates']=candidates
    original=c.execute("SELECT COALESCE(SUM(ip.amount_due-ip.amount_paid),0) n FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id WHERE i.institute_id=? AND ip.status<>'paid' AND i.status NOT IN ('write_off','partially_written_off')",(institute_id,)).fetchone()['n']
    corrected=c.execute('SELECT COALESCE(SUM('+ledger.installment_balance_sql(c)+'),0) n FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id WHERE i.institute_id=?',(institute_id,)).fetchone()['n']
    expenses=c.execute('SELECT COALESCE(SUM(amount),0) n FROM expenses WHERE institute_id=?',(institute_id,)).fetchone()['n']
    cash_expenses=c.execute('SELECT COALESCE(SUM(e.amount),0) n FROM expenses e WHERE e.institute_id=? AND '+ledger.noncash_expense_sql(),(institute_id,)).fetchone()['n']
    result['reconciliation']={'dataset':'same read-only snapshot; lifetime current balances',
        'legacy_visible_installment_dues':str(original),'corrected_visible_installment_dues':str(corrected),
        'legacy_expenses_in_cash_position':str(expenses),'expenses_after_excluding_linked_noncash_writeoffs':str(cash_expenses),
        'invoice_rows':c.execute('SELECT COUNT(*) n FROM invoices WHERE institute_id=?',(institute_id,)).fetchone()['n'],
        'receipt_rows':c.execute('SELECT COUNT(*) n FROM receipts WHERE institute_id=?',(institute_id,)).fetchone()['n'],
        'admissions_manufactured':0,'historical_collection_branches_inferred':0}
    c.close();return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True);parser.add_argument('--legacy-institute',type=int,required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();result=review(args.snapshot,args.legacy_institute)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps(dict(output=str(out),reconciliation=result['reconciliation'],correction_proposals=len(result['proposals']),unresolved_registration_candidates=len(result['registration_candidates'])),indent=2))

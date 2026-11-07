"""Read-only production snapshot and isolated ERP accuracy release verification."""
import argparse
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TABLES=['institutes','branches','users','students','courses','batches','student_batches',
'invoices','invoice_items','installment_plans','receipts','bad_debt_writeoffs',
'expense_categories','expenses','activity_logs','institute_settings','institute_document_sequences',
'lms_batch_topic_progress','lms_programs','lms_course_program_map','lms_student_program_access',
'cashfree_orders','cashfree_payment_link_orders','invoice_payments']
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()


def required_schema(conn):
    """Manifest of required columns, storage engines and index definitions."""
    import re
    names=re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)',(Path(__file__).resolve().parents[1]/'migrations/20261107_erp_data_accuracy.sql').read_text())
    result={}
    for name in names:
        table=conn.execute('SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?',(name,)).fetchone()
        columns=conn.execute('''SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,COLLATION_NAME
            FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY ORDINAL_POSITION''',(name,)).fetchall()
        indexes=conn.execute('''SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE
            FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY INDEX_NAME,SEQ_IN_INDEX''',(name,)).fetchall()
        result[name]=dict(table=dict(table) if table else None,columns=[dict(r) for r in columns],indexes=[dict(r) for r in indexes])
    return result

def capture(output):
    from ops.cashfree_production_release import database_connection,cloud_json,PROJECT,INSTANCE
    instance=cloud_json('sql','instances','describe',INSTANCE,'--project='+PROJECT)
    result={'captured_at':datetime.now(timezone.utc).isoformat(),'instance':INSTANCE,'project':PROJECT,
            'engine':instance.get('databaseInstalledVersion'),'tables':{},'masking':{},'read_only':True}
    with database_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cur.execute('SELECT VERSION() version,UTC_TIMESTAMP(6) snapshot_utc,@@sql_mode sql_mode,@@time_zone time_zone,@@transaction_read_only read_only')
            result['database']=cur.fetchone()
            cur.execute('SHOW TABLES');available={next(iter(r.values())) for r in cur.fetchall()}
            for table in TABLES:
                if table not in available:continue
                cur.execute('SHOW CREATE TABLE `'+table+'`');ddl=cur.fetchone()['Create Table']
                cur.execute('SHOW COLUMNS FROM `'+table+'`');columns=cur.fetchall()
                order=[r['Field'] for r in columns if r['Key']=='PRI']
                cur.execute('SELECT * FROM `'+table+'`'+(' ORDER BY '+','.join('`'+k+'`' for k in order) if order else ''))
                rows=cur.fetchall()
                masked=[r['Field'] for r in columns if any(w in r['Field'].lower() for w in ['password_hash','secret','token','payment_session'])]
                for row in rows:
                    for key in masked:
                        if row.get(key) is not None:row[key]='LOCAL_SNAPSHOT_REDACTED'
                result['tables'][table]={'ddl':ddl,'columns':[r['Field'] for r in columns],'rows':rows,'row_count':len(rows),'sha256':digest(rows)}
                if masked:result['masking'][table]=masked
            conn.rollback()
    out=Path(output);out.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(out,'wt',encoding='utf-8') as f:json.dump(result,f,default=str)
    print(json.dumps({'snapshot':str(out),'engine':result['engine'],'read_only':result['database']['read_only'],
        'tables':{k:v['row_count'] for k,v in result['tables'].items()},'masked_auth_fields':result['masking']},default=str))
    return result

def load(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)

def restore(data,conn,database):
    if not database.startswith('erp_accuracy_') or not database.replace('_','').isalnum():
        raise ValueError('Only isolated erp_accuracy_* databases may be restored.')
    with conn.cursor() as cur:
        cur.execute('CREATE DATABASE `'+database+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        cur.execute('USE `'+database+'`')
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        for table,t in data['tables'].items():
            cur.execute(t['ddl'])
            if t['rows']:
                cols=t['columns'];sql='INSERT INTO `'+table+'` ('+','.join('`'+c+'`' for c in cols)+') VALUES ('+','.join(['%s']*len(cols))+')'
                cur.executemany(sql,[[r.get(k) for k in cols] for r in t['rows']])
        cur.execute('SET FOREIGN_KEY_CHECKS=1')
    conn.commit()

def reconciliation(conn,institute=1):
    from services import finance_ledger as ledger
    rows=conn.execute('''SELECT i.id,i.invoice_no,i.student_id,i.status,i.invoice_date,i.total_amount,i.discount_amount,
        COALESCE((SELECT SUM(r.amount_received) FROM receipts r WHERE r.invoice_id=i.id AND r.institute_id=i.institute_id),0) paid,
        COALESCE((SELECT SUM(w.amount_written_off) FROM bad_debt_writeoffs w WHERE w.invoice_id=i.id AND w.institute_id=i.institute_id),0) written_off,
        COALESCE((SELECT SUM(ip.amount_due) FROM installment_plans ip WHERE ip.invoice_id=i.id),0) scheduled
        FROM invoices i WHERE i.institute_id=? ORDER BY i.id''',(institute,)).fetchall()
    details=[];exceptions=[];all_invoices=[]
    for row in rows:
        r=dict(row);plans=conn.execute('SELECT * FROM installment_plans WHERE invoice_id=? ORDER BY installment_no,id',(r['id'],)).fetchall()
        old=sum(Decimal(str(p['amount_due']))-Decimal(str(p['amount_paid'])) for p in plans if p['status']!='paid' and r['status'] not in ['write_off','partially_written_off'])
        calculated=conn.execute('SELECT '+ledger.installment_balance_sql(conn)+' due FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id WHERE i.id=?',(r['id'],)).fetchall()
        new=sum(Decimal(str(p['due'])) for p in calculated)
        signed=Decimal(str(r['total_amount']))-Decimal(str(r['paid']))-Decimal(str(r['written_off']))
        raw=Decimal(str(r['total_amount'])) if r['status']!='cancelled' else Decimal(0)
        expected=max(Decimal(0),signed) if r['status']!='cancelled' else Decimal(0)
        diff=new-old
        # Preserve the superseded candidate calculation to explain its defect.
        remaining_covered=Decimal(str(r['total_amount']))-max(Decimal(0),signed)
        candidate=Decimal(0)
        for p in plans:
            due=Decimal(str(p['amount_due']))
            candidate+=max(Decimal(0),due-max(Decimal(0),min(due,remaining_covered)))
            remaining_covered-=due
        reason=[]
        if r['status'] in ['write_off','partially_written_off'] and new:reason.append('status exclusion hid remaining dues')
        cached=sum(Decimal(str(p['amount_due']))-Decimal(str(p['amount_paid'])) for p in plans)
        if cached!=new:reason.append('cached installment coverage differs from ledger')
        if r['status']=='cancelled' and old:reason.append('cancelled invoice included by old query')
        if diff and any(p['status']=='paid' and Decimal(str(p['amount_paid']))<Decimal(str(p['amount_due'])) for p in plans):reason.append('paid status hid underpaid installment')
        item={'invoice_id':r['id'],'invoice_no':r['invoice_no'],'student_id':r['student_id'],'status':r['status'],
            'net_invoice':str(r['total_amount']),'receipts':str(r['paid']),'writeoffs':str(r['written_off']),
            'scheduled':str(r['scheduled']),'ledger_outstanding':str(expected),'old_visible_due':str(old),'new_visible_due':str(new),
            'delta':str(diff),'superseded_candidate_due':str(candidate),'superseded_candidate_delta':str(candidate-old),
            'candidate_phantom_due':str(candidate-new),'reasons':reason,'installments':[dict(p) for p in plans]}
        all_invoices.append(item)
        if diff or candidate!=new:details.append(item)
        if new!=expected or Decimal(str(r['scheduled']))!=Decimal(str(r['total_amount'])) or signed<0:
            exceptions.append({**item,'schedule_vs_ledger_difference':str(new-expected),'overcoverage':str(max(Decimal(0),-signed))})
    control=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(total_amount),0) total,COALESCE(SUM(discount_amount),0) discounts FROM invoices WHERE institute_id=?',(institute,)).fetchone()
    cash=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(amount_received),0) total FROM receipts WHERE institute_id=?',(institute,)).fetchone()
    waivers=conn.execute('SELECT COUNT(*) n,COALESCE(SUM(amount_written_off),0) total FROM bad_debt_writeoffs WHERE institute_id=?',(institute,)).fetchone()
    return {'institute_id':institute,'invoices':dict(control),'receipts':dict(cash),'writeoffs':dict(waivers),
        'visible_due_delta':str(sum(Decimal(d['delta']) for d in details)),
        'old_visible_due':str(sum(Decimal(d['old_visible_due']) for d in all_invoices)),
        'new_visible_due':str(sum(Decimal(d['new_visible_due']) for d in all_invoices)),
        'ledger_outstanding':str(sum(Decimal(d['ledger_outstanding']) for d in all_invoices)),
        'changed_invoices':details,'balance_exceptions':exceptions,'all_invoices':all_invoices}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',required=True)
    a=p.parse_args();capture(a.capture)


"""Read-only recovery proposals. No inference from invoice/receipt creators."""
from services import finance_ledger as ledger


def preview(conn,institute_id,confirmed=None):
    confirmed=confirmed or {}
    proposals=[]
    branches=[dict(r) for r in conn.execute('SELECT id,branch_name FROM branches WHERE institute_id=?',(institute_id,)).fetchall()]
    head=[r['id'] for r in branches if 'head office' in r['branch_name'].lower()]
    hoskote=[r['id'] for r in branches if 'hoskote' in r['branch_name'].lower()]
    ho=head[0] if len(head)==1 else None
    hos=hoskote[0] if len(hoskote)==1 else None
    if ledger.available(conn):
        for a in conn.execute("SELECT * FROM course_admissions WHERE institute_id=? AND admission_date>='2026-04-01' AND admission_date<'2026-12-01'",(institute_id,)).fetchall():
            evidence=confirmed.get(a['id'])
            creator=None;proposed=None;conflicts=[]
            if evidence and evidence.get('evidence') and evidence.get('original_admission_creator_id'):
                creator=conn.execute('SELECT * FROM users WHERE id=? AND institute_id=?',(evidence['original_admission_creator_id'],institute_id)).fetchone()
            if creator:
                proposed=ho if str(creator['username']).casefold()=='chaithra' or str(creator['full_name']).casefold()=='chaithra' else hos
                if not proposed:conflicts.append('Destination branch could not be resolved uniquely')
                if a['original_creator_id'] and a['original_creator_id']!=creator['id']:conflicts.append('Stored creator conflicts with confirmed evidence')
            else:conflicts.append('Original admission creator requires confirmation; invoice and receipt creators are not evidence')
            proposals.append(dict(entity='admission',id=a['id'],student_id=a['student_id'],existing=a['origin_branch_id'],proposed=proposed,
                evidence=evidence,confidence='confirmed_evidence' if creator and proposed and not conflicts else 'unresolved',conflicts=conflicts,apply=False))
    # Exact reference match plus title and amount: preview only, never delete.
    try:
        rows=conn.execute('''SELECT e.id,e.reference_no,e.amount,w.id writeoff_id,w.invoice_id,w.amount_written_off
            FROM expenses e JOIN bad_debt_writeoffs w ON w.institute_id=e.institute_id AND w.reference_no=e.reference_no
            WHERE e.institute_id=? AND COALESCE(e.reference_no,'')<>'' AND e.title LIKE 'Bad Debt Write-off%' ''',(institute_id,)).fetchall()
        for r in rows:
            conflict=[] if ledger.paise(r['amount'])==ledger.paise(r['amount_written_off']) else ['Amount mismatch']
            proposals.append(dict(entity='noncash_writeoff_expense',id=r['id'],invoice_id=r['invoice_id'],existing={'cash_expense':str(r['amount'])},
                proposed={'cash_expense':0,'noncash_writeoff_retained':r['writeoff_id']},evidence={'reference':r['reference_no'],'writeoff_id':r['writeoff_id']},
                confidence='matched_reference' if not conflict else 'review',conflicts=conflict,apply=False))
        matched={p['id'] for p in proposals if p['entity']=='noncash_writeoff_expense'}
        for r in conn.execute("SELECT id,amount,reference_no,title FROM expenses WHERE institute_id=? AND title LIKE 'Bad Debt Write-off%'",(institute_id,)).fetchall():
            if r['id'] not in matched:
                proposals.append(dict(entity='possible_noncash_writeoff_expense',id=r['id'],existing={'cash_expense':str(r['amount'])},proposed=None,
                    evidence={'reference':r['reference_no'],'title':r['title']},confidence='unresolved',conflicts=['No durable write-off reference match; inspect source documents'],apply=False))
    except Exception:
        raise # Missing production schema must not be presented as an empty preview.
    return dict(read_only=True,period=['2026-04-01','2026-11-30'],proposals=proposals,
        limitations=['No admissions manufactured from invoice counts.','Unlinked legacy invoice items require bundle/repeat-invoice review.','Historical collection locations remain unresolved.'])

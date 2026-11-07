"""Date-explicit admission, posting, collection and training reports.

Child records are loaded independently. Largest-remainder allocation preserves
paise across multi-course invoices without multiplying receipts or adjustments.
"""
from datetime import date, timedelta
from collections import defaultdict
from services import admissions, finance_ledger as ledger
from services.course_billing_reports import split_amount

KINDS={'admissions','sales','collections','origin-collections','outstanding','training','writeoffs-posted','writeoffs-cohort'}


def build(conn,institute_id,kind,start,end,cutoff,branch=''):
    if kind not in KINDS:
        raise ValueError('Unknown report.')
    start=date.fromisoformat(start).isoformat();end=date.fromisoformat(end).isoformat();cutoff=date.fromisoformat(cutoff).isoformat()
    if start>end or end>cutoff:
        raise ValueError('Use start <= end <= calculation cutoff.')
    branches={str(r['id']):r['branch_name'] for r in conn.execute('SELECT id,branch_name FROM branches WHERE institute_id=?',(institute_id,)).fetchall()}
    if branch not in {'','unresolved',*branches}:
        raise ValueError('Choose a branch in this institute.')
    origins={r['id']:r for r in admissions.as_of(conn,institute_id,cutoff)}
    invoices={r['id']:dict(r) for r in conn.execute('''SELECT i.* FROM invoices i JOIN students s ON s.id=i.student_id AND s.institute_id=i.institute_id
        WHERE i.institute_id=? AND substr(i.invoice_date,1,10)<=?''',(institute_id,cutoff)).fetchall()}
    weights=defaultdict(lambda:defaultdict(int))
    for row in conn.execute('''SELECT ii.*,l.admission_id,l.effective_date FROM invoice_items ii
        JOIN invoices i ON i.id=ii.invoice_id LEFT JOIN invoice_item_admissions l ON l.item_id=ii.id AND l.institute_id=i.institute_id
        WHERE i.institute_id=?''',(institute_id,)).fetchall():
        a=row['admission_id'] if row['effective_date'] and row['effective_date']<=cutoff and row['admission_id'] in origins else None
        weights[row['invoice_id']][a]+=max(0,ledger.paise(row['line_total']))
    rows=[];undated=[]
    def append(data,bid):
        if (branch=='unresolved' and bid is not None) or (branch not in {'','unresolved'} and str(bid)!=branch):
            return
        rows.append(dict(data,branch_id=bid,branch=branches.get(str(bid),'Unresolved')))
    def portions(invoice_id,amount):
        return split_amount(amount,weights[invoice_id])
    def origin(a):
        return origins.get(a,{}).get('origin_branch_id')
    def in_period(day):
        return start<=str(day)[:10]<=end
    if kind=='admissions':
        for a in origins.values():
            if in_period(a['admission_date']):
                append(dict(admission_id=a['id'],student_id=a['student_id'],course_id=a['course_id'],admission_date=a['admission_date'],status=a['status'],admissions=1),a['origin_branch_id'])
    elif kind=='sales':
        for inv in invoices.values():
            if in_period(inv['invoice_date']):
                for a,net in portions(inv['id'],ledger.paise(inv['total_amount'])).items():
                    # Original sales remain visible alongside dated cancellations.
                    discount=portions(inv['id'],ledger.paise(inv['discount_amount'])).get(a,0)
                    append(dict(invoice_id=inv['id'],admission_id=a,date=inv['invoice_date'],kind='invoice',
                                gross_paise=net+discount,discount_paise=discount,net_sales_paise=net,
                                legacy_cancelled=inv['status']=='cancelled'),origin(a))
        for ev in conn.execute('SELECT * FROM finance_adjustments WHERE institute_id=? AND effective_date>=? AND effective_date<=?',(institute_id,start,end)).fetchall():
            if ev['invoice_id'] in invoices and ev['charge_delta']:
                for a,value in portions(ev['invoice_id'],int(ev['charge_delta'])).items():
                    append(dict(invoice_id=ev['invoice_id'],admission_id=a,date=ev['effective_date'],kind=ev['kind'],gross_paise=0,discount_paise=0,net_sales_paise=value),origin(a))
    elif kind in {'collections','origin-collections'}:
        receipts=[dict(r) for r in conn.execute('''SELECT r.*,d.payment_id,d.allocation_date,p.collection_branch_id,p.payment_channel
            FROM receipts r JOIN invoices i ON i.id=r.invoice_id AND i.institute_id=r.institute_id
            LEFT JOIN receipt_details d ON d.receipt_id=r.id AND d.institute_id=r.institute_id
            LEFT JOIN collection_payments p ON p.id=d.payment_id AND p.institute_id=r.institute_id
            WHERE r.institute_id=?''',(institute_id,)).fetchall()]
        allocated=defaultdict(int)
        for r in receipts:
            if r['allocation_date'] and r['allocation_date']>cutoff:continue
            if r['payment_id']:
                allocated[r['payment_id']]+=ledger.paise(r['amount_received'])
            if not in_period(r['receipt_date']):continue
            if kind=='collections' and r['payment_id']:continue # source payment counted once below
            values={None:ledger.paise(r['amount_received'])} if kind=='collections' else portions(r['invoice_id'],ledger.paise(r['amount_received']))
            for a,value in values.items():
                append(dict(receipt_id=r['id'],invoice_id=r['invoice_id'],admission_id=a,date=r['receipt_date'],channel=r['payment_channel'] or 'legacy_unresolved',collected_paise=value),r['collection_branch_id'] if kind=='collections' else origin(a))
        for p in conn.execute('SELECT * FROM collection_payments WHERE institute_id=?',(institute_id,)).fetchall():
            if not p['payment_date']:
                if branch=='' or (branch=='unresolved' and p['collection_branch_id'] is None) or branch==str(p['collection_branch_id']):
                    undated.append(dict(payment_id=p['id'],collection_branch_id=p['collection_branch_id'],amount_paise=int(p['amount_paise'])))
                continue
            if not in_period(p['payment_date']):continue
            amount=int(p['amount_paise']) if kind=='collections' else int(p['amount_paise'])-allocated[p['id']]
            if amount:
                append(dict(payment_id=p['id'],date=p['payment_date'],channel=p['payment_channel'],date_source=p['date_source'],kind='payment' if kind=='collections' else 'unallocated',collected_paise=amount),p['collection_branch_id'] if kind=='collections' else None)
        for ev in conn.execute('SELECT a.*,p.collection_branch_id,p.payment_channel FROM finance_adjustments a LEFT JOIN receipt_details d ON d.receipt_id=a.receipt_id AND d.institute_id=a.institute_id LEFT JOIN collection_payments p ON p.id=d.payment_id AND p.institute_id=a.institute_id WHERE a.institute_id=? AND a.cash_delta<>0 AND a.effective_date>=? AND a.effective_date<=?',(institute_id,start,end)).fetchall():
            ev=dict(ev)
            if ev['kind']=='refund':
                location=conn.execute('SELECT * FROM cash_event_details WHERE event_id=? AND institute_id=?',(ev['id'],institute_id)).fetchone()
                ev['collection_branch_id']=location['branch_id'] if location else None
                ev['payment_channel']=location['channel'] if location else 'unresolved'
            values={None:int(ev['cash_delta'])} if kind=='collections' else portions(ev['invoice_id'],int(ev['cash_delta']))
            for a,value in values.items():
                append(dict(adjustment_id=ev['id'],invoice_id=ev['invoice_id'],admission_id=a,date=ev['effective_date'],kind=ev['kind'],channel=ev['payment_channel'] or 'legacy_unresolved',collected_paise=value),ev['collection_branch_id'] if kind=='collections' else origin(a))
        for ev in conn.execute('''SELECT a.*,p.collection_branch_id,p.payment_channel FROM advance_returns a JOIN collection_payments p
            ON p.id=a.payment_id AND p.institute_id=a.institute_id WHERE a.institute_id=? AND a.effective_date>=? AND a.effective_date<=?''',(institute_id,start,end)).fetchall():
            location=conn.execute('SELECT * FROM cash_event_details WHERE event_id=? AND institute_id=?',(ev['id'],institute_id)).fetchone()
            append(dict(return_id=ev['id'],date=ev['effective_date'],kind='advance_refund',channel=location['channel'] if location else 'unresolved',collected_paise=-int(ev['amount_paise'])),location['branch_id'] if location and kind=='collections' else None)
    elif kind=='outstanding':
        for inv in invoices.values():
            t=ledger.totals(conn,institute_id,inv['id'],cutoff)
            if t['credit']:
                for a,value in portions(inv['id'],t['credit']).items():
                    append(dict(invoice_id=inv['id'],admission_id=a,age_bucket='credit',outstanding_paise=0,credit_paise=value),origin(a))
            remaining=t['outstanding'];covered=max(0,t['billed']-remaining)
            plans=ledger.installments_as_of(conn,institute_id,inv['id'],cutoff)
            dues=[]
            for p in plans:
                due=ledger.paise(p['amount_due']);used=min(due,covered);covered-=used
                value=min(remaining,due-used);remaining-=value
                if value:dues.append((str(p['due_date'])[:10],value))
            if remaining:dues.append((None,remaining))
            for due,value in dues:
                try:age=max(0,(date.fromisoformat(cutoff)-date.fromisoformat(due)).days) if due else None
                except ValueError:age=None
                for a,share in portions(inv['id'],value).items():
                    append(dict(invoice_id=inv['id'],admission_id=a,due_date=due,days_overdue=age,age_bucket='unknown' if age is None else 'current' if age==0 else '1-30' if age<=30 else '31-60' if age<=60 else '61+',outstanding_paise=share),origin(a))
    elif kind.startswith('writeoffs'):
        events=[dict(id=r['id'],invoice_id=r['invoice_id'],day=r['writeoff_date'],amount=ledger.paise(r['amount_written_off']),kind='writeoff') for r in conn.execute('SELECT * FROM bad_debt_writeoffs WHERE institute_id=?',(institute_id,)).fetchall()]
        events += [dict(id=r['id'],invoice_id=r['invoice_id'],day=r['effective_date'],amount=int(r['writeoff_delta']),kind=r['kind']) for r in conn.execute('SELECT * FROM finance_adjustments WHERE institute_id=? AND writeoff_delta<>0',(institute_id,)).fetchall()]
        for ev in events:
            if str(ev['day'])[:10]>cutoff:continue
            for a,value in portions(ev['invoice_id'],ev['amount']).items():
                cohort=origins.get(a,{}).get('admission_date')
                fallback=str(invoices.get(ev['invoice_id'],{}).get('invoice_date',''))[:10]
                if (kind=='writeoffs-posted' and in_period(ev['day'])) or (kind=='writeoffs-cohort' and ((cohort and in_period(cohort)) or (not cohort and in_period(fallback)))):
                    append(dict(writeoff_event_id=ev['id'],invoice_id=ev['invoice_id'],admission_id=a,posting_date=ev['day'],admission_date=cohort,
                                cohort_basis='admission date' if cohort else 'invoice date; admission cohort unresolved',kind=ev['kind'],written_off_paise=value),origin(a))
    elif kind=='training':
        for r in conn.execute('''SELECT t.*,m.module_name FROM training_assignments t JOIN admission_modules m ON m.id=t.module_id AND m.institute_id=t.institute_id
            WHERE t.institute_id=? AND t.start_date<=? AND (t.end_date IS NULL OR t.end_date>=?)''',(institute_id,end,start)).fetchall():
            days=(date.fromisoformat(min(end,r['end_date'] or end))-date.fromisoformat(max(start,r['start_date']))).days+1
            append(dict(assignment_id=r['id'],admission_id=r['admission_id'],module=r['module_name'],batch_id=r['batch_id'],trainer_id=r['trainer_id'],start_date=r['start_date'],end_date=r['end_date'],assigned_calendar_days=days),r['branch_id'])
        for r in conn.execute('''SELECT p.*,b.branch_id FROM lms_batch_topic_progress p JOIN batches b ON b.id=p.batch_id JOIN branches br ON br.id=b.branch_id
            JOIN users u ON u.id=p.taught_by_user_id AND u.institute_id=br.institute_id WHERE br.institute_id=? AND substr(p.taught_at,1,10)>=? AND substr(p.taught_at,1,10)<=?''',(institute_id,start,end)).fetchall():
            append(dict(teaching_id=r['id'],batch_id=r['batch_id'],program_id=r['program_id'],trainer_id=r['taught_by_user_id'],taught_at=str(r['taught_at']),topics_taught=1),r['branch_id'])
    metrics=defaultdict(int)
    for row in rows:
        for key,value in row.items():
            if key.endswith('_paise') or key in {'admissions','topics_taught','assigned_calendar_days'}:
                metrics[key]+=value
    return dict(kind=kind,start=start,end=end,cutoff=cutoff,branch_basis='collection branch' if kind=='collections' else 'training branch' if kind=='training' else 'original admission branch',
        tax_basis='Existing posted invoice amounts; no tax rules changed',cancellation_treatment='Original sales plus dated cancellation/reversal events; collections retain money movements; cancelled admissions remain labelled',
        cutoff_basis='Effective business dates. Later backdated postings can restate a period; posting timestamps and before/after history are retained.',
        incomplete_month=end<str((date.fromisoformat(end).replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)) or end[:7]==ledger.now()[:7],
        rows=rows,totals=dict(metrics),row_count=len(rows),unresolved_rows=sum(r['branch_id'] is None for r in rows),
        undated_payments=undated,undated_payment_paise=sum(r['amount_paise'] for r in undated),
        unknown_date_basis='Undated imports are excluded from date-filtered totals and listed separately; current invoice balances include their receipts.')

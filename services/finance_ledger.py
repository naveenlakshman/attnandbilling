"""One balance definition for billing, collections, adjustments and reports.

Amounts on invoices and receipts are posted values. Corrections are separate,
dated events; never subtract invoice discounts a second time.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import json
import uuid

IST = timezone(timedelta(hours=5, minutes=30))


def now():
    return datetime.now(IST).isoformat(timespec='microseconds')


def paise(value):
    try:
        amount = Decimal(str(value or 0))
        if not amount.is_finite() or abs(amount-amount.quantize(Decimal('.01'))) > Decimal('.000001'):
            raise ValueError('Use a finite amount with at most two decimal places.')
        return int(amount.quantize(Decimal('.01')) * 100)
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid amount.') from None


def available(conn):
    # Compatibility for old read-only exports/tests; new write workflows require
    # the explicit migration. Never do request-time DDL on MySQL.
    if hasattr(conn, '_conn'):
        return bool(conn.execute("SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='finance_adjustments'").fetchone())
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finance_adjustments'").fetchone())


def lock_invoice(conn, institute_id, invoice_id):
    suffix = ' FOR UPDATE' if hasattr(conn, '_conn') else ''
    row = conn.execute('''SELECT i.* FROM invoices i JOIN students s
        ON s.id=i.student_id AND s.institute_id=i.institute_id
        WHERE i.id=? AND i.institute_id=?''' + suffix, (invoice_id, institute_id)).fetchone()
    if not row:
        raise ValueError('Invoice not found in this institute.')
    return dict(row)


def begin(conn):
    conn.execute('START TRANSACTION' if hasattr(conn, '_conn') else 'BEGIN IMMEDIATE')


def audit(conn, institute_id, actor_id, entity, entity_id, before, after, reason, effective_date):
    if not str(reason or '').strip():
        raise ValueError('A correction reason is required.')
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    previous=conn.execute('''SELECT event_order FROM accuracy_audit WHERE institute_id=? AND entity_type=? AND entity_id=?
        ORDER BY event_order DESC LIMIT 1'''+suffix,(institute_id,entity,str(entity_id))).fetchone()
    order=int(previous['event_order'])+1 if previous else 1
    conn.execute('''INSERT INTO accuracy_audit
        (id,institute_id,actor_id,entity_type,entity_id,before_json,after_json,reason,effective_date,recorded_at,event_order)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (uuid.uuid4().hex,institute_id,actor_id,entity,str(entity_id),json.dumps(before,default=str),
         json.dumps(after,default=str),reason,effective_date,now(),order))


def snapshot_invoice(conn, institute_id, invoice_id):
    row = conn.execute('SELECT snapshot_json FROM invoice_postings WHERE institute_id=? AND invoice_id=?',
                       (institute_id,invoice_id)).fetchone()
    if row:
        return json.loads(row['snapshot_json'])
    invoice = lock_invoice(conn,institute_id,invoice_id)
    items = [dict(r) for r in conn.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id',(invoice_id,)).fetchall()]
    snapshot = dict(invoice=invoice,items=items)
    conn.execute('INSERT INTO invoice_postings (invoice_id,institute_id,snapshot_json,captured_at) VALUES (?,?,?,?)',
                 (invoice_id,institute_id,json.dumps(snapshot,default=str),now()))
    return snapshot


# Signed effects: charge reduction, reversal of a write-off, cash returned, and
# correction of an erroneous receipt. Reversals carry the exact opposite effects.
def effects(row):
    return tuple(int(row[k]) for k in ('charge_delta','writeoff_delta','cash_delta'))


def totals(conn, institute_id, invoice_id, cutoff=None):
    invoice = conn.execute('SELECT * FROM invoices WHERE id=? AND institute_id=?',(invoice_id,institute_id)).fetchone()
    if not invoice:
        raise ValueError('Invoice not found in this institute.')
    invoice = dict(invoice)
    end = cutoff or '9999-12-31'
    if available(conn):
        receipt_rows = conn.execute('''SELECT r.* FROM receipts r LEFT JOIN receipt_details d ON d.receipt_id=r.id AND d.institute_id=r.institute_id
            WHERE r.invoice_id=? AND r.institute_id=? AND (? IS NULL OR substr(r.receipt_date,1,10)<=?)
            AND (? IS NULL OR d.allocation_date IS NULL OR d.allocation_date<=?)''',(invoice_id,institute_id,cutoff,end,cutoff,end)).fetchall()
    else:
        receipt_rows = conn.execute('''SELECT * FROM receipts WHERE invoice_id=? AND institute_id=?
            AND (? IS NULL OR substr(receipt_date,1,10)<=?)''',(invoice_id,institute_id,cutoff,end)).fetchall()
    writeoffs = conn.execute('''SELECT * FROM bad_debt_writeoffs WHERE invoice_id=? AND institute_id=?
        AND substr(writeoff_date,1,10)<=?''',(invoice_id,institute_id,end)).fetchall()
    billed = paise(invoice['total_amount']) if str(invoice['invoice_date'])[:10] <= end else 0
    received = sum(paise(r['amount_received']) for r in receipt_rows)
    written_off = sum(paise(r['amount_written_off']) for r in writeoffs)
    adjustments = []
    if available(conn):
        adjustments = conn.execute('''SELECT * FROM finance_adjustments WHERE institute_id=? AND invoice_id=?
            AND effective_date<=? ORDER BY recorded_at,id''',(institute_id,invoice_id,end)).fetchall()
    charge_delta = sum(effects(r)[0] for r in adjustments)
    writeoff_delta = sum(effects(r)[1] for r in adjustments)
    cash_delta = sum(effects(r)[2] for r in adjustments)
    # Legacy cancellations have no dated cancellation event: clearly excluded
    # from present dues; a prior cancellation date cannot be reconstructed.
    dated_cancel = any(r['kind']=='cancellation' for r in adjustments)
    has_cancel = False
    if invoice['status']=='cancelled' and not dated_cancel:
        has_cancel = available(conn) and bool(conn.execute("SELECT 1 FROM finance_adjustments WHERE institute_id=? AND invoice_id=? AND kind='cancellation'",(institute_id,invoice_id)).fetchone())
        if not has_cancel:
            billed = 0
    charge = billed + charge_delta
    cash = received + cash_delta
    waived = written_off + writeoff_delta
    signed = charge-cash-waived
    return dict(invoice=invoice,billed=billed,charge=charge,receipts=received,cash=cash,
                written_off=waived,adjustment=charge_delta,outstanding=max(0,signed),credit=max(0,-signed),
                adjustments=[dict(r) for r in adjustments])


def balance_sql(alias='i', *, adjustments=True):
    """Current signed balance, tenant-matched at every relationship."""
    legacy_cancel=f"{alias}.status='cancelled'"
    if adjustments:
        legacy_cancel+=f" AND NOT EXISTS (SELECT 1 FROM finance_adjustments ca WHERE ca.invoice_id={alias}.id AND ca.institute_id={alias}.institute_id AND ca.kind='cancellation')"
    base = f'''((CASE WHEN {legacy_cancel} THEN 0 ELSE {alias}.total_amount END)
        - COALESCE((SELECT SUM(r.amount_received) FROM receipts r WHERE r.invoice_id={alias}.id AND r.institute_id={alias}.institute_id),0)
        - COALESCE((SELECT SUM(w.amount_written_off) FROM bad_debt_writeoffs w WHERE w.invoice_id={alias}.id AND w.institute_id={alias}.institute_id),0)'''
    if adjustments:
        base += f'''+ COALESCE((SELECT SUM(a.charge_delta-a.writeoff_delta-a.cash_delta)/100.0
            FROM finance_adjustments a WHERE a.invoice_id={alias}.id AND a.institute_id={alias}.institute_id),0)'''
    return base+')'


def collectible_sql(conn, alias='i'):
    return balance_sql(alias,adjustments=available(conn))+' > 0.005'


def outstanding_sql(conn,alias='i'):
    signed=balance_sql(alias,adjustments=available(conn))
    return f'(CASE WHEN ({signed})>0 THEN ({signed}) ELSE 0 END)'


def credit_sql(conn,alias='i'):
    signed=balance_sql(alias,adjustments=available(conn))
    return f'(CASE WHEN ({signed})<0 THEN -({signed}) ELSE 0 END)'


def installment_balance_sql(conn, invoice='i', installment='ip'):
    """Derive installment dues from the ledger, including stale legacy caches."""
    balance=balance_sql(invoice,adjustments=available(conn))
    covered=f'({invoice}.total_amount-({balance}))'
    prior=f'''COALESCE((SELECT SUM(pr.amount_due) FROM installment_plans pr
        WHERE pr.invoice_id={invoice}.id AND (pr.installment_no<{installment}.installment_no
        OR (pr.installment_no={installment}.installment_no AND pr.id<{installment}.id))),0)'''
    # Intersect each scheduled interval with [covered, invoice total]. Legacy
    # schedules sometimes exceed the invoice: that excess is never a charge.
    end=f'(CASE WHEN {prior}+{installment}.amount_due>{invoice}.total_amount THEN {invoice}.total_amount ELSE {prior}+{installment}.amount_due END)'
    start=f'(CASE WHEN {covered}>{prior} THEN {covered} ELSE {prior} END)'
    return f'(CASE WHEN {end}<={start} THEN 0 ELSE {end}-{start} END)'


def sync_installments(conn, institute_id, invoice_id):
    t = totals(conn,institute_id,invoice_id)
    rows = conn.execute('SELECT * FROM installment_plans WHERE invoice_id=? ORDER BY installment_no,id',(invoice_id,)).fetchall()
    # Coverage includes fee reductions and write-offs but is never a cash receipt.
    remaining = max(0,t['billed']-t['outstanding'])
    for row in rows:
        due = paise(row['amount_due']); covered=min(due,remaining);remaining-=covered
        status='paid' if covered>=due else 'partially_paid' if covered else 'pending'
        conn.execute('UPDATE installment_plans SET amount_paid=?,status=?,updated_at=? WHERE id=?',
                     (covered/100,status,now(),row['id']))
    status=t['invoice']['status']
    if status != 'cancelled':
        status=('write_off' if t['written_off'] else 'paid') if not t['outstanding'] else (
            'partially_written_off' if t['written_off'] else 'partially_paid' if t['cash'] else 'unpaid')
        conn.execute('UPDATE invoices SET status=?,updated_at=? WHERE id=? AND institute_id=?',
                     (status,now(),invoice_id,institute_id))
    return t


def adjust(conn,institute_id,actor_id,invoice_id,kind,amount,day,reason,*,receipt_id=None,writeoff_id=None,reverse_of=None,request_key=None):
    from datetime import date
    day=date.fromisoformat(day).isoformat()
    if not str(reason or '').strip():
        raise ValueError('A correction reason is required.')
    if day>datetime.now(IST).date().isoformat():
        raise ValueError('Future financial postings are not permitted.')
    if not request_key:
        raise ValueError('A unique request key is required.')
    invoice=lock_invoice(conn,institute_id,invoice_id)
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    previous=conn.execute('SELECT * FROM finance_adjustments WHERE institute_id=? AND request_key=?'+suffix,(institute_id,request_key)).fetchone()
    if previous:
        if (int(previous['invoice_id'])!=int(invoice_id) or previous['kind']!=kind or previous['effective_date']!=day
                or int(previous['amount_paise'])!=paise(amount) or previous['reason']!=reason
                or previous['receipt_id']!=receipt_id or previous['writeoff_id']!=writeoff_id or previous['reverse_of']!=reverse_of):
            raise ValueError('Request key was already used for different details.')
        return previous['id']
    if day<str(invoice['invoice_date'])[:10]:
        raise ValueError('Adjustment cannot predate its invoice.')
    snapshot_invoice(conn,institute_id,invoice_id)
    t=totals(conn,institute_id,invoice_id)
    amount=paise(amount)
    if amount<=0:
        raise ValueError('Amount must be positive.')
    charge=waiver=cash=0
    if kind=='fee_reduction':
        if amount>t['charge']-t['written_off']:
            raise ValueError('Reduction exceeds the charge remaining after write-offs.')
        charge=-amount
    elif kind=='cancellation':
        if t['invoice']['status']=='cancelled' or t['written_off']:
            raise ValueError('Reverse write-offs before cancelling an invoice.')
        if amount!=t['charge']:
            raise ValueError('Cancellation must equal the remaining invoice charge.')
        charge=-amount
    elif kind=='writeoff_reversal':
        w=conn.execute('SELECT * FROM bad_debt_writeoffs WHERE id=? AND institute_id=? AND invoice_id=?',(writeoff_id,institute_id,invoice_id)).fetchone()
        if not w or amount!=paise(w['amount_written_off']):
            raise ValueError('Select the complete write-off to reverse.')
        if day<str(w['writeoff_date'])[:10]:
            raise ValueError('Reversal cannot predate its write-off.')
        if conn.execute('SELECT 1 FROM finance_adjustments WHERE institute_id=? AND writeoff_id=?',(institute_id,writeoff_id)).fetchone():
            raise ValueError('This write-off already has a reversal.')
        waiver=-amount
    elif kind in {'refund','receipt_reversal'}:
        receipt=conn.execute('SELECT * FROM receipts WHERE id=? AND institute_id=? AND invoice_id=?',(receipt_id,institute_id,invoice_id)).fetchone()
        if not receipt:
            raise ValueError('Select a receipt belonging to this invoice.')
        if day<str(receipt['receipt_date'])[:10]:
            raise ValueError('Refund/reversal cannot predate the receipt.')
        returned=conn.execute("SELECT COALESCE(SUM(-cash_delta),0) n FROM finance_adjustments WHERE institute_id=? AND receipt_id=?",(institute_id,receipt_id)).fetchone()['n']
        if amount>paise(receipt['amount_received'])-int(returned):
            raise ValueError('Amount exceeds the unreversed receipt value.')
        if kind=='refund' and amount>min(t['credit'],totals(conn,institute_id,invoice_id,day)['credit']):
            raise ValueError('Refund requires a credit from cancellation or fee reduction; use receipt reversal to correct an erroneous receipt.')
        cash=-amount
    elif kind=='adjustment_reversal':
        original=conn.execute('SELECT * FROM finance_adjustments WHERE id=? AND institute_id=? AND invoice_id=?',(reverse_of,institute_id,invoice_id)).fetchone()
        if not original or original['kind'] in {'adjustment_reversal','refund','receipt_reversal','writeoff_reversal'} or amount!=int(original['amount_paise']):
            raise ValueError('Select a fee adjustment or cancellation to reverse in full.')
        if day<original['effective_date']:
            raise ValueError('Reversal cannot predate its original event.')
        charge,waiver,cash=(-x for x in effects(original))
        if t['cash']+t['written_off']>t['charge']+charge:
            raise ValueError('Reversal would leave invalid coverage.')
    else:
        raise ValueError('Unknown adjustment type.')
    ident=uuid.uuid4().hex
    conn.execute('''INSERT INTO finance_adjustments
        (id,institute_id,invoice_id,kind,amount_paise,charge_delta,writeoff_delta,cash_delta,
        effective_date,recorded_at,created_by,reason,receipt_id,writeoff_id,reverse_of,request_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident,institute_id,invoice_id,kind,amount,charge,waiver,cash,day,now(),actor_id,reason,receipt_id,writeoff_id,reverse_of,request_key))
    if kind=='cancellation':
        conn.execute("UPDATE invoices SET status='cancelled' WHERE id=? AND institute_id=?",(invoice_id,institute_id))
    elif kind=='adjustment_reversal' and original['kind']=='cancellation':
        conn.execute("UPDATE invoices SET status='unpaid' WHERE id=? AND institute_id=?",(invoice_id,institute_id))
    after=sync_installments(conn,institute_id,invoice_id)
    audit(conn,institute_id,actor_id,'financial_adjustment',ident,t,after,reason,day)
    return ident


def noncash_expense_sql(alias='e'):
    # Include old linked write-off expenses in the exclusion without changing
    # their stored values. The recovery preview identifies these separately.
    return f'''NOT EXISTS (SELECT 1 FROM bad_debt_writeoffs w WHERE
        w.institute_id={alias}.institute_id AND w.reference_no={alias}.reference_no
        AND COALESCE(w.reference_no,'')<>'' AND w.amount_written_off={alias}.amount
        AND {alias}.title LIKE 'Bad Debt Write-off%')'''


def correct_installment(conn,institute_id,actor_id,ident,due_date,amount_due,remarks,reason,effective_date):
    from datetime import date
    due_date=date.fromisoformat(due_date).isoformat()
    effective_date=date.fromisoformat(effective_date).isoformat()
    if effective_date>now()[:10]:raise ValueError('Correction effective date cannot be in the future.')
    row=conn.execute('''SELECT ip.* FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id
        WHERE ip.id=? AND i.institute_id=?''',(ident,institute_id)).fetchone()
    if not row:raise ValueError('Installment not found in this institute.')
    lock_invoice(conn,institute_id,row['invoice_id'])
    if paise(amount_due)!=paise(row['amount_due']):
        raise ValueError('A financial adjustment is required to change fees; this correction preserves the scheduled amount.')
    after={**dict(row),'due_date':due_date,'remarks':remarks}
    audit(conn,institute_id,actor_id,'installment',ident,dict(row),after,reason,effective_date)
    conn.execute('UPDATE installment_plans SET due_date=?,remarks=?,updated_at=? WHERE id=?',(due_date,remarks,now(),ident))
    return row['invoice_id']


def installments_as_of(conn,institute_id,invoice_id,cutoff):
    result=[]
    for row in conn.execute('SELECT * FROM installment_plans WHERE invoice_id=? ORDER BY installment_no,id',(invoice_id,)).fetchall():
        value=dict(row)
        events=conn.execute("SELECT * FROM accuracy_audit WHERE institute_id=? AND entity_type='installment' AND entity_id=? ORDER BY event_order",(institute_id,str(row['id']))).fetchall()
        if events:
            value=json.loads(events[0]['before_json'])
            for ev in events:
                if ev['effective_date']<=cutoff:
                    before=json.loads(ev['before_json']);after=json.loads(ev['after_json'])
                    value.update({k:v for k,v in after.items() if before.get(k)!=v})
        result.append(value)
    return result


def cash_movements(conn,institute_id,start,end):
    """Cash/bank movements, including advances and outflows, counted once."""
    result=[]
    for r in conn.execute('''SELECT id,payment_date day,collection_branch_id branch_id,amount_paise amount
        FROM collection_payments WHERE institute_id=? AND payment_date>=? AND payment_date<=?''',(institute_id,start,end)).fetchall():
        result.append(dict(r))
    for r in conn.execute('''SELECT r.id,r.receipt_date day,r.amount_received FROM receipts r
        JOIN invoices i ON i.id=r.invoice_id AND i.institute_id=r.institute_id
        JOIN students s ON s.id=i.student_id AND s.institute_id=i.institute_id
        WHERE r.institute_id=? AND substr(r.receipt_date,1,10)>=? AND substr(r.receipt_date,1,10)<=?
        AND NOT EXISTS(SELECT 1 FROM receipt_details d WHERE d.receipt_id=r.id AND d.institute_id=r.institute_id)''',(institute_id,start,end)).fetchall():
        result.append(dict(id=r['id'],day=str(r['day'])[:10],branch_id=None,amount=paise(r['amount_received'])))
    for r in conn.execute('''SELECT a.id,a.effective_date day,a.cash_delta amount,a.kind,
        p.collection_branch_id original_branch,c.branch_id payout_branch
        FROM finance_adjustments a LEFT JOIN receipt_details d ON d.receipt_id=a.receipt_id AND d.institute_id=a.institute_id
        LEFT JOIN collection_payments p ON p.id=d.payment_id AND p.institute_id=a.institute_id
        LEFT JOIN cash_event_details c ON c.event_id=a.id AND c.institute_id=a.institute_id
        WHERE a.institute_id=? AND a.cash_delta<>0 AND a.effective_date>=? AND a.effective_date<=?''',(institute_id,start,end)).fetchall():
        result.append(dict(id=r['id'],day=r['day'],amount=int(r['amount']),branch_id=r['payout_branch'] if r['kind']=='refund' else r['original_branch']))
    for r in conn.execute('''SELECT a.id,a.effective_date day,-a.amount_paise amount,c.branch_id
        FROM advance_returns a LEFT JOIN cash_event_details c ON c.event_id=a.id AND c.institute_id=a.institute_id
        WHERE a.institute_id=? AND a.effective_date>=? AND a.effective_date<=?''',(institute_id,start,end)).fetchall():
        result.append(dict(r))
    return result

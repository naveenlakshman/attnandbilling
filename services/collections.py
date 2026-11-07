"""Physical collection location, online channel, references and advances.

Existing receipts remain invoice allocations. A source payment can be allocated
to several invoices; its unallocated remainder is an explicit student advance.
All functions use the caller's transaction and lock invoice/payment rows.
"""
from datetime import date
import hashlib
import json
import uuid

from services import finance_ledger as ledger
from services.admissions import owned
from services.document_numbers import allocate_document_number


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()


def import_receipt(conn,institute_id,actor_id,row):
    """Import one historical allocation without guessing missing provenance.

    Caller owns the transaction/savepoint. Empty payment_date is the explicit
    unknown-date sentinel; it never becomes today's date or invoice date.
    """
    inv=ledger.lock_invoice(conn,institute_id,int(row.get('invoice_id') or 0))
    number=str(row.get('receipt_number') or row.get('receipt_no') or '').strip()
    if not number or len(number)>100:
        raise ValueError('A receipt number of at most 100 characters is required.')
    value=ledger.paise(row.get('amount_received'))
    if value<=0:raise ValueError('Receipt amount must be positive; use a reversal for corrections.')
    dates=[]
    for field in ['payment_date','receipt_date']:
        raw=str(row.get(field) or '').strip()
        if raw:
            try:
                from datetime import datetime
                parsed=next((datetime.strptime(raw,fmt).date().isoformat() for fmt in ['%Y-%m-%d','%d-%m-%Y','%d/%m/%Y','%Y/%m/%d'] if _matches_date(raw,fmt)),None)
            except (ValueError,TypeError):parsed=None
            if not parsed:raise ValueError('Invalid payment date.')
            dates.append(parsed)
    if len(set(dates))>1:raise ValueError('payment_date and receipt_date disagree.')
    day=dates[0] if dates else ''
    if day and (day>ledger.now()[:10] or day<str(inv['invoice_date'])[:10]):
        raise ValueError('Payment date must follow the invoice and cannot be in the future.')
    raw_branch=str(row.get('collection_branch_id') or '').strip()
    branch=None
    if raw_branch:
        if not raw_branch.isdigit():raise ValueError('collection_branch_id must be an institute branch ID.')
        branch=int(raw_branch);owned(conn,'branches',branch,institute_id)
    channel=str(row.get('payment_channel') or 'unresolved').strip().lower()
    method=str(row.get('payment_mode') or 'unresolved').strip().lower().replace(' ','_')
    if channel not in {'branch','bank','online','unresolved'}:raise ValueError('Invalid payment channel.')
    if method not in {'cash','upi','bank_transfer','card','unresolved'}:raise ValueError('Invalid payment method.')
    reference=str(row.get('payment_reference') or '').strip().upper() or None
    if reference and len(reference)>150:raise ValueError('Payment reference exceeds 150 characters.')
    fp=fingerprint([inv['id'],number,value,day,branch,channel,method,reference,str(row.get('notes') or '').strip()])
    key='csv-receipt-'+hashlib.sha256(number.encode()).hexdigest()
    old=conn.execute('SELECT * FROM collection_payments WHERE institute_id=? AND request_key=?',(institute_id,key)).fetchone()
    if old:
        if old['fingerprint']!=fp:raise ValueError('Receipt number was already imported with different details.')
        return conn.execute('SELECT receipt_id FROM receipt_details WHERE payment_id=? AND institute_id=?',(old['id'],institute_id)).fetchone()['receipt_id']
    if conn.execute('SELECT 1 FROM receipts WHERE receipt_no=? AND institute_id=?',(number,institute_id)).fetchone():
        raise ValueError('Receipt number already exists in this institute.')
    if reference and conn.execute('SELECT 1 FROM collection_payments WHERE institute_id=? AND payment_channel=? AND payment_reference=?',(institute_id,channel,reference)).fetchone():
        raise ValueError('Payment reference already exists in this channel/institute.')
    if inv['status']=='cancelled' or value>ledger.totals(conn,institute_id,inv['id'])['outstanding']:
        raise ValueError('Receipt exceeds the collectible invoice balance.')
    ledger.snapshot_invoice(conn,institute_id,inv['id'])
    stamp=ledger.now();pid=uuid.uuid4().hex
    cur=conn.execute('''INSERT INTO receipts (institute_id,receipt_no,invoice_id,receipt_date,amount_received,payment_mode,notes,created_by,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',(institute_id,number,inv['id'],day,value/100,method,str(row.get('notes') or '').strip() or None,actor_id,stamp))
    rid=cur.lastrowid
    conn.execute('''INSERT INTO collection_payments (id,institute_id,student_id,amount_paise,collection_branch_id,payment_channel,payment_method,
        payment_reference,payment_date,payment_timestamp,date_source,posted_at,created_by,request_key,fingerprint)
        VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?)''',(pid,institute_id,inv['student_id'],value,branch,channel,method,reference,day,
        'import_entered' if day else 'import_unknown',stamp,actor_id,key,fp))
    receipt=dict(conn.execute('SELECT * FROM receipts WHERE id=? AND institute_id=?',(rid,institute_id)).fetchone())
    conn.execute('INSERT INTO receipt_details (receipt_id,institute_id,payment_id,original_json,recorded_at,allocation_date) VALUES (?,?,?,?,?,?)',
        (rid,institute_id,pid,json.dumps(receipt,default=str),stamp,day))
    ledger.sync_installments(conn,institute_id,inv['id'])
    ledger.audit(conn,institute_id,actor_id,'receipt_import',rid,None,
        dict(invoice_id=inv['id'],collection_branch_id=branch,payment_channel=channel,payment_date=day or None,payment_reference=reference,
             imported_by=actor_id,original_creator_id=None,unknown_fields=[k for k,v in [('collection_branch_id',branch),('payment_channel',None if channel=='unresolved' else channel),('payment_date',day),('payment_reference',reference)] if not v]),
        'Historical receipt import; missing metadata remains unknown',day or stamp[:10])
    return rid


def _matches_date(raw,fmt):
    from datetime import datetime
    try:datetime.strptime(raw,fmt);return True
    except ValueError:return False


def payment(conn,institute_id,actor_id,student_id,amount,day,branch_id,channel,method,reference,request_key,*,invoice_id=None,timestamp=None,date_source='staff_entered'):
    owned(conn,'students',student_id,institute_id)
    if channel not in {'branch','online','bank'} or method not in {'cash','upi','bank_transfer','card'}:
        raise ValueError('Choose a valid payment channel and method.')
    if channel=='branch' and not branch_id:
        raise ValueError('A branch collection requires its collection branch.')
    if branch_id:
        owned(conn,'branches',branch_id,institute_id)
    amount=ledger.paise(amount);day=date.fromisoformat(day).isoformat()
    if amount<=0 or day>ledger.now()[:10]:
        raise ValueError('Use a positive amount and a non-future payment date.')
    reference=(reference or '').strip().upper() or None
    if method!='cash' and not reference:
        raise ValueError('A structured payment reference is required for noncash payments.')
    if not request_key or len(request_key)>100 or (reference and len(reference)>150):
        raise ValueError('Use a valid request key and reference.')
    fp=fingerprint([student_id,amount,day,branch_id,channel,method,reference,invoice_id])
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    if invoice_id:
        inv=ledger.lock_invoice(conn,institute_id,invoice_id)
    else:
        conn.execute('SELECT id FROM students WHERE id=? AND institute_id=?'+suffix,(student_id,institute_id)).fetchone()
    old=conn.execute('SELECT * FROM collection_payments WHERE institute_id=? AND request_key=?'+suffix,(institute_id,request_key)).fetchone()
    if old:
        if old['fingerprint']!=fp:
            raise ValueError('Request key was already used for different payment details.')
        return old['id']
    if invoice_id:
        if int(inv['student_id'])!=int(student_id):
            raise ValueError('Payment student does not match invoice.')
        if inv['status']=='cancelled' or amount>ledger.totals(conn,institute_id,invoice_id)['outstanding']:
            raise ValueError('Payment exceeds the collectible invoice balance.')
    if reference and conn.execute('SELECT 1 FROM collection_payments WHERE institute_id=? AND payment_channel=? AND payment_reference=?',(institute_id,channel,reference)).fetchone():
        raise ValueError('This payment reference has already been recorded.')
    ident=uuid.uuid4().hex
    conn.execute('''INSERT INTO collection_payments
        (id,institute_id,student_id,amount_paise,collection_branch_id,payment_channel,payment_method,
        payment_reference,payment_date,payment_timestamp,date_source,posted_at,created_by,request_key,fingerprint)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident,institute_id,student_id,amount,branch_id or None,channel,method,reference,day,timestamp,date_source,ledger.now(),actor_id,request_key,fp))
    if invoice_id:
        allocate(conn,institute_id,actor_id,ident,invoice_id,amount/100,request_key='direct-'+ident,allocation_date=day)
    ledger.audit(conn,institute_id,actor_id,'payment',ident,None,{'amount_paise':amount,'collection_branch_id':branch_id,'channel':channel,'invoice_id':invoice_id},'Payment recorded',day)
    return ident


def allocate(conn,institute_id,actor_id,payment_id,invoice_id,amount,*,request_key,allocation_date=None):
    # Invoice first, then payment: same lock order as direct and gateway receipts.
    inv=ledger.lock_invoice(conn,institute_id,invoice_id)
    if not request_key or len(request_key)>100:
        raise ValueError('An allocation request key is required.')
    allocation_date=date.fromisoformat(allocation_date or ledger.now()[:10]).isoformat()
    fp=fingerprint([payment_id,int(invoice_id),ledger.paise(amount),allocation_date])
    replay=conn.execute('SELECT * FROM allocation_requests WHERE institute_id=? AND request_key=?',(institute_id,request_key)).fetchone()
    if replay:
        if replay['fingerprint']!=fp:
            raise ValueError('Allocation request key already used for different details.')
        return replay['receipt_id']
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    p=conn.execute('SELECT * FROM collection_payments WHERE id=? AND institute_id=?'+suffix,(payment_id,institute_id)).fetchone()
    if not p or int(p['student_id'])!=int(inv['student_id']):
        raise ValueError('Payment and invoice must belong to the same student/institute.')
    if allocation_date<max(str(inv['invoice_date'])[:10],p['payment_date']) or allocation_date>ledger.now()[:10]:
        raise ValueError('Allocation date must follow both the invoice and payment and cannot be in the future.')
    used=conn.execute('''SELECT COALESCE(SUM(r.amount_received),0) n FROM receipt_details d JOIN receipts r
        ON r.id=d.receipt_id AND r.institute_id=d.institute_id WHERE d.payment_id=? AND d.institute_id=?''',(payment_id,institute_id)).fetchone()['n']
    value=ledger.paise(amount)
    returned=conn.execute('SELECT COALESCE(SUM(amount_paise),0) n FROM advance_returns WHERE institute_id=? AND payment_id=?',(institute_id,payment_id)).fetchone()['n']
    if value<=0 or value>int(p['amount_paise'])-ledger.paise(used)-int(returned) or value>ledger.totals(conn,institute_id,invoice_id)['outstanding']:
        raise ValueError('Allocation exceeds unallocated money or invoice balance.')
    if inv['status']=='cancelled':
        raise ValueError('Cannot allocate to a cancelled invoice.')
    settings=conn.execute('SELECT receipt_prefix FROM institute_settings WHERE institute_id=?',(institute_id,)).fetchone()
    if not settings:
        raise ValueError('Configure receipt numbering first.')
    number=allocate_document_number(conn.cursor(),institute_id,'receipt',settings['receipt_prefix'])
    stamp=ledger.now()
    cur=conn.execute('''INSERT INTO receipts
        (receipt_no,invoice_id,institute_id,receipt_date,amount_received,payment_mode,notes,created_by,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (number,invoice_id,institute_id,p['payment_date'],value/100,p['payment_method'],p['payment_reference'],p['created_by'],stamp))
    receipt_id=cur.lastrowid
    conn.execute('INSERT INTO allocation_requests (institute_id,request_key,fingerprint,receipt_id) VALUES (?,?,?,?)',(institute_id,request_key,fp,receipt_id))
    receipt=dict(conn.execute('SELECT * FROM receipts WHERE id=?',(receipt_id,)).fetchone())
    conn.execute('INSERT INTO receipt_details (receipt_id,institute_id,payment_id,original_json,recorded_at,allocation_date) VALUES (?,?,?,?,?,?)',
                 (receipt_id,institute_id,payment_id,json.dumps(receipt,default=str),stamp,allocation_date))
    ledger.snapshot_invoice(conn,institute_id,invoice_id)
    ledger.sync_installments(conn,institute_id,invoice_id)
    ledger.audit(conn,institute_id,actor_id,'receipt_allocation',receipt_id,None,{'payment_id':payment_id,'invoice_id':invoice_id,'amount_paise':value},'Payment allocated to invoice',stamp[:10])
    return receipt_id


def return_advance(conn,institute_id,actor_id,payment_id,amount,day,reason,request_key):
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    p=conn.execute('SELECT * FROM collection_payments WHERE id=? AND institute_id=?'+suffix,(payment_id,institute_id)).fetchone()
    if not p:
        raise ValueError('Payment not found.')
    day=date.fromisoformat(day).isoformat();value=ledger.paise(amount)
    if not request_key or day<p['payment_date'] or day>ledger.now()[:10]:
        raise ValueError('Use a valid request key and return date after payment.')
    old=conn.execute('SELECT * FROM advance_returns WHERE institute_id=? AND request_key=?',(institute_id,request_key)).fetchone()
    if old:
        if old['payment_id']!=payment_id or int(old['amount_paise'])!=value or old['effective_date']!=day or old['reason']!=reason:
            raise ValueError('Return request key already used for different details.')
        return old['id']
    allocated=conn.execute('''SELECT COALESCE(SUM(r.amount_received),0) n FROM receipts r JOIN receipt_details d
        ON d.receipt_id=r.id AND d.institute_id=r.institute_id WHERE d.payment_id=? AND d.institute_id=?''',(payment_id,institute_id)).fetchone()['n']
    returned=conn.execute('SELECT COALESCE(SUM(amount_paise),0) n FROM advance_returns WHERE institute_id=? AND payment_id=?',(institute_id,payment_id)).fetchone()['n']
    if value<=0 or value>int(p['amount_paise'])-ledger.paise(allocated)-int(returned):
        raise ValueError('Return exceeds the unallocated advance.')
    ident=uuid.uuid4().hex
    conn.execute('INSERT INTO advance_returns (id,institute_id,payment_id,amount_paise,effective_date,recorded_at,created_by,reason,request_key) VALUES (?,?,?,?,?,?,?,?,?)',
                 (ident,institute_id,payment_id,value,day,ledger.now(),actor_id,reason,request_key))
    ledger.audit(conn,institute_id,actor_id,'advance_return',ident,None,{'payment_id':payment_id,'amount_paise':value},reason,day)
    return ident


def cash_event_location(conn,institute_id,actor_id,event_id,branch_id,channel,reference):
    """Refund location is supplied explicitly, never inherited from receipt."""
    if channel not in {'branch','bank','online','unresolved'}:
        raise ValueError('Choose a refund channel.')
    if channel=='branch' and not branch_id:
        raise ValueError('Select the refund payout branch.')
    if branch_id:owned(conn,'branches',branch_id,institute_id)
    reference=(reference or '').strip().upper() or None
    if channel in {'bank','online'} and not reference:
        raise ValueError('A payout reference is required for bank/online refunds.')
    old=conn.execute('SELECT * FROM cash_event_details WHERE event_id=? AND institute_id=?',(event_id,institute_id)).fetchone()
    if old:
        if old['branch_id']!=branch_id or old['channel']!=channel or old['payment_reference']!=reference:
            raise ValueError('Refund retry has different payout details.')
        return
    conn.execute('INSERT INTO cash_event_details (event_id,institute_id,branch_id,channel,payment_reference,recorded_at,created_by) VALUES (?,?,?,?,?,?,?)',
                 (event_id,institute_id,branch_id,channel,reference,ledger.now(),actor_id))


def attach_gateway(conn,order,receipt_id,payment_data,posted_at):
    """Gateway location stays NULL. Never infer it from invoice or staff branch."""
    if not ledger.available(conn):
        return
    receipt=dict(conn.execute('SELECT * FROM receipts WHERE id=? AND institute_id=?',(receipt_id,order['institute_id'])).fetchone())
    timestamp=payment_data.get('payment_completion_time') or payment_data.get('payment_time')
    if timestamp:
        from datetime import datetime
        try:
            parsed=datetime.fromisoformat(str(timestamp).replace('Z','+00:00'))
            if parsed.tzinfo is None:
                raise ValueError
            timestamp=parsed.astimezone(ledger.IST).isoformat()
            day=timestamp[:10];date_source='gateway_timestamp'
        except ValueError:
            timestamp=None
    if not timestamp:
        day=posted_at[:10];date_source='posting_fallback'
    ident=uuid.uuid4().hex
    conn.execute('''INSERT INTO collection_payments
        (id,institute_id,student_id,amount_paise,collection_branch_id,payment_channel,payment_method,payment_reference,
        payment_date,payment_timestamp,date_source,posted_at,created_by,request_key,fingerprint)
        VALUES (?,?,?,?,NULL,'online',?,?,?,?,?,?,?,?,?)''',
        (ident,order['institute_id'],order['student_id'],order['amount_paise'],receipt['payment_mode'],
         str(payment_data['cf_payment_id']),day,timestamp,date_source,posted_at,order['created_by'],order['order_id'],fingerprint(order['order_id'])))
    conn.execute('UPDATE receipts SET receipt_date=? WHERE id=? AND institute_id=?',(day,receipt_id,order['institute_id']))
    receipt['receipt_date']=day
    conn.execute('INSERT INTO receipt_details (receipt_id,institute_id,payment_id,original_json,recorded_at,allocation_date) VALUES (?,?,?,?,?,?)',
                 (receipt_id,order['institute_id'],ident,json.dumps(receipt,default=str),posted_at,day))

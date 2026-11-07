"""Read-only course allocations of invoice totals and individual receipts."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP


UNASSIGNED = 'Unassigned / legacy items'


def paise(value):
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def money(value):
    return (Decimal(value) / 100).quantize(Decimal('0.01'))


def split_amount(amount, weights):
    """Largest-remainder allocation, preserving every paise and a stable tie order."""
    weights = {key: max(0, value) for key, value in weights.items()}
    total = sum(weights.values())
    if not total:
        return {None: amount} if amount else {key: 0 for key in weights} or {None: 0}
    sign = -1 if amount < 0 else 1
    divided = {key: divmod(abs(amount) * weight, total) for key, weight in weights.items()}
    result = {key: quotient for key, (quotient, _) in divided.items()}
    remainder = abs(amount) - sum(result.values())
    order = sorted(divided, key=lambda key: (-divided[key][1], key is None, key or 0))
    for key in order[:remainder]:
        result[key] += 1
    return {key: value * sign for key, value in result.items()}


def load_course_billing(conn, institute_id, kind, *, start_date='', end_exclusive='',
                        branch_id=None, course_filter='', include_cancelled=False):
    if kind not in {'invoices', 'receipts'}:
        raise ValueError('Unknown course billing report')
    receipt_report = kind == 'receipts'
    date_column = 'r.receipt_date' if receipt_report else 'i.invoice_date'
    where = ['i.institute_id = ?']
    params = [institute_id]
    if start_date:
        where.append(date_column+' >= ?')
        params.append(start_date)
    if end_exclusive:
        where.append(date_column+' < ?')
        params.append(end_exclusive)
    if branch_id is not None:
        where.append('i.branch_id = ?')
        params.append(branch_id)
    if not receipt_report and not include_cancelled:
        where.append("COALESCE(i.status, '') <> 'cancelled'")

    if receipt_report:
        source = '''receipts r JOIN invoices i ON i.id=r.invoice_id AND i.institute_id=r.institute_id'''
        transaction = '''r.id AS transaction_id, r.receipt_no AS transaction_no,
                         r.receipt_date AS transaction_date, r.amount_received AS amount,
                         r.payment_mode'''
    else:
        source = 'invoices i'
        transaction = '''i.id AS transaction_id, i.invoice_no AS transaction_no,
                         i.invoice_date AS transaction_date, i.total_amount AS amount,
                         NULL AS payment_mode'''
    events = conn.execute(f'''SELECT {transaction}, i.id AS invoice_id, i.invoice_no,
        i.student_id, i.status, s.full_name, s.student_code, b.branch_name
        FROM {source}
        JOIN students s ON s.id=i.student_id AND s.institute_id=i.institute_id
        LEFT JOIN branches b ON b.id=i.branch_id AND b.institute_id=i.institute_id
        WHERE {' AND '.join(where)} ORDER BY {date_column} DESC, transaction_id DESC''', params).fetchall()

    # Fetch every item on the selected invoices before applying a course filter.
    # Joining receipts directly to items would duplicate amounts and item weights.
    invoice_ids = sorted({row['invoice_id'] for row in events})
    weights = defaultdict(lambda: defaultdict(int))
    names = {None: UNASSIGNED}
    for offset in range(0, len(invoice_ids), 500):
        ids = invoice_ids[offset:offset+500]
        placeholders = ','.join('?' for _ in ids)
        items = conn.execute(f'''SELECT ii.invoice_id, ii.line_total, c.id AS course_id, c.course_name
            FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
            LEFT JOIN courses c ON c.id=ii.course_id AND c.institute_id=i.institute_id
            WHERE i.institute_id=? AND i.id IN ({placeholders})''', [institute_id, *ids]).fetchall()
        for item in items:
            key = item['course_id']
            weights[item['invoice_id']][key] += max(0, paise(item['line_total']))
            if key is not None:
                names[key] = item['course_name'] or 'Unnamed course'

    rows = []
    summaries = {}
    all_transactions, all_invoices, all_students = set(), set(), set()
    for event in events:
        amount = paise(event['amount'])
        allocations = split_amount(amount, weights[event['invoice_id']])
        for course_id, allocated in allocations.items():
            key = str(course_id) if course_id is not None else 'unassigned'
            if course_filter and course_filter != key:
                continue
            if receipt_report and amount and not allocated:
                continue
            detail = dict(event)
            detail.update(course_id=course_id, course_key=key, course_name=names.get(course_id, UNASSIGNED),
                          amount_paise=allocated, amount=money(allocated),
                          source_amount=money(amount), transaction_date=str(event['transaction_date'] or ''),
                          branch_name=event['branch_name'] or 'Unassigned branch')
            rows.append(detail)
            if key not in summaries:
                summaries[key] = dict(course_key=key, course_id=course_id, course_name=detail['course_name'],
                                      amount_paise=0, transactions=set(), invoices=set(), students=set())
            summary = summaries[key]
            summary['amount_paise'] += allocated
            summary['transactions'].add(event['transaction_id'])
            summary['invoices'].add(event['invoice_id'])
            summary['students'].add(event['student_id'])
            all_transactions.add(event['transaction_id'])
            all_invoices.add(event['invoice_id'])
            all_students.add(event['student_id'])
    summary_rows = []
    for summary in summaries.values():
        summary_rows.append(dict(course_key=summary['course_key'], course_id=summary['course_id'],
            course_name=summary['course_name'], amount=money(summary['amount_paise']),
            transaction_count=len(summary['transactions']), invoice_count=len(summary['invoices']),
            student_count=len(summary['students'])))
    summary_rows.sort(key=lambda row: (row['course_id'] is None, row['course_name'].casefold(), row['course_id'] or 0))
    rows.sort(key=lambda row: (row['transaction_date'], row['transaction_id']), reverse=True)
    return dict(summary=summary_rows, details=rows, totals=dict(
        amount=money(sum(row['amount_paise'] for row in rows)), transaction_count=len(all_transactions),
        invoice_count=len(all_invoices), student_count=len(all_students),
        course_count=sum(row['course_id'] is not None for row in summary_rows)))

"""Admin course-wise invoice and receipt views with matching CSV exports."""

import csv
import io
from datetime import date, datetime, timedelta

from flask import abort, make_response, render_template, request, send_file, url_for

from db import get_conn
from modules.core.utils import admin_required, login_required
from services.course_billing_reports import load_course_billing
from services.tenant_context import get_current_institute_id


def _date_filter(name):
    value = request.args.get(name, '').strip()
    if value:
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value or parsed == date.max:
                raise ValueError
        except ValueError:
            abort(400, description='Use a valid YYYY-MM-DD date.')
    return value


def _csv_cell(value):
    # Student/course names are text, never spreadsheet formulas. Money remains numeric.
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n'))):
        return "'"+value
    return value if value is not None else ''


def _download(report, kind, download):
    receipt_report = kind == 'receipts'
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    if download == 'summary':
        writer.writerow(['Course ID', 'Course', 'Invoice count',
                         *(['Receipt count'] if receipt_report else []), 'Student count',
                         'Course share received (INR)' if receipt_report else 'Net course invoiced (INR)'])
        records = ([row['course_id'], row['course_name'], row['invoice_count'],
                    *([row['transaction_count']] if receipt_report else []), row['student_count'], row['amount']]
                   for row in report['summary'])
    else:
        writer.writerow(['Receipt no' if receipt_report else 'Invoice no',
                         'Receipt date' if receipt_report else 'Invoice date',
                         *(['Invoice no'] if receipt_report else []),
                         'Registration no', 'Student full name', 'Branch', 'Course ID', 'Course',
                         *(['Payment mode'] if receipt_report else ['Invoice status']),
                         'Course share received (INR)' if receipt_report else 'Net course invoiced (INR)'])
        records = ([row['transaction_no'], row['transaction_date'],
                    *([row['invoice_no']] if receipt_report else []), row['student_code'], row['full_name'],
                    row['branch_name'], row['course_id'], row['course_name'],
                    row['payment_mode'] if receipt_report else row['status'], row['amount']]
                   for row in report['details'])
    for record in records:
        writer.writerow([_csv_cell(value) for value in record])
    data = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(data, mimetype='text/csv', as_attachment=True,
                     download_name=f'course_{kind}_{download}_{datetime.now():%Y%m%d_%H%M%S}.csv')


def register_course_billing_reports(blueprint):
    @blueprint.route('/course-wise/<kind>')
    @login_required
    @admin_required
    def course_billing(kind):
        if kind not in {'invoices', 'receipts'}:
            abort(404)
        institute_id = get_current_institute_id()
        if not institute_id:
            abort(403)
        start = _date_filter('start_date')
        end = _date_filter('end_date')
        if start and end and start > end:
            abort(400, description='The start date must be on or before the end date.')
        branch = request.args.get('branch_id', '').strip()
        course = request.args.get('course_id', '').strip()
        download = request.args.get('download', '')
        if download not in {'', 'summary', 'details'}:
            abort(400)
        page = request.args.get('page', '1')
        if not page.isascii() or not page.isdigit() or len(page) > 7 or not 0 < int(page) <= 1000000:
            abort(400, description='Choose a valid page number.')
        page = int(page)
        include_cancelled = request.args.get('include_cancelled') == '1' and kind == 'invoices'
        conn = get_conn()
        try:
            branches = [dict(row) for row in conn.execute('''SELECT id,branch_name FROM branches
                WHERE institute_id=? ORDER BY branch_name''', (institute_id,)).fetchall()]
            courses = [dict(row) for row in conn.execute('''SELECT id,course_name FROM courses
                WHERE institute_id=? ORDER BY course_name''', (institute_id,)).fetchall()]
            if branch and branch not in {str(row['id']) for row in branches}:
                abort(400, description='Choose a branch from this institute.')
            if course and course != 'unassigned' and course not in {str(row['id']) for row in courses}:
                abort(400, description='Choose a course from this institute.')
            report = load_course_billing(conn, institute_id, kind, start_date=start,
                end_exclusive=(date.fromisoformat(end)+timedelta(days=1)).isoformat() if end else '',
                branch_id=int(branch) if branch else None, course_filter=course,
                include_cancelled=include_cancelled)
        finally:
            conn.close()
        if download:
            response = _download(report, kind, download)
        else:
            filters = dict(start_date=start, end_date=end, branch_id=branch, course_id=course)
            if include_cancelled:
                filters['include_cancelled'] = '1'
            def link(**changes):
                return url_for('reports.course_billing', **{'kind':kind, **filters, **changes})
            page_size = 50
            pages = max(1, (len(report['details'])+page_size-1)//page_size)
            page = min(page, pages)
            response = make_response(render_template('reports/course_billing.html', kind=kind, report=report,
                branches=branches, courses=courses, filters=filters, include_cancelled=include_cancelled,
                detail_rows=report['details'][(page-1)*page_size:page*page_size], page=page, pages=pages,
                detail_start=(page-1)*page_size+1 if report['details'] else 0,
                detail_end=min(page*page_size, len(report['details'])), report_link=link))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

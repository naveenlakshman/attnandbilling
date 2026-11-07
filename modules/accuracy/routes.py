import csv
import io
import json
import uuid
import sqlite3
import pymysql
from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for, make_response
from db import get_conn
from modules.core.utils import login_required, admin_required
from services.tenant_context import get_current_institute_id
from services import admissions, collections, finance_ledger as ledger
from services.accuracy_reports import build, KINDS
from services.recovery_preview import preview

accuracy_bp=Blueprint('accuracy',__name__)


def context():
    inst=get_current_institute_id()
    if not inst:
        abort(403)
    conn=get_conn()
    if not ledger.available(conn):
        conn.close();abort(503,description='Apply the ERP accuracy migration before using this workflow.')
    return conn,inst


@accuracy_bp.get('/')
@login_required
@admin_required
def workspace():
    conn,inst=context()
    try:
        data={table:[dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE institute_id=? ORDER BY id',(inst,)).fetchall()]
              for table in ['students','courses','branches','users','receipts','course_admissions','admission_modules','training_assignments','collection_payments','finance_adjustments']}
        data['batches']=[dict(r) for r in conn.execute('SELECT b.* FROM batches b JOIN branches br ON br.id=b.branch_id WHERE br.institute_id=?',(inst,)).fetchall()]
        students={r['id']:r['full_name'] for r in data['students']}
        courses={r['id']:r['course_name'] for r in data['courses']}
        branches={r['id']:r['branch_name'] for r in data['branches']}
        for a in data['course_admissions']:
            a['display_label']=f"{students[a['student_id']]} / {courses[a['course_id']]} / {branches.get(a['origin_branch_id'],'Unresolved')} / {a['id'][:8]}"
        data['writeoffs']=[dict(r) for r in conn.execute('SELECT * FROM bad_debt_writeoffs WHERE institute_id=?',(inst,)).fetchall()]
        data['invoices']=[dict(r) for r in conn.execute('SELECT id,student_id,invoice_no,total_amount,status FROM invoices WHERE institute_id=? ORDER BY id DESC',(inst,)).fetchall()]
        data['items']=[dict(r) for r in conn.execute('SELECT ii.id,ii.invoice_id,ii.description FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.institute_id=? ORDER BY ii.id DESC',(inst,)).fetchall()]
        data['audit']=[dict(r) for r in conn.execute('SELECT * FROM accuracy_audit WHERE institute_id=? ORDER BY recorded_at DESC LIMIT 100',(inst,)).fetchall()]
        selected=request.args.get('invoice_id','')
        balance=None
        if selected:
            try:balance=ledger.totals(conn,inst,int(selected))
            except (ValueError,TypeError):abort(404)
        return render_template('accuracy/workspace.html',data=data,today=ledger.now()[:10],key=uuid.uuid4().hex,selected_invoice=selected,balance=balance)
    finally:
        conn.close()


@accuracy_bp.post('/action')
@login_required
@admin_required
def action():
    conn,inst=context();d=request.get_json() if request.is_json else request.form.to_dict()
    try:
        ledger.begin(conn)
        who=session['user_id'];operation=d.get('operation');day=d.get('effective_date') or ledger.now()[:10]
        reason=d.get('reason','').strip()
        if operation=='admission':
            result=admissions.admission(conn,inst,who,int(d['student_id']),int(d['course_id']),d['admission_date'],int(d['branch_id']) if d.get('branch_id') else None,
                modules=d.get('modules','').split(','),version=d.get('version') or 'current',source=d.get('source','staff'),
                original_creator_id=int(d['original_creator_id']) if d.get('original_creator_id') else None,source_reference=d.get('source_reference'))
        elif operation=='correct_admission':
            changes={k:d[k] for k in ['admission_date','status'] if d.get(k)}
            for k in ['origin_branch_id','original_creator_id']:
                if k in d and d[k]!='':changes[k]=None if d[k]=='unresolved' else int(d[k])
            admissions.correct(conn,inst,who,d['admission_id'],changes,reason,day);result=d['admission_id']
        elif operation=='link_item':
            admissions.link_item(conn,inst,who,int(d['item_id']),d['admission_id'],day,reason);result=d['item_id']
        elif operation=='assignment':
            result=admissions.assign(conn,inst,who,d['admission_id'],d['module_id'],int(d['batch_id']),d['start_date'],end=d.get('end_date') or None,previous=d.get('previous') or None,reason=reason)
        elif operation=='close_assignment':
            admissions.close_assignment(conn,inst,who,d['assignment_id'],d['end_date'],reason);result=d['assignment_id']
        elif operation=='payment':
            result=collections.payment(conn,inst,who,int(d['student_id']),d['amount'],d['payment_date'],int(d['branch_id']) if d.get('branch_id') else None,
                d['channel'],d['method'],d.get('reference'),d['request_key'],invoice_id=int(d['invoice_id']) if d.get('invoice_id') else None)
        elif operation=='allocate':
            result=collections.allocate(conn,inst,who,d['payment_id'],int(d['invoice_id']),d['amount'],request_key=d['request_key'],allocation_date=d.get('allocation_date') or None)
        elif operation=='return_advance':
            result=collections.return_advance(conn,inst,who,d['payment_id'],d['amount'],day,reason,d['request_key'])
        elif operation=='adjustment':
            result=ledger.adjust(conn,inst,who,int(d['invoice_id']),d['kind'],d['amount'],day,reason,
                receipt_id=int(d['receipt_id']) if d.get('receipt_id') else None,writeoff_id=int(d['writeoff_id']) if d.get('writeoff_id') else None,
                reverse_of=d.get('reverse_of') or None,request_key=d['request_key'])
        else:
            raise ValueError('Unknown operation.')
        if operation=='return_advance' or (operation=='adjustment' and d.get('kind')=='refund'):
            collections.cash_event_location(conn,inst,who,result,int(d['payout_branch_id']) if d.get('payout_branch_id') else None,
                d.get('payout_channel','unresolved'),d.get('payout_reference'))
        conn.commit()
        if request.is_json:return jsonify(id=result),201
        flash('Saved with audit history.','success')
        return redirect(url_for('accuracy.workspace'))
    except (ValueError,KeyError,TypeError) as exc:
        conn.rollback()
        if request.is_json:return jsonify(error=str(exc)),400
        flash(str(exc),'danger');return redirect(url_for('accuracy.workspace'))
    except (sqlite3.IntegrityError,pymysql.IntegrityError):
        conn.rollback()
        if request.is_json:return jsonify(error='Duplicate reference or request; reload and review the recorded transaction.'),409
        flash('Duplicate reference or request; review the recorded transaction.','warning')
        return redirect(url_for('accuracy.workspace'))
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()


@accuracy_bp.get('/reports/<kind>')
@login_required
@admin_required
def report(kind):
    conn,inst=context()
    try:
        today=ledger.now()[:10]
        result=build(conn,inst,kind,request.args.get('start',today[:7]+'-01'),request.args.get('end',today),request.args.get('cutoff',today),request.args.get('branch',''))
        if request.args.get('format')=='json':return jsonify(result)
        if request.args.get('format')=='csv':
            stream=io.StringIO();writer=csv.writer(stream)
            for key in ['kind','start','end','cutoff','branch_basis','tax_basis','cancellation_treatment','cutoff_basis','incomplete_month']:
                writer.writerow([key,str(result[key])])
            writer.writerow(['undated payments (INR)',format(result['undated_payment_paise']/100,'.2f'),result['unknown_date_basis']])
            fields=list(dict.fromkeys(k for row in result['rows'] for k in row))
            writer.writerow([k.replace("_paise"," (INR)") for k in fields])
            for row in result['rows']:
                writer.writerow([format(row.get(k,0)/100,'.2f') if k.endswith('_paise') else (("'"+str(row.get(k,''))) if str(row.get(k,'')).lstrip().startswith(('=','+','-','@')) and not isinstance(row.get(k),int) else row.get(k,'')) for k in fields])
            response=make_response(stream.getvalue().encode('utf-8-sig'));response.headers['Content-Type']='text/csv'
            response.headers['Content-Disposition']=f'attachment; filename="{kind}.csv"';return response
        branches=[dict(r) for r in conn.execute('SELECT id,branch_name FROM branches WHERE institute_id=?',(inst,)).fetchall()]
        return render_template('accuracy/report.html',report=result,kinds=sorted(KINDS),branches=branches,fields=list(dict.fromkeys(k for r in result['rows'] for k in r)))
    except ValueError as exc:
        abort(400,description=str(exc))
    finally:conn.close()


@accuracy_bp.get('/recovery-preview')
@login_required
@admin_required
def recovery():
    conn,inst=context()
    try:return jsonify(preview(conn,inst))
    finally:conn.close()


@accuracy_bp.after_request
def private(response):
    response.headers['Cache-Control']='private, no-store'
    return response

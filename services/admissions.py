"""Admission origin and dated training assignments, independent of student branch."""
from datetime import date, timedelta
import json
import re
import uuid

from services.finance_ledger import audit, now


def owned(conn, table, ident, institute_id):
    if table not in {'students','courses','branches','users','course_admissions','admission_modules'}:
        raise ValueError('Invalid entity.')
    row=conn.execute(f'SELECT * FROM {table} WHERE id=? AND institute_id=?',(ident,institute_id)).fetchone()
    if not row:
        raise ValueError('Record not found in this institute.')
    return dict(row)


def admission(conn,institute_id,actor_id,student_id,course_id,day,branch_id,*,modules=(),version='current',source='staff',original_creator_id=None,source_reference=None):
    day=date.fromisoformat(day).isoformat()
    owned(conn,'students',student_id,institute_id)
    course=owned(conn,'courses',course_id,institute_id)
    if branch_id:
        owned(conn,'branches',branch_id,institute_id)
    if source not in {'staff','import','recovered'}:
        raise ValueError('Choose a valid admission source.')
    creator=actor_id if source=='staff' else original_creator_id
    if creator:
        owned(conn,'users',creator,institute_id)
    if source!='staff' and not source_reference:
        raise ValueError('Imported/recovered admissions require a source reference.')
    if source=='staff' and not branch_id:
        raise ValueError('Select the original admission branch.')
    modules=[m.strip() for m in modules if m.strip()]
    if not modules:
        modules=['Basics','Tally'] if bool(re.search(r'\bDFA\b',course['course_name'],re.IGNORECASE)) else [course['course_name']]
    ident=uuid.uuid4().hex;stamp=now()
    conn.execute('''INSERT INTO course_admissions
        (id,institute_id,student_id,course_id,course_version,course_snapshot,admission_date,
         origin_branch_id,original_creator_id,source,source_reference,imported_by,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident,institute_id,student_id,course_id,version,json.dumps(course,default=str),day,branch_id or None,
         creator,source,source_reference,actor_id if source!='staff' else None,'active',stamp,stamp))
    for module in dict.fromkeys(m.strip() for m in modules if m.strip()):
        conn.execute('INSERT INTO admission_modules (id,institute_id,admission_id,module_name) VALUES (?,?,?,?)',
                     (uuid.uuid4().hex,institute_id,ident,module))
    after=owned(conn,'course_admissions',ident,institute_id)
    audit(conn,institute_id,actor_id,'admission',ident,None,after,'Admission created',day)
    return ident


def correct(conn,institute_id,actor_id,ident,changes,reason,day):
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    conn.execute('SELECT id FROM course_admissions WHERE id=? AND institute_id=?'+suffix,(ident,institute_id)).fetchone()
    before=owned(conn,'course_admissions',ident,institute_id)
    allowed={'origin_branch_id','original_creator_id','admission_date','status'}
    if not changes or set(changes)-allowed:
        raise ValueError('Only admission origin/date/creator/status may be corrected.')
    if changes.get('origin_branch_id'):
        owned(conn,'branches',changes['origin_branch_id'],institute_id)
    if changes.get('original_creator_id'):
        owned(conn,'users',changes['original_creator_id'],institute_id)
    if 'admission_date' in changes:
        changes['admission_date']=date.fromisoformat(changes['admission_date']).isoformat()
    if 'status' in changes and changes['status'] not in {'active','completed','cancelled','dropped'}:
        raise ValueError('Invalid admission status.')
    day=date.fromisoformat(day).isoformat()
    if day>now()[:10]:raise ValueError('Correction effective date cannot be in the future.')
    audit(conn,institute_id,actor_id,'admission',ident,before,{**before,**changes},reason,day)
    columns=','.join(k+'=?' for k in changes)
    conn.execute(f'UPDATE course_admissions SET {columns},updated_at=? WHERE id=? AND institute_id=?',
                 [*changes.values(),now(),ident,institute_id])


def as_of(conn,institute_id,cutoff):
    result=[]
    for r in conn.execute('SELECT * FROM course_admissions WHERE institute_id=?',(institute_id,)).fetchall():
        current=dict(r)
        events=conn.execute("SELECT * FROM accuracy_audit WHERE institute_id=? AND entity_type='admission' AND entity_id=? ORDER BY event_order",(institute_id,r['id'])).fetchall()
        if events:
            current=json.loads(events[0]['after_json'])
            for event in events[1:]:
                if event['effective_date']<=cutoff:
                    before=json.loads(event['before_json']) or {}
                    after=json.loads(event['after_json'])
                    current.update({k:v for k,v in after.items() if before.get(k)!=v})
        if current['admission_date']<=cutoff:
            result.append(current)
    return result


def link_item(conn,institute_id,actor_id,item_id,admission_id,day,reason):
    a=owned(conn,'course_admissions',admission_id,institute_id)
    row=conn.execute('''SELECT ii.*,i.student_id FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
        WHERE ii.id=? AND i.institute_id=?''',(item_id,institute_id)).fetchone()
    if not row or int(row['student_id'])!=int(a['student_id']) or row['course_id']!=a['course_id']:
        raise ValueError('Invoice item must match the admission student and course.')
    if conn.execute('SELECT 1 FROM invoice_item_admissions WHERE item_id=?',(item_id,)).fetchone():
        raise ValueError('Item already linked; reverse/reissue an erroneous posted invoice rather than relinking history.')
    day=date.fromisoformat(day).isoformat()
    conn.execute('INSERT INTO invoice_item_admissions (item_id,institute_id,admission_id,effective_date,linked_by,linked_at) VALUES (?,?,?,?,?,?)',
                 (item_id,institute_id,admission_id,day,actor_id,now()))
    audit(conn,institute_id,actor_id,'invoice_item',item_id,None,{'admission_id':admission_id},reason,day)


def assign(conn,institute_id,actor_id,admission_id,module_id,batch_id,start,*,end=None,previous=None,reason):
    a=owned(conn,'course_admissions',admission_id,institute_id)
    # Lock admission to serialize overlapping assignments for this module.
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    locked=conn.execute('SELECT * FROM course_admissions WHERE id=? AND institute_id=?'+suffix,(admission_id,institute_id)).fetchone()
    if not locked:raise ValueError('Admission not found.')
    a=dict(locked)
    m=owned(conn,'admission_modules',module_id,institute_id)
    if m['admission_id']!=admission_id:
        raise ValueError('Module does not belong to this admission.')
    b=conn.execute('''SELECT b.* FROM batches b JOIN branches br ON br.id=b.branch_id
        WHERE b.id=? AND br.institute_id=?''',(batch_id,institute_id)).fetchone()
    if not b or b['status']=='cancelled':
        raise ValueError('Choose a batch in this institute.')
    if b['trainer_id']:
        owned(conn,'users',b['trainer_id'],institute_id)
    start=date.fromisoformat(start).isoformat();end=date.fromisoformat(end).isoformat() if end else None
    if end and end<start:
        raise ValueError('Assignment end precedes its start.')
    if a['status']=='cancelled' or start<a['admission_date']:
        raise ValueError('Training must follow an active admission.')
    if previous:
        old=conn.execute('SELECT * FROM training_assignments WHERE id=? AND institute_id=?'+suffix,(previous,institute_id)).fetchone()
        if not old or old['admission_id']!=admission_id or old['module_id']!=module_id or old['end_date'] or old['start_date']>=start:
            raise ValueError('Select an open previous assignment that starts earlier.')
        stop=(date.fromisoformat(start)-timedelta(days=1)).isoformat()
        conn.execute('UPDATE training_assignments SET end_date=? WHERE id=?',(stop,previous))
        audit(conn,institute_id,actor_id,'training_assignment',previous,dict(old),{**dict(old),'end_date':stop},reason,start)
        if stop<now()[:10]:
            other=conn.execute('''SELECT id FROM training_assignments WHERE institute_id=? AND admission_id=?
                AND batch_id=? AND id<>? AND (end_date IS NULL OR end_date>=?)''',(institute_id,admission_id,old['batch_id'],previous,now()[:10])).fetchone()
            if not other:
                conn.execute("UPDATE student_batches SET status='completed',updated_at=? WHERE student_id=? AND batch_id=?",(now(),a['student_id'],old['batch_id']))
    overlap=conn.execute('''SELECT id FROM training_assignments WHERE institute_id=? AND admission_id=? AND module_id=?
        AND start_date<=? AND (end_date IS NULL OR end_date>=?)'''+suffix,(institute_id,admission_id,module_id,end or '9999-12-31',start)).fetchone()
    if overlap:
        raise ValueError('This module already has a training assignment during that period.')
    ident=uuid.uuid4().hex
    conn.execute('''INSERT INTO training_assignments
        (id,institute_id,admission_id,module_id,batch_id,branch_id,trainer_id,start_date,end_date,previous_assignment_id,reason,created_by,recorded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident,institute_id,admission_id,module_id,batch_id,b['branch_id'],b['trainer_id'],start,end,previous,reason,actor_id,now()))
    existing=conn.execute('SELECT id FROM student_batches WHERE student_id=? AND batch_id=?',(a['student_id'],batch_id)).fetchone()
    if existing:
        # Assignment episodes retain every date. The legacy roster only controls
        # current attendance; never overwrite its original joined_on.
        conn.execute("UPDATE student_batches SET status='active',updated_at=? WHERE id=?",(now(),existing['id']))
    else:
        conn.execute("INSERT INTO student_batches (student_id,batch_id,joined_on,status,created_at,updated_at) VALUES (?,?,?,'active',?,?)",(a['student_id'],batch_id,start,now(),now()))
    audit(conn,institute_id,actor_id,'training_assignment',ident,None,{'admission_id':admission_id,'module_id':module_id,'batch_id':batch_id,'branch_id':b['branch_id'],'trainer_id':b['trainer_id'],'start_date':start,'end_date':end},reason,start)
    return ident


def close_assignment(conn,institute_id,actor_id,ident,end,reason):
    suffix=' FOR UPDATE' if hasattr(conn,'_conn') else ''
    parent=conn.execute('SELECT admission_id FROM training_assignments WHERE id=? AND institute_id=?',(ident,institute_id)).fetchone()
    if not parent:raise ValueError('Training assignment not found.')
    conn.execute('SELECT id FROM course_admissions WHERE id=? AND institute_id=?'+suffix,(parent['admission_id'],institute_id)).fetchone()
    row=conn.execute('SELECT * FROM training_assignments WHERE id=? AND institute_id=?'+suffix,(ident,institute_id)).fetchone()
    if not row:raise ValueError('Training assignment not found.')
    end=date.fromisoformat(end).isoformat()
    if row['end_date'] or end<row['start_date']:
        raise ValueError('Choose an open assignment and an end date on/after its start.')
    audit(conn,institute_id,actor_id,'training_assignment',ident,dict(row),{**dict(row),'end_date':end},reason,end)
    conn.execute('UPDATE training_assignments SET end_date=? WHERE id=? AND institute_id=?',(end,ident,institute_id))
    a=owned(conn,'course_admissions',row['admission_id'],institute_id)
    other=conn.execute('''SELECT t.id FROM training_assignments t JOIN course_admissions a ON a.id=t.admission_id AND a.institute_id=t.institute_id
        WHERE t.institute_id=? AND a.student_id=? AND t.batch_id=? AND t.id<>? AND (t.end_date IS NULL OR t.end_date>=?)''',(institute_id,a['student_id'],row['batch_id'],ident,now()[:10])).fetchone()
    if end<now()[:10] and not other:
        conn.execute("UPDATE student_batches SET status='completed',updated_at=? WHERE student_id=? AND batch_id=?",(now(),a['student_id'],row['batch_id']))

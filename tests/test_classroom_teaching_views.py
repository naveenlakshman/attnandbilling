from datetime import date, datetime
from pathlib import Path

from flask import Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
import pytest
from services.batch_schedule import batch_end_summary


ROOT = Path(__file__).resolve().parents[1]


def make_app():
    app = Flask(__name__,static_folder=str(ROOT/'static'))
    app.config.update(TESTING=True,SECRET_KEY='classroom-view-test')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'base.html':'''<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">{% block extra_css %}{% endblock %}<style>body{background:#f8f9fa;color:#17283e} main{max-width:1550px;margin:auto}</style></head><body><main>{% block content %}{% endblock %}</main>{% block extra_js %}{% endblock %}</body></html>'''}),
        FileSystemLoader(str(ROOT/'templates')),
    ])
    app.jinja_env.filters['format_time'] = lambda value: datetime.strptime(value,'%H:%M').strftime('%I:%M %p')
    app.jinja_env.filters['format_ist_datetime'] = lambda value,*args:str(value)
    app.add_url_rule('/attendance/batches/<int:batch_id>',endpoint='attendance.view_batch',view_func=lambda batch_id:'view')
    app.add_url_rule('/lms_admin/batch/<int:batch_id>/teach',endpoint='lms_admin.classroom_teach_mode',view_func=lambda batch_id:'teach')
    batches = []
    for index,name in enumerate(['Advance Excel Batch (4 Students)','CCOM','Python Web Development (Srilekha)','11:30 To 12:30 Spoken English Class','Tally Batch by Naveen','12:00 To 2:00 CCOM Batch','Python Evening Batch','CCOM STUDENTS','6 PM to 7 PM Tally Batch'],1):
        batches.append(dict(id=index,batch_name=name,course_name='Certificate Course in Office Management with AI' if index%2 else 'Python Application Development',branch_name='Hoskote Branch',trainer_name='Naveen Trainer',
            start_time='11:00' if index<6 else '17:00',end_time='13:00' if index<6 else '19:00',student_count=0 if index==9 else index,
            attendance_marked_today=index%2==0,class_completed_today=index%3==0,taught_cnt=index,total_cnt=20 if index!=9 else 0,taught_pct=index*5.0,
            next_topic='Working with functions',earlier_pending_summary='2 earlier topics pending' if index==2 else None,
            today_completed_topics=['Introduction'] if index%3==0 else [],last_taught_topic='Basics',last_taught_at='2026-10-31 10:00',launch_program_id=31 if index!=9 else None))
        batches[-1]['end_summary']=batch_end_summary('2026-11-20' if index!=9 else None,today=date(2026,11,2))
    app.config['BATCHES'] = batches
    def dashboard():
        from flask import request
        return render_template('lms_admin/classroom_teaching_dashboard.html',batches=app.config['BATCHES'],
            total_students=sum(b['student_count'] for b in app.config['BATCHES']),is_admin=request.args.get('staff')!='1',
            trainers=[dict(id=7,full_name='Naveen Trainer')],selected_trainer_id=7)
    app.add_url_rule('/lms_admin/classroom-teaching',endpoint='lms_admin.classroom_teaching_dashboard',view_func=dashboard)
    return app


@pytest.mark.parametrize('view',['cards','list'])
def test_both_views_use_one_filterable_batch_record_and_existing_actions(view):
    app = make_app()
    response = app.test_client().get('/lms_admin/classroom-teaching?view='+view)
    assert response.status_code==200
    html=response.text
    assert html.count('batch-card-col"')==9
    assert html.count('class="classroom-batch-list-row"')==9
    assert ('id="batchCardsContainer"' in html and 'classroom-view-list" id=' in html)==(view=='list')
    assert 'data-classroom-view="'+view+'" aria-controls="batchCardsContainer" aria-pressed="true"' in html
    assert 'name="view" id="classroomViewField" value="'+view+'"' in html
    assert '/lms_admin/batch/1/teach?program_id=31' in html
    assert '/lms_admin/batch/1/teach?program_id=31&amp;show_students=1' in html
    assert '/attendance/batches/1' in html
    assert '1/20 topics (5.0%)' in html
    assert 'Attendance Pending' in html and 'Attendance Marked' in html
    assert 'Class Completed' in html and 'Class Pending' in html
    assert 'Attendance N/A' in html and 'No syllabus configured' in html
    assert 'classroom_teaching_dashboard.js?v=1' in html
    assert html.count('data-days-remaining="18"')==16
    assert 'End date: 20-11-2026' in html and '18 days left' in html
    assert 'End date not set' in html


def test_list_escapes_names_and_staff_has_no_trainer_selector():
    app=make_app()
    app.config['BATCHES'][0]['batch_name']='<script>alert(1)</script>'
    html=app.test_client().get('/lms_admin/classroom-teaching?view=list&staff=1').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html and '<script>alert(1)</script>' not in html
    assert 'id="trainerFilter"' not in html


def test_empty_batches_render_existing_empty_state():
    app=make_app()
    app.config['BATCHES']=[]
    response=app.test_client().get('/lms_admin/classroom-teaching?view=list')
    assert response.status_code==200 and 'No active batches found' in response.text

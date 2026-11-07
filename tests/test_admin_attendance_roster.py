from datetime import datetime,timezone
from pathlib import Path

from flask import Flask,render_template
from jinja2 import ChoiceLoader,DictLoader,FileSystemLoader

from modules.core import routes
from test_attendance_roster_summary import db


def test_admin_dashboard_wires_roster_counts_to_the_rendered_widget(db,monkeypatch):
    class StatsCursor:
        def execute(self,*args):return self
        def fetchone(self):return {'cnt':0,'total':0}
        def fetchall(self):return []
    class Connection:
        def cursor(self):return StatsCursor()
        def execute(self,*args):return db.execute(*args)
        def close(self):pass
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=datetime(2026,11,2,10,0,tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='admin-roster-test')
    app.jinja_loader=ChoiceLoader([
        DictLoader({'base.html':'{% block content %}{% endblock %}'}),
        FileSystemLoader(str(Path(__file__).resolve().parents[1]/'templates')),
    ])
    app.jinja_env.globals['url_for']=lambda endpoint,**values:'/test/'+endpoint
    monkeypatch.setattr(routes,'get_conn',lambda:Connection())
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:7)
    monkeypatch.setattr(routes,'datetime',Clock)
    captured={}
    def render(template,**context):
        captured.update(context)
        return render_template(template,company={'company_short_name':'ERP'},**context)
    monkeypatch.setattr(routes,'render_template',render)
    app.add_url_rule('/dashboard',view_func=routes.dashboard)
    client=app.test_client()
    with client.session_transaction() as state:state.update(user_id=7,role='admin',full_name='Test Admin')
    response=client.get('/dashboard')
    assert response.status_code==200
    assert captured['att_marked']==3 and captured['total_students_today']==4
    assert captured['attendance_rate']==75.0 and captured['att_outside_roster']==1
    assert captured['att_present']==1 and captured['att_absent']==1 and captured['att_leave']==1
    assert '3 of 4 marked' in response.text and '75.0%' in response.text
    assert '1 additional attendance record outside the current roster.' in response.text
    assert 'Attendance by branch' in response.text
    branches={row['branch_id']:row for row in captured['attendance_branches']}
    assert set(branches)=={7,9,10}
    assert branches[7]['pending']==1 and branches[9]['percentage']==100.0
    assert 'data-attendance-branch-id="7"' in response.text
    assert 'data-attendance-branch-id="8"' not in response.text
    assert 'Hoskote &lt;West&gt;' in response.text and 'Hoskote <West>' not in response.text
    assert '66.7%' in response.text and 'No current roster' in response.text

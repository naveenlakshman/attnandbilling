from pathlib import Path

import pytest
from flask import Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]


def make_app():
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='certificate-search-test')
    app.jinja_loader=ChoiceLoader([
        DictLoader({name:'' for name in [
            'includes/sidebar_master.html','includes/mobile_nav_master.html',
            'includes/fab_menu_billing.html','includes/fab_menu_lms.html','includes/fab_menu_main.html',
        ]}),
        FileSystemLoader(str(ROOT/'templates')),
    ])
    app.jinja_env.globals['csrf_token']=lambda:'test-token'
    app.add_url_rule('/dashboard',endpoint='core.dashboard',view_func=lambda:'dashboard')
    def page():
        return render_template('certificates/admin_issue.html',company=dict(company_short_name='Test ERP',company_name='Test Institute'),
            students=[dict(id=7,full_name='Asha Kumar',student_code='REG-007',status='active'),
                      dict(id=8,full_name='Asha Rao',student_code='REG-008',status='completed')],
            selected_student_id=8,selected_course_id=31,courses_list=[dict(id=31,course_name='Accounting')],eligibility=None)
    for endpoint in ['certificates.admin_issue','billing.invoices','baddebt.index','lms_admin.classroom_teaching_dashboard']:
        app.add_url_rule('/'+endpoint,endpoint=endpoint,view_func=page)
    return app


@pytest.mark.parametrize('endpoint,loads_search',[
    ('certificates.admin_issue',True),('billing.invoices',True),('baddebt.index',True),
    ('lms_admin.classroom_teaching_dashboard',False),
])
def test_actual_layout_loads_search_assets_on_certificate_issue_and_billing(endpoint,loads_search):
    app=make_app()
    response=app.test_client().get('/'+endpoint)
    assert response.status_code==200
    html=response.text
    css='https://cdn.jsdelivr.net/npm/tom-select/dist/css/tom-select.css'
    javascript='https://cdn.jsdelivr.net/npm/tom-select/dist/js/tom-select.complete.min.js'
    assert html.count(css)==int(loads_search)
    assert html.count(javascript)==int(loads_search)
    if loads_search:
        assert html.index(css)<html.index('</head>')
        assert html.index(javascript)<html.index('</body>')


def test_student_picker_contains_both_search_keys_and_preserves_completed_selection():
    response=make_app().test_client().get('/certificates.admin_issue')
    html=response.text
    assert 'Asha Kumar (REG-007)' in html
    assert 'Asha Rao (REG-008) - Completed' in html
    assert '<option value="8" selected>' in html
    assert '<option value="31" selected>' in html
    assert 'for="studentSelect"' in html
    assert "Type a student's name or registration number to search." in html
    assert "placeholder: 'Search by student name or registration number'" in html
    assert "searchField: ['text']" in html

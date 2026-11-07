from html.parser import HTMLParser
from pathlib import Path

from flask import Flask, render_template, request
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
import pytest


class SearchForm(HTMLParser):
    def __init__(self,html):
        super().__init__();self.method=None;self.action=None;self.inputs={};self.buttons=[];self.selected={};self.select=None
        self.feed(html)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form':self.method=attrs.get('method');self.action=attrs.get('action')
        if tag=='input':self.inputs[attrs.get('name')]=attrs
        if tag=='button':self.buttons.append(attrs)
        if tag=='select':self.select=attrs.get('name')
        if tag=='option' and self.select and 'selected' in attrs:self.selected[self.select]=attrs.get('value')
    def handle_endtag(self,tag):
        if tag=='select':self.select=None


@pytest.mark.parametrize('query',['Sujan H C','9999999999','1516559'])
def test_manual_get_search_preserves_complete_query_and_filters(query):
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='manual-student-search')
    app.jinja_loader=ChoiceLoader([
        DictLoader({'base.html':'{% block content %}{% endblock %}{% block extra_js %}{% endblock %}'}),
        FileSystemLoader(str(Path(__file__).resolve().parents[1]/'templates')),
    ])
    app.add_url_rule('/export',endpoint='billing.export_students_csv',view_func=lambda:'export')
    app.add_url_rule('/new',endpoint='billing.student_new',view_func=lambda:'new')
    def listing():
        return render_template('billing/students.html',students=[],branches=[dict(id=1,branch_code='HO')],
            all_batches=[dict(id=7,batch_name='Test batch',status='active')],
            search_query=request.args.get('search',''),branch_filter='1',status_filter='active',batch_filter='7',
            stats=dict(active_count=0,completed_count=0,dropped_count=0,total_count=0),branch_stats=[],
            student_batches_map={},student_batch_courses_map={},student_invoiced_courses_map={},
            page=1,total_pages=1,total_matching=0)
    app.add_url_rule('/billing/students',endpoint='billing.students',view_func=listing)
    response=app.test_client().get('/billing/students',query_string={'search':query})
    assert response.status_code==200
    form=SearchForm(response.text)
    assert form.method=='get' and form.action=='/billing/students'
    assert form.inputs['search']['value']==query and form.inputs['search']['type']=='search'
    assert form.selected==dict(branch='1',status='active',batch='7')
    assert any(button.get('type')=='submit' for button in form.buttons)
    assert 'page' not in form.inputs
    assert '>Search</button>' in response.text
    assert 'press Enter or click Search' in response.text

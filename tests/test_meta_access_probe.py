"""Access-probe safety tests. Stubs never demonstrate real Meta authorization."""
import json

import pytest

from scripts.verify_meta_lead_access import AccessCheckError, Graph, secret, verify


class FakeGraph:
    def __init__(self):
        self.calls=[]
        self.app='11';self.page='22';self.form='33';self.registry=['44'];self.lead_form='33'
        self.answers=[{'name':'full_name','values':['Synthetic Person']}]

    def get(self,path,token,**params):
        self.calls.append(path)
        if path=='debug_token':return {'data':{'is_valid':True,'app_id':self.app,'scopes':['leads_retrieval']}}
        if path=='me':return {'id':self.page,'name':'Synthetic Page'}
        assert path=='44'
        return {'id':'44','form_id':self.lead_form,'created_time':'2026-11-12T10:00:00Z','field_data':self.answers}

    def rows(self,path,token,fields):
        self.calls.append(path)
        if path=='22/leadgen_forms':return iter([{'id':self.form,'name':'Synthetic Form'}])
        if path=='33/test_leads':return iter([{'id':ident} for ident in self.registry])
        assert path=='22/subscribed_apps'
        return iter([{'id':'11','subscribed_fields':['leadgen']}])


def run(graph):
    return verify(graph,app_id='11',page_id='22',form_id='33',test_lead_id='44',
                  page_token='DUMMY_PAGE_TOKEN',app_secret='DUMMY_APP_SECRET')


def test_probe_returns_synthetic_proof_without_answers_or_credentials():
    result=run(FakeGraph());text=json.dumps(result)
    assert result['synthetic_retrieval']=='PASSED' and result['app_subscribed_to_leadgen']
    assert result['production_ingestion_enabled'] is False
    assert result['app_review_and_live_access_status']=='REQUIRES_APP_DASHBOARD_VERIFICATION'
    assert result['answer_fields']==['full_name']
    assert all(secret not in text for secret in ['DUMMY_PAGE_TOKEN','DUMMY_APP_SECRET','Synthetic Person'])


@pytest.mark.parametrize('field,value,operation',[
    ('app','99','debug_token'),('page','99','me'),('form','99','form_ownership'),
    ('registry',[],'synthetic_guard'),('lead_form','99','lead_ownership'),('answers',[],'answers'),
])
def test_probe_blocks_wrong_ownership_or_non_test_leads(field,value,operation):
    graph=FakeGraph();setattr(graph,field,value)
    with pytest.raises(AccessCheckError) as error:run(graph)
    assert error.value.details['operation']==operation
    if operation in ['debug_token','me','form_ownership','synthetic_guard']:
        assert '44' not in graph.calls


def test_graph_client_never_logs_meta_error_messages_or_tokens():
    class Response:
        status_code=400
        def json(self):return {'error':{'code':190,'type':'OAuthException','message':'DUMMY_PAGE_TOKEN'}}
    class Session:
        def get(self,url,**kwargs):return Response()
    with pytest.raises(AccessCheckError) as error:
        Graph('v1.0',Session()).get('me','DUMMY_PAGE_TOKEN')
    assert error.value.details['meta_code']==190
    assert 'DUMMY_PAGE_TOKEN' not in str(error.value.details)


def test_probe_requires_pinned_secret_reference_and_explicit_api_version():
    with pytest.raises(AccessCheckError):secret('DUMMY_PAGE_TOKEN')
    with pytest.raises(AccessCheckError):secret('projects/example/secrets/page/versions/latest')
    with pytest.raises(AccessCheckError):Graph('latest')
    with pytest.raises(AccessCheckError):Graph('v1.0').get('22/leads','unused')

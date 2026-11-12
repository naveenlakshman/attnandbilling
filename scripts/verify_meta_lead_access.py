"""Read-only Meta access proof. Retrieves only an explicitly registered test lead.

No webhook subscriptions, lead creation, ERP writes or prospect messages.
Credentials are read from pinned Secret Manager versions and never printed.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests


class AccessCheckError(Exception):
    def __init__(self, operation, reason, **details):
        self.details = dict(operation=operation, reason=reason, **details)
        super().__init__(reason)


def secret(reference):
    match = re.fullmatch(r'projects/([\w-]+)/secrets/([\w-]+)/versions/(\d+)', reference)
    if not match:
        raise AccessCheckError('credentials', 'Use a pinned Secret Manager version reference.')
    cli = shutil.which('gcloud.cmd') or shutil.which('gcloud')
    if not cli:
        raise AccessCheckError('credentials', 'Google Cloud CLI is unavailable.')
    result = subprocess.run([cli, 'secrets', 'versions', 'access', match[3],
                             '--secret='+match[2], '--project='+match[1], '--quiet'], capture_output=True)
    if result.returncode or not result.stdout.strip():
        raise AccessCheckError('credentials', 'Cannot read the approved secret version; verify IAM and reference.')
    return result.stdout.decode('utf8').strip()


class Graph:
    def __init__(self, version, session=None):
        if not re.fullmatch(r'v\d+\.\d+', version):
            raise AccessCheckError('configuration', 'Choose an explicit supported Graph API version.')
        self.base = 'https://graph.facebook.com/'+version
        self.session = session or requests.Session()

    def get(self, path, token, **params):
        if not re.fullmatch(r'(?:me|debug_token|\d+)(?:/(?:leadgen_forms|test_leads|subscribed_apps))?', path):
            raise AccessCheckError('configuration', 'Unsupported read-only access-proof operation.')
        try:
            response = self.session.get(self.base+'/'+path,
                headers={'Authorization': 'Bearer '+token}, params=params, timeout=20)
            data = response.json()
        except (requests.RequestException, ValueError):
            raise AccessCheckError(path, 'Network or invalid-response failure; no credentials logged.') from None
        if response.status_code != 200 or not isinstance(data, dict) or data.get('error'):
            error = data.get('error', {}) if isinstance(data, dict) else {}
            raise AccessCheckError(path, 'Meta denied this operation; check token, permissions and Page Leads Access.',
                                   http_status=response.status_code, meta_code=error.get('code'),
                                   meta_subcode=error.get('error_subcode'), meta_type=error.get('type'))
        return data

    def rows(self, path, token, fields):
        cursor = None
        for _ in range(100):
            params = {'fields': fields, 'limit': 100}
            if cursor:
                params['after'] = cursor
            page = self.get(path, token, **params)
            if not isinstance(page.get('data'), list):
                raise AccessCheckError(path, 'Expected a paginated data list.')
            yield from page['data']
            paging = page.get('paging') or {}
            if not paging.get('next'):
                return
            after = (paging.get('cursors') or {}).get('after')
            if not after or after == cursor:
                raise AccessCheckError(path, 'Pagination did not advance; cannot certify completeness.')
            cursor = after
        raise AccessCheckError(path, 'Access-proof pagination limit reached; review the result.')


def verify(graph, *, app_id, page_id, form_id, test_lead_id, page_token, app_secret):
    if not all(re.fullmatch(r'\d+', value) for value in [app_id, page_id, form_id, test_lead_id]):
        raise AccessCheckError('configuration', 'Meta IDs must be explicitly supplied numeric strings.')
    debug = graph.get('debug_token', app_id+'|'+app_secret, input_token=page_token).get('data') or {}
    if not debug.get('is_valid') or str(debug.get('app_id')) != app_id:
        raise AccessCheckError('debug_token', 'Token is invalid or belongs to a different Meta app.')
    page = graph.get('me', page_token, fields='id,name')
    if str(page.get('id')) != page_id:
        raise AccessCheckError('me', 'The intended authorization did not resolve to the configured Page.')
    form = next((row for row in graph.rows(page_id+'/leadgen_forms', page_token, 'id,name,status')
                 if str(row.get('id')) == form_id), None)
    if not form:
        raise AccessCheckError('form_ownership', 'Configured form is not accessible on the configured Page.')
    if not any(str(row.get('id')) == test_lead_id
               for row in graph.rows(form_id+'/test_leads', page_token, 'id')):
        raise AccessCheckError('synthetic_guard', 'Lead is not in this form test-lead registry; do not retrieve it.')
    lead = graph.get(test_lead_id, page_token, fields='id,form_id,created_time,field_data')
    if str(lead.get('id')) != test_lead_id or str(lead.get('form_id')) != form_id:
        raise AccessCheckError('lead_ownership', 'Retrieved test lead identity/form does not match.')
    fields = lead.get('field_data')
    if not isinstance(fields, list) or not fields:
        raise AccessCheckError('answers', 'No submitted test answers were retrieved.')
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), app_id=app_id,
                  page_id=page_id, page_name=page.get('name'), form_id=form_id, form_name=form.get('name'),
                  test_lead_id=test_lead_id, created_time=lead.get('created_time'),
                  answer_fields=[row.get('name') for row in fields], answer_count=len(fields),
                  answer_values_sha256=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest(),
                  token_scopes=debug.get('scopes',[]), token_expires_at=debug.get('expires_at'),
                  token_data_access_expires_at=debug.get('data_access_expires_at'),
                  synthetic_retrieval='PASSED', production_ingestion_enabled=False,
                  app_review_and_live_access_status='REQUIRES_APP_DASHBOARD_VERIFICATION')
    try:
        apps = list(graph.rows(page_id+'/subscribed_apps', page_token, 'id,subscribed_fields'))
        result['app_subscribed_to_leadgen'] = any(str(a.get('id'))==app_id and
            'leadgen' in a.get('subscribed_fields',[]) for a in apps)
    except AccessCheckError as exc:
        result['subscription_read_blocker'] = exc.details
        result['app_subscribed_to_leadgen'] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['graph-version','app-id','page-id','form-id','test-lead-id','page-token-reference','app-secret-reference','output']:
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        result = verify(Graph(args.graph_version), app_id=args.app_id, page_id=args.page_id,
            form_id=args.form_id, test_lead_id=args.test_lead_id,
            page_token=secret(args.page_token_reference), app_secret=secret(args.app_secret_reference))
    except AccessCheckError as exc:
        result = dict(synthetic_retrieval='BLOCKED', production_ingestion_enabled=False, blocker=exc.details)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result,indent=2))
    return 0 if result['synthetic_retrieval']=='PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

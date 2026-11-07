import json
from types import SimpleNamespace

import pytest

from ops import cashfree_production_release as release


def test_live_secret_upload_uses_stdin_and_records_only_pinned_references(tmp_path,monkeypatch,capsys):
    app_id = 'LIVE-release-fixture'
    secret = 'fixture-only-cashfree-key'
    (tmp_path/'.env').write_text('CASHFREE_LIVE_APP_ID='+app_id+'\nCASHFREE_LIVE_SECRET_KEY='+secret+'\n')
    monkeypatch.setattr(release,'ROOT',tmp_path)
    monkeypatch.setattr(release,'RECORD',tmp_path/'record')
    monkeypatch.setattr(release,'service',lambda:{'spec':{'template':{'spec':{
        'serviceAccountName':'attn-billing-runtime@global-it-edu-app.iam.gserviceaccount.com'}}}})
    calls = []

    def cli(*args,data=None,check=True):
        calls.append((args,data))
        if args[:2] == ('secrets','describe'):
            return SimpleNamespace(returncode=1,stdout=b'',stderr=b'not found')
        if args[:3] == ('secrets','versions','add'):
            return SimpleNamespace(returncode=0,stdout=('projects/test/secrets/'+args[3]+'/versions/1\n').encode())
        return SimpleNamespace(returncode=0,stdout=b'')

    monkeypatch.setattr(release,'gcloud',cli)
    release.store_secrets()
    output = capsys.readouterr().out
    record = (tmp_path/'record'/'cashfree-secret-versions.json').read_text()
    assert app_id not in output+record and secret not in output+record
    assert set(json.loads(record)) == {'CASHFREE_APP_ID','CASHFREE_SECRET_KEY'}
    uploads = [(args,data) for args,data in calls if args[:3] == ('secrets','versions','add')]
    assert [data for args,data in uploads] == [app_id.encode(),secret.encode()]
    for args,data in calls:
        assert app_id not in ' '.join(args) and secret not in ' '.join(args)
    assert all('--data-file=-' in args for args,data in uploads)
    assert len([args for args,data in calls if 'add-iam-policy-binding' in args]) == 2


def test_secret_upload_rejects_sandbox_keys_before_any_cloud_action(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('CASHFREE_LIVE_APP_ID=TEST-fixture\nCASHFREE_LIVE_SECRET_KEY=fake\n')
    monkeypatch.setattr(release,'ROOT',tmp_path)
    monkeypatch.setattr(release,'service',lambda:pytest.fail('Sandbox credentials must not reach production provisioning.'))
    with pytest.raises(RuntimeError,match='complete CASHFREE_LIVE'):
        release.store_secrets()

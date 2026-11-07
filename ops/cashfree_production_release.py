"""Production Cashfree preflight and secret provisioning; never prints secret values."""

import argparse
import json
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values
import pymysql

PROJECT = 'global-it-edu-app'
REGION = 'asia-south1'
SERVICE = 'global-it-erp-production'
INSTANCE = 'global-it-erp-production-db'
ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'scratch' / 'cashfree-production-release'


def gcloud(*args, data=None, check=True):
    executable = shutil.which('gcloud.cmd') or shutil.which('gcloud')
    if not executable:
        raise RuntimeError('Google Cloud CLI is unavailable.')
    result = subprocess.run([executable,*args,'--quiet'], input=data, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip())
    return result


def cloud_json(*args):
    return json.loads(gcloud(*args,'--format=json').stdout)


def service():
    return cloud_json('run','services','describe',SERVICE,'--project='+PROJECT,'--region='+REGION)


def inventory():
    live = service()
    template = live['spec']['template']
    container = template['spec']['containers'][0]
    allowed = {'APP_ENV','DB_TYPE','DB_CONNECTION_MODE','MYSQL_HOST','MYSQL_PORT','MYSQL_USER','MYSQL_DB',
        'MYSQL_UNIX_SOCKET','CLOUD_SQL_CONNECTION_NAME','CLOUD_SQL_ENABLE_IAM_AUTH','GCS_BUCKET_NAME',
        'CASHFREE_MODE','CASHFREE_API_URL','CASHFREE_INSTITUTE_ID','CASHFREE_PAYMENT_LINKS_ENABLED',
        'CASHFREE_PAYMENT_LINK_BASE_URL','CASHFREE_NOTIFY_URL'}
    env = {item['name']:item for item in container.get('env',[])}
    sql = cloud_json('sql','instances','describe',INSTANCE,'--project='+PROJECT)
    backups = cloud_json('sql','backups','list','--instance='+INSTANCE,'--project='+PROJECT,'--limit=3')
    report = dict(project=PROJECT,service=SERVICE,traffic=live.get('status',{}).get('traffic'),
        image=container.get('image'),runtime_account=template['spec'].get('serviceAccountName'),
        resources=container.get('resources'),concurrency=template['spec'].get('containerConcurrency'),
        timeout=template['spec'].get('timeoutSeconds'),annotations=template.get('metadata',{}).get('annotations'),
        environment={name:row.get('value','<secret reference>') for name,row in env.items() if name in allowed},
        secret_references={name:row['valueFrom'] for name,row in env.items() if 'valueFrom' in row},
        sql=dict(name=sql.get('name'),state=sql.get('state'),connection_name=sql.get('connectionName'),
                 backup=sql.get('settings',{}).get('backupConfiguration')),
        recent_backups=[{k:backup.get(k) for k in ('id','status','type','endTime')} for backup in backups])
    RECORD.mkdir(parents=True,exist_ok=True)
    (RECORD/'inventory.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


@contextmanager
def database_connection():
    live = service()
    env = {row['name']:row for row in live['spec']['template']['spec']['containers'][0].get('env',[])}
    database = env.get('MYSQL_DB',{}).get('value')
    username = env.get('MYSQL_USER',{}).get('value')
    if database != 'global_it_erp_production' or not username:
        raise RuntimeError('Production database identity does not match the reviewed target.')
    reference = env.get('MYSQL_PASSWORD',{}).get('valueFrom',{}).get('secretKeyRef')
    if not reference:
        raise RuntimeError('Production must provide a Secret Manager MYSQL_PASSWORD reference.')
    password = gcloud('secrets','versions','access',reference['key'],
                      '--secret='+reference['name'],'--project='+PROJECT).stdout.decode('utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    RECORD.mkdir(parents=True,exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
    with (RECORD/'sql-proxy.log').open('ab') as log:
        proxy = subprocess.Popen([str(ROOT/'cloud-sql-proxy.exe'),'--gcloud-auth','--address=127.0.0.1',
            '--port='+str(port),PROJECT+':'+REGION+':'+INSTANCE],stdout=log,stderr=log,creationflags=flags)
        conn = None
        try:
            deadline = time.monotonic()+30
            while True:
                try:
                    conn = pymysql.connect(host='127.0.0.1',port=port,user=username,password=password,
                        database=database,connect_timeout=3,read_timeout=15,charset='utf8mb4',
                        cursorclass=pymysql.cursors.DictCursor,autocommit=False)
                    break
                except pymysql.Error:
                    if proxy.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError('Cloud SQL proxy connection failed. Inspect the local proxy log; no credentials were printed.')
                    time.sleep(0.25)
            yield conn
        finally:
            if conn:
                conn.close()
            proxy.terminate()
            proxy.wait(timeout=10)


def schema_preflight():
    with database_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SELECT DATABASE() AS database_name')
            report = cursor.fetchone()
            cursor.execute('''SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('cashfree_orders','cashfree_payment_link_orders')
                ORDER BY TABLE_NAME,ORDINAL_POSITION''')
            report['cashfree_schema'] = cursor.fetchall()
            cursor.execute("SELECT hostname,status,is_primary FROM institute_domains WHERE institute_id=1 ORDER BY is_primary DESC,id")
            report['institute_1_domains'] = cursor.fetchall()
            conn.rollback()
    RECORD.mkdir(parents=True,exist_ok=True)
    (RECORD/'schema-preflight.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


def store_secrets():
    values = dotenv_values(ROOT/'.env')
    app_id = values.get('CASHFREE_LIVE_APP_ID') or ''
    secret = values.get('CASHFREE_LIVE_SECRET_KEY') or ''
    if not app_id or app_id.upper().startswith('TEST') or not secret or 'xxxxxxxx' in secret.lower():
        raise RuntimeError('Add complete CASHFREE_LIVE_APP_ID and CASHFREE_LIVE_SECRET_KEY to .env first.')
    runtime = service()['spec']['template']['spec']['serviceAccountName']
    expected = 'attn-billing-runtime@'+PROJECT+'.iam.gserviceaccount.com'
    if runtime != expected:
        raise RuntimeError('The runtime service account differs from the reviewed production inventory.')
    stored = {}
    for variable,name,value in (
        ('CASHFREE_APP_ID','attn-billing-cashfree-live-app-id',app_id),
        ('CASHFREE_SECRET_KEY','attn-billing-cashfree-live-secret-key',secret),
    ):
        exists = gcloud('secrets','describe',name,'--project='+PROJECT,check=False)
        if exists.returncode:
            gcloud('secrets','create',name,'--project='+PROJECT,'--replication-policy=automatic',
                   '--labels=application=attnandbilling,environment=production,provider=cashfree')
        # Secret bytes go through stdin, never a process argument or plaintext temp file.
        result = gcloud('secrets','versions','add',name,'--project='+PROJECT,'--data-file=-',
                        '--format=value(name)',data=value.encode('utf-8'))
        version = result.stdout.decode().strip().rsplit('/',1)[-1]
        if not version.isdigit():
            raise RuntimeError('Secret Manager did not return a numeric version.')
        gcloud('secrets','add-iam-policy-binding',name,'--project='+PROJECT,
               '--member=serviceAccount:'+runtime,'--role=roles/secretmanager.secretAccessor')
        stored[variable] = name+':'+version
    RECORD.mkdir(parents=True,exist_ok=True)
    (RECORD/'cashfree-secret-versions.json').write_text(json.dumps(stored,indent=2),encoding='utf-8')
    print(json.dumps({'project':PROJECT,'runtime_account':runtime,'pinned_secrets':stored},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventory','schema-preflight','store-secrets'])
    arguments = parser.parse_args()
    try:
        {'inventory':inventory,'schema-preflight':schema_preflight,'store-secrets':store_secrets}[arguments.action]()
    except RuntimeError as error:
        raise SystemExit(str(error))

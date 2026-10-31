"""Disposable MySQL fixture for ERP regression tests; no configured databases are used."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pymysql
import pytest


@pytest.fixture(scope='module')
def mysql_server(tmp_path_factory):
    if os.environ.get('ERP_RUN_MYSQL_TESTS') != '1':
        pytest.skip('Set ERP_RUN_MYSQL_TESTS=1 for the disposable MySQL integration test.')
    executable = shutil.which('mysqld')
    if not executable:
        pytest.skip('mysqld is unavailable.')
    directory = tmp_path_factory.mktemp('erp-mysql-test')
    datadir = directory / 'data'
    datadir.mkdir()
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    base = [executable, '--no-defaults', f'--basedir={Path(executable).parent.parent}',
            f'--datadir={datadir}']
    initialized = subprocess.run(base + ['--initialize-insecure'], capture_output=True,
                                 timeout=60, creationflags=flags)
    assert initialized.returncode == 0, initialized.stderr.decode(errors='replace')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with (directory / 'server.log').open('wb') as log:
        process = subprocess.Popen(base + ['--bind-address=127.0.0.1', f'--port={port}',
                                          '--mysqlx=0', '--console'],
                                   stdout=log, stderr=log, creationflags=flags)
        options = dict(host='127.0.0.1', port=port, user='root', password='',
                       charset='utf8mb4', connect_timeout=2, autocommit=False)
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    admin = pymysql.connect(**options)
                    break
                except pymysql.Error:
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail((directory / 'server.log').read_text(errors='replace'))
                    time.sleep(0.25)
            admin.close()
            yield options
        finally:
            try:
                admin = pymysql.connect(**options)
                try:
                    with admin.cursor() as cursor:
                        cursor.execute('SHUTDOWN')
                finally:
                    admin.close()
                process.wait(timeout=15)
            except (pymysql.Error, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=10)

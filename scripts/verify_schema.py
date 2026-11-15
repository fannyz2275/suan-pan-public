#!/usr/bin/env python3
"""Run schema.sql in a disposable PostgreSQL cluster (pgvector required).

Example: python scripts/verify_schema.py --pg-bin /opt/homebrew/opt/postgresql@18/bin
Never connects to Supabase or an existing cluster. No TCP listener is created.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, help='directory containing initdb, pg_ctl, and psql')
    args = parser.parse_args()
    found = shutil.which('initdb')
    if args.pg_bin is None and not found:
        parser.error('Install PostgreSQL and pgvector, then provide --pg-bin.')
    binaries = args.pg_bin or Path(found).parent
    def run(name, *argv, **kwargs):
        return subprocess.run([str(binaries/name), *map(str,argv)], check=True, text=True, capture_output=True, **kwargs)
    with tempfile.TemporaryDirectory(prefix='suan-pan-schema-') as folder:
        folder = Path(folder)
        cluster = folder/'data'
        run('initdb','-D',cluster,'--auth-local=trust','--auth-host=reject','--no-locale')
        started = False
        try:
            run('pg_ctl','-D',cluster,'-l',folder/'server.log','-o',f"-h '' -k {folder} -p 55439",'start')
            started = True
            connection = ['-h',str(folder),'-p','55439','-d','postgres','-v','ON_ERROR_STOP=1']
            run('psql',*connection,'-f',ROOT/'backend/tests/schema/supabase_stub.sql',
                '-f',ROOT/'backend/supabase/schema.sql','-f',ROOT/'backend/tests/schema/verify.sql')
            run('psql',*connection,'-c','create database rollback_check')
            rollback_connection = [*connection]
            rollback_connection[5] = 'rollback_check'
            stub = (ROOT/'backend/tests/schema/supabase_stub.sql').read_text()
            stub = '\n'.join(line for line in stub.splitlines() if not line.startswith('create role '))
            run('psql',*rollback_connection,input=stub)
            sql = (ROOT/'backend/supabase/schema.sql').read_text()
            assert sql.endswith('\ncommit;\n')
            failing = sql[:-len('commit;\n')] + "do $$ begin raise exception 'synthetic rollback probe'; end $$;\ncommit;\n"
            try:
                run('psql',*rollback_connection,input=failing)
            except subprocess.CalledProcessError as exc:
                if 'synthetic rollback probe' not in exc.stderr:
                    raise
            else:
                raise AssertionError('Expected injected setup failure')
            count = run('psql',*rollback_connection,'-Atc',"select count(*) from pg_tables where schemaname='public'").stdout.strip()
            assert count == '0', 'Setup failure left partial public tables'
            print('PASS: fresh bootstrap, profile trigger, credential permissions, session RLS, and atomic rollback.')
        finally:
            if started:
                run('pg_ctl','-D',cluster,'-m','immediate','stop')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Scan tracked release contents without printing credential values.

Use --ref REF to inspect a committed tree. This is a heuristic guard, not proof
that credentials have never appeared in Git history.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    'Google API key': rb'AIza[0-9A-Za-z_-]{35}',
    'OpenRouter API key': rb'sk-or-v1-[0-9a-f]{32,}',
    'Supabase secret key': rb'sb_secret_[A-Za-z0-9_-]{20,}',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
}


def findings(path, content):
    result = [label for label, pattern in PATTERNS.items() if re.search(pattern, content)]
    name = Path(path).name
    if (name == '.env' or name.startswith('.env.') or '.env.' in name or name.endswith('.env')) and not name.endswith('.example'):
        result.append('private environment file')
    if path.startswith('.private-publication/'):
        result.append('private archive')
    if path.startswith('docs/test-reports/') and name.lower().endswith(('.png', '.jpg', '.jpeg')):
        result.append('unreviewed report screenshot; use synthetic fixtures instead')
    for token in re.findall(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', content):
        try:
            body = token.split(b'.')[1]
            payload = json.loads(base64.urlsafe_b64decode(body + b'=' * (-len(body) % 4)))
            if payload.get('role') == 'service_role':
                result.append('Supabase service-role token')
        except (ValueError, UnicodeError):
            continue
    return sorted(set(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', help='scan a committed tree instead of tracked working files')
    args = parser.parse_args()
    command = ['git', 'ls-tree', '-rz', '--name-only', args.ref] if args.ref else ['git', 'ls-files', '-z']
    paths = subprocess.check_output(command).decode().split('\0')
    failed = False
    for path in filter(None, paths):
        if args.ref:
            content = subprocess.check_output(['git', 'show', f'{args.ref}:{path}'])
        else:
            if not Path(path).is_file():
                continue
            content = Path(path).read_bytes()
        for finding in findings(path, content):
            print(f'{path}: {finding}')
            failed = True
    if not failed:
        print('Tracked publication-content checks passed. Historical exposure requires separate cleanup.')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())

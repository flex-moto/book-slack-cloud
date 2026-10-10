#!/usr/bin/env python3
"""Authorize D-Lab once and store its token directly in GitHub Actions Secrets."""
import argparse
import base64
import hashlib
import json
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ORIGIN = 'https://mcp.daigovideolab.jp'
RESOURCE = ORIGIN + '/mcp'


def request_json(url, data, form=False):
    raw = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    request = urllib.request.Request(url, data=raw, headers={
        'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='flex-moto/book-slack-cloud')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    callback = f'http://127.0.0.1:{args.port}/callback'
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(32)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Authorization codes must not appear in logs.

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path != '/callback' or not secrets.compare_digest(query.get('state', [''])[0], state):
                self.send_error(400, 'Invalid callback')
                return
            result.update(query)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('認証応答を受け取りました。Codexで設定結果を確認してください。'.encode())

    with HTTPServer(('127.0.0.1', args.port), Handler) as server:
        client = request_json(ORIGIN + '/register', {
            'client_name': 'D-Lab news on GitHub Actions', 'redirect_uris': [callback],
            'grant_types': ['authorization_code'], 'response_types': ['code'],
            'token_endpoint_auth_method': 'none'})
        url = ORIGIN + '/authorize?' + urllib.parse.urlencode({
            'client_id': client['client_id'], 'redirect_uri': callback, 'response_type': 'code',
            'scope': 'mcp:knowledge.search', 'state': state, 'resource': RESOURCE,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})
        print('Open this URL and sign in to D-Lab:', flush=True)
        print(url, flush=True)
        server.timeout = 1
        deadline = time.monotonic() + 1800
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result.get('code'):
        raise SystemExit('Login was cancelled or timed out. No GitHub secret changed.')
    token = request_json(ORIGIN + '/token', {
        'grant_type': 'authorization_code', 'code': result['code'][0],
        'client_id': client['client_id'], 'redirect_uri': callback,
        'code_verifier': verifier, 'resource': RESOURCE}, form=True)
    access_token = token.get('access_token')
    if not access_token:
        raise SystemExit('No access token returned. No GitHub secret changed.')
    subprocess.run(['gh', 'secret', 'set', 'DLAB_MCP_TOKEN', '--repo', args.repo],
                   input=access_token, text=True, check=True)
    if token.get('expires_in'):
        from datetime import datetime, timedelta, timezone
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=int(token['expires_in']))).isoformat()
        subprocess.run(['gh', 'variable', 'set', 'DLAB_MCP_TOKEN_EXPIRES_AT', '--repo', args.repo,
                        '--body', expiry], check=True)
        print('Token expiry:', expiry)
    print('DLAB_MCP_TOKEN saved in GitHub Actions Secrets. Token was not printed or saved locally.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not echo HTTP response bodies, tokens, callback codes, or request data.
        raise SystemExit(f'Cloud authorization failed ({type(exc).__name__}). Retry login.') from None

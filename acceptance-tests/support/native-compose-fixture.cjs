// Entirely local disposable applications with a real database, API, website and
// first-user initialization. Full-stack/configuration cases retain Postgres;
// operation/isolation cases can use persistent SQLite. No live demo credentials.
const PYTHON = 'python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88';
const HELPER_PYTHON = 'python:3.14-alpine3.22@sha256:6b91e66ab2a880ce9ca5a1b91c70f45963ff71ff68268df056336e1a657d5efd';
const POSTGRES = 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea';
const ACCOUNT = Object.freeze({ email: 'preview@example.invalid', password: 'disposable-preview-password' });

// A tiny PostgreSQL simple-query client keeps the fixture offline-buildable.
// Trust authentication is confined to this disposable database; the application's
// login still checks its initialized user row. This is not a production client.
const databaseClient = String.raw`import socket, struct

def query(sql):
    with socket.create_connection(('db', 5432), timeout=5) as connection:
        def read(size):
            value = b''
            while len(value) < size:
                chunk = connection.recv(size - len(value))
                if not chunk:
                    raise RuntimeError('database disconnected')
                value += chunk
            return value
        def message():
            kind = read(1)
            length = struct.unpack('!I', read(4))[0]
            return kind, read(length - 4)
        params = b'user\0postgres\0database\0preview\0\0'
        connection.sendall(struct.pack('!II', len(params) + 8, 196608) + params)
        while True:
            kind, body = message()
            if kind == b'E':
                raise RuntimeError('database startup failed')
            if kind == b'Z':
                break
        sql = sql.encode() + b'\0'
        connection.sendall(b'Q' + struct.pack('!I', len(sql) + 4) + sql)
        rows = []
        while True:
            kind, body = message()
            if kind == b'E':
                raise RuntimeError('database query failed')
            if kind == b'D':
                size = struct.unpack('!I', body[2:6])[0]
                rows.append(body[6:6 + size].decode())
            if kind == b'Z':
                return rows

def quoted(value):
    return "'" + value.replace("'", "''") + "'"
`;

const sqliteClient = String.raw`import os, sqlite3

def query(sql):
    with sqlite3.connect(os.environ.get('PREVIEW_DATABASE_PATH', '/data/preview.sqlite3'), timeout=5) as connection:
        return [str(row[0]) for row in connection.execute(sql).fetchall()]

def quoted(value):
    return "'" + value.replace("'", "''") + "'"
`;

const api = String.raw`from http.server import BaseHTTPRequestHandler, HTTPServer
from db import query, quoted
import json

class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    def do_GET(self):
        if self.path == '/health':
            query('SELECT 1')
            return self.respond(200, {'ready': True})
        if self.headers.get('Authorization') != 'Bearer fixture-token':
            return self.respond(401, {'error': 'login required'})
        self.respond(200, json.loads(query("SELECT COALESCE(json_agg(name)::text, '[]') FROM items")[0]))
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/login':
            rows = query('SELECT count(*) FROM users WHERE email = ' + quoted(value['email']) + ' AND password = ' + quoted(value['password']))
            if rows == ['1']:
                return self.respond(200, {'token': 'fixture-token'})
            return self.respond(401, {'error': 'invalid credentials'})
        if self.path == '/items' and self.headers.get('Authorization') == 'Bearer fixture-token':
            query('INSERT INTO items(name) VALUES (' + quoted(value['name']) + ')')
            return self.respond(201, {'saved': value['name']})
        self.respond(403, {'error': 'forbidden'})
HTTPServer(('0.0.0.0', 8766), Handler).serve_forever()
`;

const website = String.raw`from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/'):
            return self.proxy()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(Path('/app/index.html').read_bytes())
    def do_POST(self):
        self.proxy()
    def proxy(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'content-length')}
        try:
            response = urlopen(Request('http://api:8766' + self.path[4:], data=body, headers=headers), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            self.send_response(response.status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.read())
HTTPServer(('0.0.0.0', 8765), Handler).serve_forever()
`;

const html = `<!doctype html><html><body><h1>Native preview application</h1>
<form id="login"><label>Email<input id="email" type="email" required></label><label>Password<input id="password" type="password" required></label><button>Log in</button></form>
<form id="create" hidden><label>Item<input id="item" required></label><button>Create item</button></form><pre id="items"></pre><p role="status"></p>
<script>
let token;
const status = document.querySelector('[role="status"]');
document.querySelector('#login').onsubmit = async event => {
  event.preventDefault();
  const response = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email:document.querySelector('#email').value,password:document.querySelector('#password').value})});
  const value = await response.json();
  if (!response.ok) {status.textContent = value.error; return;}
  token = value.token; document.querySelector('#create').hidden = false; status.textContent = 'Logged in';
};
document.querySelector('#create').onsubmit = async event => {
  event.preventDefault();
  const headers = {'Content-Type':'application/json', Authorization:'Bearer '+token};
  const response = await fetch('/api/items', {method:'POST', headers, body:JSON.stringify({name:document.querySelector('#item').value})});
  if (!response.ok) {status.textContent = 'Save failed'; return;}
  document.querySelector('#items').textContent = await (await fetch('/api/items', {headers})).text();
  status.textContent = 'Item saved';
};
</script></body></html>`;

function initializationFixture(script, { mode = 'normal', markup = '' } = {}) {
  const before = "import os, sys, time\nprint('acceptance initialization entered', flush=True)\n";
  const live = "for index in range(48):\n    print(f'acceptance stdout tick {index:03d}', flush=True)\n    print(f'acceptance stderr tick {index:03d}', file=sys.stderr, flush=True)\n    time.sleep(0.5)\n";
  const variants = {
    normal: before + script,
    live: before + live + script,
    failed: before + "print('acceptance initialization diagnostic ' + os.environ['PREVIEW_EXECUTION_SECRET'], file=sys.stderr, flush=True)\nsys.exit(17)\n",
    retention: before + "for index in range(1024):\n    print('retention output ' + str(index) + ' ' + 'x' * 2048, flush=True)\nprint('acceptance retained final diagnostic', file=sys.stderr, flush=True)\nsys.exit(23)\n",
    secret: before + "secret = os.environ['PREVIEW_EXECUTION_SECRET']\ncut = len(secret) // 2\nsys.stdout.write('split secret: ' + secret[:cut]); sys.stdout.flush()\ntime.sleep(0.5)\nsys.stdout.write(secret[cut:] + '\\n'); sys.stdout.flush()\nsys.exit(29)\n",
    markup: before + `print(${JSON.stringify(`\u001b[31m${markup}\u001b[0m\u001b]52;c;ignored\u0007`)}, flush=True)\nsys.exit(31)\n`,
    missing: before + script,
  };
  if (!Object.hasOwn(variants, mode)) throw new Error(`Unknown real-project fixture mode: ${mode}`);
  return variants[mode];
}

function nativeComposeFixture({ linked = false, failInitialization = false, build = true, buildApi = build, watch = build, prebuiltWatch = false,
  database = 'postgres', pythonImage = database === 'postgres' ? PYTHON : HELPER_PYTHON } = {}) {
  if (!['postgres', 'sqlite'].includes(database)) throw new Error('Unsupported fixture database');
  if (watch && !build) throw new Error('Watch fixtures require a genuine website build context');
  const postgres = database === 'postgres';
  if (prebuiltWatch && (!watch || !build || buildApi)) throw new Error('Invalid prebuilt watch fixture');
  const buildImage = postgres && !prebuiltWatch ? PYTHON : HELPER_PYTHON;
  // Most API/UI/isolation scenarios need a running real application, not a
  // fresh BuildKit instance. Confined checkout binds avoid COPY-only builds;
  // explicit full-stack/configuration and build-resource cases retain builds.
  const startup = prebuiltWatch ? 'docker compose up --watch' : watch ? 'docker compose watch' : 'docker compose up';
  const instructions = '# Full-stack Docker development\n\n'
    + 'Initialize the database and first account:\n\n```sh\ndocker compose run --rm api python init.py\n```\n\n'
    + `Start the complete application${watch ? ' and keep source synchronization running' : ''}:\n\n\`\`\`sh\n${startup}\n\`\`\`\n\n`
    + 'Application: http://localhost:8765/ . The website proxies its required API requests.\n';
  return {
    'README.md': linked
      ? '# Preview fixture\n\nFollow [Docker development](docs/development.md#full-stack-docker-development).\n\n## Alternative host-local development\nRun `python site/server.py` and `python api/server.py` only when not using Docker.\n'
      : instructions,
    ...(linked ? { 'docs/development.md': instructions } : {}),
    '.env': `FIRST_EMAIL=${ACCOUNT.email}\nFIRST_PASSWORD=${ACCOUNT.password}\n${postgres ? '' : 'PREVIEW_DATABASE_PATH=/data/configured-preview.sqlite3\n'}`,
    'compose.yml': `services:
${postgres ? `  db:
    image: ${POSTGRES}
    container_name: fixed-preview-database
    environment:
      POSTGRES_DB: preview
      POSTGRES_HOST_AUTH_METHOD: trust
    volumes: [database:/var/lib/postgresql/data]
    healthcheck:
      test: [CMD-SHELL, pg_isready -U postgres -d preview]
      interval: 1s
      timeout: 1s
      retries: 30
` : ''}  api:
    ${buildApi ? 'build: ./api' : `image: ${pythonImage}\n    working_dir: /app\n    volumes: ['./api:/app:ro'${postgres ? '' : ', database:/data'}]`}
${buildApi && !postgres ? '    volumes: [database:/data]\n' : ''}    container_name: fixed-preview-api
    env_file: .env
    command: [python, -u, server.py]
${postgres ? `    depends_on:
      db:
        condition: service_healthy
` : ''}  website:
    ${prebuiltWatch ? `build: ./site\n    image: ${pythonImage}\n    pull_policy: never\n    working_dir: /app\n    volumes: ['./site:/app:rw']` : build ? 'build: ./site' : `image: ${pythonImage}\n    working_dir: /app\n    volumes: ['./site:/app:ro']`}
    container_name: fixed-preview-website
    command: [python, -u, server.py]
    depends_on: [api]
  mail:
    image: ${pythonImage}
    command: [python, -m, http.server, '8025']
  admin:
    image: ${pythonImage}
    command: [python, -m, http.server, '8080']
volumes:
  database:
`,
    'compose.override.yml': `services:
  website:
    ports: ['8765:8765']
${watch ? `    develop:
      watch:
        - action: sync
          path: ${prebuiltWatch ? './watched-site' : './site'}
          target: ${prebuiltWatch ? '/tmp/watched-inputs' : '/app'}
          initial_sync: true
          ignore: [Dockerfile]
` : ''}  api:
    ports: ['8766:8766']
${postgres ? `  db:
    ports: ['15432:5432']
` : ''}  mail:
    ports: ['8025:8025']
  admin:
    ports: ['8080:8080']
`,
    'api/Dockerfile': `FROM ${buildImage}\nWORKDIR /app\nCOPY . .\n`,
    'site/Dockerfile': `FROM ${buildImage}\nWORKDIR /app\nCOPY . .\n`,
    'api/db.py': postgres ? databaseClient : sqliteClient,
    'api/server.py': postgres ? api : api.replace('json_agg(name)::text', 'json_group_array(name)'),
    'api/init.py': failInitialization
      ? 'import sys\nprint("fixture initialization failed", file=sys.stderr, flush=True)\nsys.exit(17)\n'
      : String.raw`from db import query, quoted
import os
query('CREATE TABLE IF NOT EXISTS users(email text primary key, password text)')
query('CREATE TABLE IF NOT EXISTS items(name text)')
query('INSERT INTO users VALUES (' + quoted(os.environ['FIRST_EMAIL']) + ', ' + quoted(os.environ['FIRST_PASSWORD']) + ') ON CONFLICT DO NOTHING')
print('first user initialized', flush=True)
`,
    'site/server.py': prebuiltWatch ? website.replace("Path('/app/index.html')", "Path('/tmp/watched-inputs/index.html')") : website,
    'site/index.html': html,
    ...(prebuiltWatch ? { 'watched-site/index.html': html } : {}),
  };
}

module.exports = { ACCOUNT, HELPER_PYTHON, PYTHON, initializationFixture, nativeComposeFixture };

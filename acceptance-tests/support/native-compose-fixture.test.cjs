'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { HELPER_PYTHON, initializationFixture, nativeComposeFixture } = require('./native-compose-fixture.cjs');

test('lean fixtures address the exact immutable public helper seeded by production', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const runtime = fs.readFileSync(path.resolve(__dirname, '../../backend/app/services/preview_native_runtime.py'), 'utf8');
  assert.ok(runtime.includes(`HELPER_IMAGE = '${HELPER_PYTHON}'`));
});

test('ready-state fixtures keep real Postgres, five services and initialization without redundant image builds', () => {
  const full = nativeComposeFixture();
  const ready = nativeComposeFixture({ build: false });
  for (const name of ['db', 'api', 'website', 'mail', 'admin']) {
    assert.ok(ready['compose.yml'].includes(`  ${name}:\n`));
  }
  assert.match(ready['compose.yml'], /image: postgres:16-alpine@sha256:/);
  assert.match(ready['compose.yml'], /condition: service_healthy/);
  assert.match(ready['compose.yml'], /volumes: \[database:\/var\/lib\/postgresql\/data\]/);
  assert.doesNotMatch(ready['compose.yml'], /build:/);
  assert.match(ready['compose.yml'], /volumes: \['\.\/api:\/app:ro'\]/);
  assert.match(ready['compose.yml'], /volumes: \['\.\/site:\/app:ro'\]/);
  assert.match(ready['README.md'], /docker compose run --rm api python init\.py/);
  assert.match(ready['README.md'], /docker compose up\n/);
  assert.doesNotMatch(ready['README.md'], /docker compose watch/);
  for (const name of ['api/db.py', 'api/server.py', 'api/init.py', 'site/server.py', 'site/index.html', '.env']) {
    assert.equal(ready[name], full[name], `${name} must remain the real full-stack application`);
  }
});

test('operation and isolation fixtures use a real persistent SQLite database without starting an unrelated Postgres service', () => {
  const image = `sha256:${'a'.repeat(64)}`;
  const files = nativeComposeFixture({ build: false, database: 'sqlite', pythonImage: image });
  assert.doesNotMatch(files['compose.yml'], /image: postgres|  db:|build:/);
  assert.doesNotMatch(files['compose.override.yml'], /15432|  db:/);
  assert.match(files['compose.yml'], /database:\/data/);
  assert.match(files['api/db.py'], /sqlite3\.connect\(os\.environ\.get\('PREVIEW_DATABASE_PATH'/);
  assert.match(files['.env'], /PREVIEW_DATABASE_PATH=\/data\/configured-preview\.sqlite3/);
  assert.match(files['api/server.py'], /json_group_array\(name\)/);
  assert.match(files['api/init.py'], /CREATE TABLE IF NOT EXISTS users/);
  assert.match(files['api/init.py'], /CREATE TABLE IF NOT EXISTS items/);
  assert.ok(files['compose.yml'].includes(`image: ${image}`));
  assert.match(files['site/server.py'], /http:\/\/api:8766/);
  assert.match(files['site/index.html'], /\/api\/login/);
  assert.match(files['site/index.html'], /\/api\/items/);
});

test('representative build/watch fixture retains both builds, source synchronization and native configuration', () => {
  const full = nativeComposeFixture({ linked: true });
  assert.match(full['compose.yml'], /build: \.\/api/);
  assert.match(full['compose.yml'], /build: \.\/site/);
  assert.match(full['compose.override.yml'], /watch:\n\s+- action: sync/);
  assert.match(full['docs/development.md'], /docker compose watch/);
  assert.match(full['README.md'], /docs\/development\.md/);
  for (const port of ['8765', '8766', '15432', '8025', '8080']) assert.ok(full['compose.override.yml'].includes(port));
});

test('lightweight watch fixtures retain a genuine build and cannot silently watch an image-only service', () => {
  const files = nativeComposeFixture({ build: true, buildApi: false, database: 'sqlite' });
  assert.match(files['compose.yml'], /api:\n\s+image:/);
  assert.match(files['compose.yml'], /website:\n\s+build: \.\/site/);
  assert.match(files['site/Dockerfile'], /FROM python:3\.14-alpine3\.22@sha256:/);
  assert.match(files['compose.override.yml'], /path: \.\/site\n\s+target: \/app/);
  assert.throws(() => nativeComposeFixture({ build: false, watch: true }), /genuine website build/);
});

test('prebuilt watch uses genuine watched application input with initial sync rather than a bind-only false positive', () => {
  const files = nativeComposeFixture({ build: true, buildApi: false, watch: true, prebuiltWatch: true, database: 'sqlite' });
  assert.match(files['README.md'], /docker compose up --watch/);
  assert.match(files['compose.yml'], /pull_policy: never/);
  assert.match(files['compose.override.yml'], /path: \.\/watched-site/);
  assert.match(files['compose.override.yml'], /initial_sync: true/);
  assert.match(files['site/server.py'], /Path\('\/tmp\/watched-inputs\/index\.html'\)/);
  assert.equal(files['watched-site/index.html'], files['site/index.html']);
});

test('ordinary initialization has no artificial wait; live-output fixtures retain their observation window', () => {
  const body = 'print("real database initialization")\n';
  const normal = initializationFixture(body);
  assert.match(normal, /acceptance initialization entered/);
  assert.ok(normal.endsWith(body));
  assert.doesNotMatch(normal, /time\.sleep|stdout tick/);
  const live = initializationFixture(body, { mode: 'live' });
  assert.match(live, /range\(48\)/);
  assert.match(live, /time\.sleep\(0\.5\)/);
  assert.match(live, /acceptance stdout tick/);
  assert.match(live, /acceptance stderr tick/);
  assert.ok(live.endsWith(body));
});

test('routing-only Compose preparation avoids builds while the dependency-build default remains available', async () => {
  const { PreviewWorkloadPage } = require('./pages/preview-workload-page.js');
  const files = new Map();
  const page = new PreviewWorkloadPage({ apiClient: {
    withWorkspaceFileBatch: async (_chat, callback) => callback(),
    editWorkspaceFile: async (_chat, name, content) => files.set(name, content),
  } });
  await page.prepareRoutingCompose('owned-chat', 'routing marker');
  assert.doesNotMatch(files.get('compose.yml'), /build:/);
  assert.match(files.get('compose.yml'), /\.\/site:\/workspace:ro/);
  assert.match(files.get('compose.yml'), /\.\/api:\/workspace:ro/);
  assert.match(files.get('compose.yml'), /user: '65534'/);
  assert.match(files.get('site/server.py'), /routing marker/);
  await page.prepareCompose('owned-chat');
  assert.match(files.get('compose.yml'), /build:\n\s+context: site/);
  assert.match(files.get('compose.yml'), /build:\n\s+context: api/);
});

test('page preparation explicitly retains build/watch and delayed live fixtures only where required', async () => {
  const { NativePreviewPage } = require('./pages/native-preview-page.js');
  const page = new NativePreviewPage({ previewWorkloadPage: {} });
  const prepared = [];
  page.prepare = async options => { prepared.push(options); };
  page.checkoutFiles = async () => ({});
  await page.prepareNative();
  await page.prepareNative('watch');
  await page.prepareNative('full');
  await page.prepareNative('live');
  assert.deepEqual(prepared, [
    { mode: 'normal', build: false, buildApi: false, watch: false, prebuiltWatch: false, database: 'sqlite', ui: false },
    { mode: 'normal', build: true, buildApi: false, watch: true, prebuiltWatch: true, database: 'sqlite', ui: false },
    { mode: 'normal', build: true, buildApi: false, watch: true, prebuiltWatch: true, database: 'postgres', ui: false },
    { mode: 'live', build: false, buildApi: false, watch: false, prebuiltWatch: false, database: 'sqlite', ui: false },
  ]);
});

test('failure, retention, split-secret and untrusted-output fixtures still emit their actual diagnostics', () => {
  const body = 'database_initialization()\n';
  for (const [mode, code] of [['failed', 17], ['retention', 23], ['secret', 29], ['markup', 31]]) {
    const script = initializationFixture(body, { mode, markup: '<script>untrusted()</script>' });
    assert.match(script, new RegExp(`sys\\.exit\\(${code}\\)`));
    assert.ok(!script.includes(body), 'Negative fixture must not run successful database initialization');
  }
  assert.match(initializationFixture(body, { mode: 'secret' }), /time\.sleep\(0\.5\)/);
  assert.match(initializationFixture(body, { mode: 'retention' }), /range\(1024\)/);
  assert.match(initializationFixture(body, { mode: 'markup', markup: '<script>untrusted()</script>' }), /<script>untrusted\(\)<\/script>/);
  assert.throws(() => initializationFixture(body, { mode: 'unknown' }), /Unknown/);
});

'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { cacheUpstream, preparePreviewCache } = require('./preview-cache.cjs');
const repoRoot = path.resolve(__dirname, '../..');

test('host loopback mirrors map only to the trusted helper host address', () => {
  for (const host of ['localhost', '127.0.0.1', '[::1]']) {
    assert.equal(cacheUpstream(`http://${host}:5001/`), 'http://host.docker.internal:5001');
  }
  assert.equal(cacheUpstream('https://cache.example.invalid:5443'), 'https://cache.example.invalid:5443');
});

test('cache configuration cannot embed credentials or arbitrary URL components', () => {
  for (const value of ['file:///tmp/cache', 'http://user:password@cache.invalid',
    'http://cache.invalid/other', 'http://cache.invalid/?token=secret', 'http://cache.invalid/#fragment']) {
    assert.throws(() => cacheUpstream(value), /credential-free HTTP/);
  }
});

test('mirror detection can be explicitly overridden or disabled', () => {
  assert.equal(preparePreviewCache({ repoRoot, mirrors: [] }), undefined);
  assert.equal(preparePreviewCache({ repoRoot, mirrors: ['http://127.0.0.1:5001'], override: '' }), undefined);
  const cache = preparePreviewCache({ repoRoot, mirrors: ['http://127.0.0.1:5001'], override: 'http://cache.invalid:5000' });
  try { assert.equal(cache.upstream, 'http://cache.invalid:5000'); } finally { cache.cleanup(); }
});

test('acceptance overlays extend current production definitions without changing them', () => {
  const originalController = fs.readFileSync(path.join(repoRoot, 'backend/preview.Dockerfile'), 'utf8');
  const originalNative = fs.readFileSync(path.join(repoRoot, 'backend/preview-native.Dockerfile'), 'utf8');
  const cache = preparePreviewCache({ repoRoot, mirrors: ['http://127.0.0.1:5001/'] });
  try {
    assert.ok(fs.readFileSync(cache.controllerDockerfile, 'utf8').startsWith(originalController));
    assert.ok(fs.readFileSync(cache.nativeDockerfile, 'utf8').startsWith(originalNative));
    assert.match(fs.readFileSync(cache.controllerDockerfile, 'utf8'), /preview_public_registry_proxy/);
    assert.match(fs.readFileSync(cache.nativeDockerfile, 'utf8'), /XDG_CONFIG_HOME=\/opt\/acceptance-config/);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(__dirname, 'preview-cache-daemon.json'), 'utf8')),
      { 'registry-mirrors': [cache.mirror] });
    assert.equal(fs.readFileSync(path.join(repoRoot, 'backend/preview.Dockerfile'), 'utf8'), originalController);
    assert.equal(fs.readFileSync(path.join(repoRoot, 'backend/preview-native.Dockerfile'), 'utf8'), originalNative);
  } finally { cache.cleanup(); }
  assert.equal(fs.existsSync(cache.directory), false);
});

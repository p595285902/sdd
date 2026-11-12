'use strict';

// Acceptance-only image overlays. Production Dockerfiles and runtime settings
// remain untouched; only the trusted acquisition helper can reach this cache.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const MIRROR = 'http://acceptance-cache.invalid';

function cacheUpstream(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.search || url.hash || url.pathname !== '/') {
    throw new Error('Acceptance Docker mirror must be a credential-free HTTP(S) registry origin');
  }
  // The host daemon's loopback is not a container's loopback. Docker Desktop
  // and Rancher Desktop expose the host through this trusted-helper address.
  if (['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
    url.hostname = 'host.docker.internal';
  }
  return url.origin;
}

function preparePreviewCache({ repoRoot, mirrors, override, temporaryRoot = os.tmpdir() }) {
  const mirror = override === undefined ? mirrors[0] : override;
  if (!mirror) return undefined;
  const upstream = cacheUpstream(mirror);
  const directory = fs.mkdtempSync(path.join(temporaryRoot, 'sdd-acceptance-cache-'));
  try {
    const controllerDockerfile = path.join(directory, 'controller.Dockerfile');
    const nativeDockerfile = path.join(directory, 'native.Dockerfile');
    fs.writeFileSync(controllerDockerfile,
      fs.readFileSync(path.join(repoRoot, 'backend/preview.Dockerfile'), 'utf8') + '\n' +
      'RUN mv /controller/preview_registry_proxy.py /controller/preview_public_registry_proxy.py\n' +
      'COPY acceptance-tests/support/preview-cache-proxy.py /controller/preview_registry_proxy.py\n' +
      `RUN ${JSON.stringify(['python', '-c', "from pathlib import Path; import sys; p=Path('/controller/acceptance-cache-upstream'); p.write_text(sys.argv[1]); p.chmod(0o600)", upstream])}\n`);
    fs.writeFileSync(nativeDockerfile,
      fs.readFileSync(path.join(repoRoot, 'backend/preview-native.Dockerfile'), 'utf8') + '\n' +
      'ENV XDG_CONFIG_HOME=/opt/acceptance-config\n' +
      'COPY acceptance-tests/support/preview-cache-daemon.json /opt/acceptance-config/docker/daemon.json\n');
    return { upstream, mirror: MIRROR, directory, controllerDockerfile, nativeDockerfile,
      cleanup() { fs.rmSync(directory, { recursive: true, force: true }); } };
  } catch (error) {
    fs.rmSync(directory, { recursive: true, force: true });
    throw error;
  }
}

module.exports = { MIRROR, cacheUpstream, preparePreviewCache };

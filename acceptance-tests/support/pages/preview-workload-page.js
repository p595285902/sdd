const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { runBackendPython } = require('../../features/support/app-lifecycle.js');

const startScript = `
import sys
import uuid
from app.core.config import settings
from app.services.develop_preview_runtime import PreviewController

controller = PreviewController(root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090")
chat_id = uuid.UUID(sys.argv[1])
started = controller.start(chat_id)
assert started["state"] == "running"
assert controller.status(chat_id) == started
`;

class PreviewWorkloadPage {
  constructor(world) {
    this.world = world;
    this.chatIds = [];
  }

  docker(...args) {
    return execFileSync('docker', args, { encoding: 'utf8' }).trim();
  }

  containerIds(chatId) {
    const project = this.world.applicationState.projectName;
    const output = this.docker('ps', '--filter', `label=sdd.preview.chat-id=${chatId}`,
      '--filter', `label=sdd.preview.project=${project}`, '--format', '{{.ID}}');
    return output ? output.split('\n') : [];
  }

  async start(chatId) {
    this.chatIds.push(chatId);
    await runBackendPython(startScript, chatId);
    const ids = this.containerIds(chatId);
    assert.equal(ids.length, 1);
    return JSON.parse(this.docker('inspect', ids[0]))[0];
  }

  canRead(container, filename) {
    return this.docker('exec', container.Id, 'test', '-f', `/workspace/${filename}`) === '';
  }

  cannotRead(container, filename) {
    assert.throws(() => this.docker('exec', container.Id, 'test', '-e', `/workspace/${filename}`));
    assert.throws(() => this.docker('exec', container.Id, 'test', '-e', `/workspace/../${filename}`));
  }

  expectOnlyCheckout(container, chatId) {
    assert.equal(container.HostConfig.Mounts.length, 1);
    assert.equal(container.HostConfig.Mounts[0].Type, 'volume');
    assert.equal(container.HostConfig.Mounts[0].VolumeOptions.Subpath, chatId);
    assert.equal(container.Mounts[0].Destination, '/workspace');
    assert.equal(container.Mounts[0].RW, false);
  }

  expectSandbox(container) {
    const host = container.HostConfig;
    assert.equal(host.Memory, 268435456);
    assert.equal(host.NanoCpus, 1000000000);
    assert.equal(host.PidsLimit, 64);
    assert.equal(host.Privileged, false);
    assert.equal(host.ReadonlyRootfs, true);
    assert.deepEqual(host.CapDrop, ['ALL']);
    assert.ok(host.SecurityOpt.includes('no-new-privileges:true'));
    assert.equal(host.NetworkMode, 'none');
    assert.deepEqual(host.PortBindings, {});
    const environmentNames = container.Config.Env.map((entry) => entry.split('=')[0]);
    assert.deepEqual(environmentNames.sort(),
      ['HOME', 'PATH', 'PYTHON_SHA256', 'PYTHON_VERSION'].sort());
    assert.equal(container.Config.User, '65534:65534');
    assert.equal(Object.keys(container.Config.ExposedPorts || {}).length, 0);
    assert.equal((host.Binds || []).length, 0);
  }

  stopAll() {
    for (const chatId of this.chatIds) {
      for (const id of this.containerIds(chatId)) {
        this.docker('stop', id);
      }
    }
  }
}

module.exports = { PreviewWorkloadPage };
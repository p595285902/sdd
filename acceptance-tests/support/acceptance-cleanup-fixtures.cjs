'use strict';

// Fixed, bounded fixtures in an already owned invocation. No endpoint accepts
// scripts, paths, database selectors, or fault instructions from a client.
const { randomUUID } = require('node:crypto');
const lifecycle = require('../features/support/app-lifecycle.js');

async function createFilesystemCleanupFault() {
  const name = `cleanup-depth-${randomUUID()}`;
  const limits = JSON.parse(await lifecycle.backendPythonOutput(`
import json, os, resource, sys
from app.core.config import settings
from app.services.acceptance_reset import OWNER_FILE
name, run = sys.argv[1:]
assert settings.DEVELOP_ACCEPTANCE_MODE and settings.DEVELOP_ACCEPTANCE_RESET_ENABLED
assert settings.ACCEPTANCE_RUN_ID == run
for root in (settings.DEVELOP_WORKSPACE_ROOT, settings.ACCEPTANCE_AGENT_ROOT):
    assert not root.is_symlink()
    assert json.loads((root / OWNER_FILE).read_text()) == {'run_id': run}
assert name.startswith('cleanup-depth-') and '/' not in name
(settings.DEVELOP_WORKSPACE_ROOT / name).write_text('removed before the agent-storage failure')
root = settings.ACCEPTANCE_AGENT_ROOT / name
root.mkdir()
fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    # Python 3.14 rmtree is iterative but retains ancestor descriptors. A real
    # process-local descriptor budget makes this bounded tree fail to clean.
    for _ in range(320):
        os.mkdir('d', dir_fd=fd)
        child = os.open('d', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = child
finally:
    os.close(fd)
# PID 1 is this owned backend's single FastAPI process, not a host process.
assert b'fastapi' in open('/proc/1/cmdline', 'rb').read()
limits = resource.prlimit(1, resource.RLIMIT_NOFILE)
assert limits[0] > 128 and limits[1] >= limits[0]
resource.prlimit(1, resource.RLIMIT_NOFILE, (128, limits[1]))
print(json.dumps(limits))
`, name, lifecycle.state.projectName));
  return { name, limits };
}

async function inspectFilesystemCleanupFault({ name }) {
  return JSON.parse(await lifecycle.backendPythonOutput(`
import json, sys
from app.core.config import settings
name = sys.argv[1]
assert name.startswith('cleanup-depth-') and '/' not in name
print(json.dumps({'workspace_removed': not (settings.DEVELOP_WORKSPACE_ROOT / name).exists(),
                 'agent_remains': (settings.ACCEPTANCE_AGENT_ROOT / name).is_dir()}))
`, name));
}

async function repairFilesystemCleanupFault({ name, limits }) {
  await lifecycle.backendPythonOutput(`
import os, resource, sys
from app.core.config import settings
name = sys.argv[1]
assert name.startswith('cleanup-depth-') and '/' not in name
assert b'fastapi' in open('/proc/1/cmdline', 'rb').read()
resource.prlimit(1, resource.RLIMIT_NOFILE, tuple(map(int, sys.argv[2:])))
root = settings.ACCEPTANCE_AGENT_ROOT / name
assert root.is_dir() and not root.is_symlink()
fds = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
try:
    for _ in range(320):
        fds.append(os.open('d', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
    assert os.listdir(fds[-1]) == []
    while len(fds) > 1:
        os.close(fds.pop())
        os.rmdir('d', dir_fd=fds[-1])
finally:
    for fd in fds:
        os.close(fd)
root.rmdir()
`, name, ...limits.map(String));
}

module.exports = { createFilesystemCleanupFault, inspectFilesystemCleanupFault, repairFilesystemCleanupFault };

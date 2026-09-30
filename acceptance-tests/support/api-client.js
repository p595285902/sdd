const { randomUUID } = require('node:crypto');
const { runBackendPython } = require('../features/support/app-lifecycle.js');

const seedMessagesScript = `
import sys
import uuid
from datetime import timedelta
from sqlmodel import Session
from app.core.db import engine
from app.models import DevelopmentChat, DevelopmentMessage

chat_id = uuid.UUID(sys.argv[1])
count = int(sys.argv[2])
with Session(engine) as session:
  chat = session.get(DevelopmentChat, chat_id)
  if chat is None:
    raise RuntimeError("Development Chat not found")
  for index in range(1, count + 1):
    session.add(DevelopmentMessage(
      role="assistant",
      content=f"Seeded message {index}",
      chat_id=chat.id,
      created_at=chat.created_at + timedelta(seconds=index),
    ))
  session.commit()
`;

const assertWorkspaceScript = `
import sys
import uuid
from pathlib import Path
from app.core.config import settings

workspace = Path(settings.DEVELOP_WORKSPACE_ROOT) / str(uuid.UUID(sys.argv[1]))
expected = sys.argv[2] == "present"
if workspace.exists() != expected:
  raise AssertionError(f"Unexpected workspace state: {workspace}")
if expected:
  for marker in (".git", ".opencode-initialized", ".openspec-initialized"):
    if not (workspace / marker).exists():
      raise AssertionError(f"Missing workspace marker: {marker}")
`;

const assertMessagesDeletedScript = `
import sys
import uuid
from sqlmodel import Session, select
from app.core.db import engine
from app.models import DevelopmentMessage

chat_id = uuid.UUID(sys.argv[1])
with Session(engine) as session:
  if session.exec(select(DevelopmentMessage).where(DevelopmentMessage.chat_id == chat_id)).first():
    raise AssertionError("Development Chat messages still exist")
`;

const markWorkspaceScript = `
import sys
import uuid
from pathlib import Path
from app.core.config import settings

workspace = Path(settings.DEVELOP_WORKSPACE_ROOT) / str(uuid.UUID(sys.argv[1]))
(workspace / sys.argv[2]).write_text("marked")
`;

const assertWorkspaceMarkerScript = `
import sys
import uuid
from pathlib import Path
from app.core.config import settings

workspace = Path(settings.DEVELOP_WORKSPACE_ROOT) / str(uuid.UUID(sys.argv[1]))
exists = (workspace / sys.argv[2]).exists()
if exists != (sys.argv[3] == "present"):
  raise AssertionError("Unexpected cross-workspace marker state")
`;

const assertWorkspaceContentScript = `
import sys
import uuid
from pathlib import Path
from app.core.config import settings

workspace = Path(settings.DEVELOP_WORKSPACE_ROOT) / str(uuid.UUID(sys.argv[1]))
content = (workspace / sys.argv[2]).read_text()
if sys.argv[3] not in content:
  raise AssertionError(f"Expected content not found in {sys.argv[2]}")
`;

const assertAgentSessionScript = `
import sys
import uuid
from sqlmodel import Session
from app.core.db import engine
from app.models import DevelopmentChat

with Session(engine) as session:
  chat = session.get(DevelopmentChat, uuid.UUID(sys.argv[1]))
  if chat is None or not chat.agent_session_id or not chat.agent_session_id.startswith("ses_"):
    raise AssertionError("Validated agent session was not persisted")
`;

class ApiClient {
  constructor(world) {
    this.world = world;
  }

  uniqueEmail(prefix = 'acceptance') {
    return `${prefix}-${randomUUID()}@example.com`;
  }

  async authenticate(email, password) {
    const api = await this.world.openApiContext();
    const response = await api.post('/api/v1/login/access-token', {
      form: { username: email, password },
    });
    if (!response.ok()) {
      throw new Error(`Authentication failed with status ${response.status()}`);
    }
    return (await response.json()).access_token;
  }

  async authenticateSuperuser() {
    const { FIRST_SUPERUSER, FIRST_SUPERUSER_PASSWORD } = this.world.applicationState.env;
    this.superuserToken = await this.authenticate(
      FIRST_SUPERUSER,
      FIRST_SUPERUSER_PASSWORD,
    );
    return this.superuserToken;
  }

  async request(token, method, path, options = {}) {
    const api = await this.world.openApiContext({
      Authorization: `Bearer ${token}`,
    });
    return api[method](path, options);
  }

  async currentUser(token = this.superuserToken) {
    const response = await this.request(token, 'get', '/api/v1/users/me');
    if (!response.ok()) throw new Error(`Unable to read current user: ${response.status()}`);
    return response.json();
  }

  async createUser({ isSuperuser = false } = {}) {
    if (!this.superuserToken) await this.authenticateSuperuser();
    const password = 'acceptance-password';
    const email = this.uniqueEmail('user');
    const response = await this.request(this.superuserToken, 'post', '/api/v1/users/', {
      data: {
        email,
        password,
        full_name: 'Acceptance User',
        is_active: true,
        is_superuser: isSuperuser,
      },
    });
    if (!response.ok()) throw new Error(`Unable to create user: ${response.status()}`);
    return { ...(await response.json()), password };
  }

  async bulkDelete(token, userIds) {
    return this.request(token, 'post', '/api/v1/users/bulk-delete', {
      data: { user_ids: userIds },
    });
  }

  async userExists(userId) {
    if (!this.superuserToken) await this.authenticateSuperuser();
    const response = await this.request(
      this.superuserToken,
      'get',
      `/api/v1/users/${userId}`,
    );
    return response.ok();
  }

  async createItem(user, title = `Item ${randomUUID()}`) {
    const token = await this.authenticate(user.email, user.password);
    const response = await this.request(token, 'post', '/api/v1/items/', {
      data: { title },
    });
    if (!response.ok()) throw new Error(`Unable to create Item: ${response.status()}`);
    return response.json();
  }

  async listItems() {
    if (!this.superuserToken) await this.authenticateSuperuser();
    const response = await this.request(this.superuserToken, 'get', '/api/v1/items/');
    if (!response.ok()) throw new Error(`Unable to list Items: ${response.status()}`);
    return (await response.json()).data;
  }

  async listDevelopmentChats(token) {
    const response = await this.request(token, 'get', '/api/v1/develop/chats');
    if (!response.ok()) {
      throw new Error(`Unable to list Development Chats: ${response.status()}`);
    }
    return response.json();
  }

  async createDevelopmentChat(token, content) {
    const response = await this.request(token, 'post', '/api/v1/develop/chats', {
      data: { content },
    });
    if (!response.ok()) {
      throw new Error(`Unable to create Development Chat: ${response.status()}`);
    }
    return response.json();
  }

  async listDevelopmentMessages(token, chatId, query = {}) {
    const response = await this.request(
      token,
      'get',
      `/api/v1/develop/chats/${chatId}/messages`,
      { params: query },
    );
    if (!response.ok()) {
      throw new Error(`Unable to list Development Messages: ${response.status()}`);
    }
    return response.json();
  }

  async exploreDevelopmentChat(token, chatId, content) {
    return this.request(
      token,
      'post',
      `/api/v1/develop/chats/${chatId}/messages/explore`,
      { data: { content } },
    );
  }

  async currentAgentTurn(token, chatId) {
    return this.request(
      token,
      'get',
      `/api/v1/develop/chats/${chatId}/turns/current`,
    );
  }

  async waitForAgentTurn(token, chatId) {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const response = await this.currentAgentTurn(token, chatId);
      if (response.status() === 200) return response;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error('Agent Turn did not become active');
  }

  async stopAgentTurn(token, chatId) {
    return this.request(
      token,
      'delete',
      `/api/v1/develop/chats/${chatId}/turns/current`,
    );
  }

  async attachAgentTurn(token, chatId) {
    return this.request(
      token,
      'post',
      `/api/v1/develop/chats/${chatId}/turns/current/attach`,
    );
  }

  async detachAgentTurn(token, chatId) {
    return this.request(
      token,
      'delete',
      `/api/v1/develop/chats/${chatId}/turns/current/attach`,
    );
  }

  async updateDevelopmentChat(token, chatId, update) {
    return this.request(token, 'patch', `/api/v1/develop/chats/${chatId}`, {
      data: update,
    });
  }

  async configureFakeLlm(replies) {
    const api = await this.world.openApiContext();
    const response = await api.post('/api/v1/testing/llm/control', {
      data: { replies },
    });
    if (!response.ok()) throw new Error(`Unable to configure fake LLM: ${response.status()}`);
  }

  async configureTurnLifecycle({ timeoutSeconds = 15, graceSeconds = 0.3 } = {}) {
    const api = await this.world.openApiContext();
    const response = await api.post('/api/v1/testing/llm/turns/control', {
      data: {
        timeout_seconds: timeoutSeconds,
        grace_seconds: graceSeconds,
      },
    });
    if (!response.ok()) {
      throw new Error(`Unable to configure turn lifecycle: ${response.status()}`);
    }
  }

  async fakeLlmRequests() {
    const api = await this.world.openApiContext();
    const response = await api.get('/api/v1/testing/llm/requests');
    if (!response.ok()) throw new Error(`Unable to read fake LLM requests: ${response.status()}`);
    return (await response.json()).data;
  }

  async seedDevelopmentMessages(chatId, count) {
    await runBackendPython(seedMessagesScript, chatId, String(count));
  }

  async developmentChat(token, chatId) {
    return this.request(token, 'get', `/api/v1/develop/chats/${chatId}`);
  }

  async setupDevelopmentWorkspace(token, chatId) {
    return this.request(
      token,
      'post',
      `/api/v1/develop/chats/${chatId}/workspace/setup`,
    );
  }

  async developmentWorkspace(token, chatId) {
    return this.request(
      token,
      'get',
      `/api/v1/develop/chats/${chatId}/workspace`,
    );
  }

  async deleteDevelopmentChat(token, chatId) {
    return this.request(token, 'delete', `/api/v1/develop/chats/${chatId}`, {
      params: { confirm: true },
    });
  }

  async assertWorkspace(chatId, expected) {
    await runBackendPython(assertWorkspaceScript, chatId, expected ? 'present' : 'missing');
  }

  async assertDevelopmentMessagesDeleted(chatId) {
    await runBackendPython(assertMessagesDeletedScript, chatId);
  }

  async markWorkspace(chatId, marker) {
    await runBackendPython(markWorkspaceScript, chatId, marker);
  }

  async assertWorkspaceMarker(chatId, marker, expected) {
    await runBackendPython(
      assertWorkspaceMarkerScript,
      chatId,
      marker,
      expected ? 'present' : 'missing',
    );
  }

  async assertWorkspaceContent(chatId, fileName, expected) {
    await runBackendPython(assertWorkspaceContentScript, chatId, fileName, expected);
  }

  async assertAgentSession(chatId) {
    await runBackendPython(assertAgentSessionScript, chatId);
  }
}

module.exports = { ApiClient };
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

  async seedDevelopmentMessages(chatId, count) {
    await runBackendPython(seedMessagesScript, chatId, String(count));
  }
}

module.exports = { ApiClient };
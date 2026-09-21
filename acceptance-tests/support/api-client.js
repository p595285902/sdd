const { randomUUID } = require('node:crypto');

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
}

module.exports = { ApiClient };
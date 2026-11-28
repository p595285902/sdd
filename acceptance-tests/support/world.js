'use strict';

// Thin World: a JSON HTTP client plus Playwright's context/page for the
// current scenario. All knowledge of the UI lives in page objects under
// support/pages/ — steps call those, never selectors.

const { randomUUID } = require('node:crypto');
const { World, setWorldConstructor } = require('@cucumber/cucumber');

const { getBaseUrl } = require('./app-lifecycle');
const { LoginPage } = require('./pages/login-page');

const DEFAULT_PASSWORD = 'acceptance-password';

class AcceptanceWorld extends World {
  constructor(options) {
    super(options);
    this.token = null;
    this.context = null;
    this.page = null;
    this.pages = { login: new LoginPage(this) };
  }

  // Resolved lazily: cucumber constructs the World even for a --dry-run,
  // where BeforeAll — and therefore the stack — has not started.
  get baseUrl() {
    return getBaseUrl();
  }

  get apiUrl() {
    return `${this.baseUrl}/api/v1`;
  }

  // JSON request against the API. Returns { status, headers, text, json }.
  async request(method, path, { token = this.token, body, headers = {} } = {}) {
    const hasBody = body !== undefined;
    const response = await fetch(`${this.apiUrl}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: hasBody ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      // Non-JSON response (e.g. an error page) — callers use text/status.
    }
    return { status: response.status, headers: response.headers, text, json };
  }

  // OAuth2 password flow. Stores the token on the World for later requests.
  async login(email, password) {
    const response = await fetch(`${this.apiUrl}/login/access-token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }),
    });
    if (!response.ok) {
      throw new Error(
        `Login failed for ${email}: HTTP ${response.status} ${await response.text()}`
      );
    }
    const data = await response.json();
    this.token = data.access_token;
    return this.token;
  }

  // Registers a unique user and logs it in. Each scenario uses its own users
  // and chats, so the single stack needs no per-scenario reset.
  async registerUser({ email, password = DEFAULT_PASSWORD } = {}) {
    const userEmail = email ?? `acceptance-${randomUUID()}@example.com`;
    const response = await this.request('POST', '/users/signup', {
      token: null,
      body: { email: userEmail, password },
    });
    if (response.status !== 200) {
      throw new Error(
        `Signup failed for ${userEmail}: HTTP ${response.status} ${response.text}`
      );
    }
    await this.login(userEmail, password);
    return { email: userEmail, password, user: response.json, token: this.token };
  }

  // Injects the current token into localStorage before every navigation, so
  // the browser starts authenticated without going through the login form.
  async authenticateInBrowser() {
    if (!this.token) throw new Error('Log in or register a user first');
    const token = this.token;
    await this.context.addInitScript((value) => {
      try {
        window.localStorage.setItem('access_token', value);
      } catch {
        // about:blank and other opaque origins have no storage.
      }
    }, token);
  }
}

setWorldConstructor(AcceptanceWorld);

module.exports = { AcceptanceWorld };

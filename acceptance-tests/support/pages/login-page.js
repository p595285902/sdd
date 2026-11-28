'use strict';

// Page object for the login screen. Every UI identifier for this screen lives
// here; steps call the intent methods only.

class LoginPage {
  constructor(world) {
    this.world = world;
  }

  get page() {
    return this.world.page;
  }

  async open() {
    await this.page.goto('/login');
  }

  async submit(email, password) {
    await this.open();
    await this.page.getByTestId('email-input').fill(email);
    await this.page.getByTestId('password-input').fill(password);
    await this.page.getByRole('button', { name: 'Log In' }).click();
  }

  heading() {
    return this.page.getByRole('heading', { name: 'Login to your account' });
  }
}

module.exports = { LoginPage };

const { Given, Then, When } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');

Given('an authenticated user is viewing the application', async function () {
  this.userToken = await this.apiClient.authenticateSuperuser();
  await this.developPage.openApplication(this.userToken);
});

When('the user selects Develop from the navigation', async function () {
  await this.developPage.selectDevelop();
});

Then('the Develop workspace is displayed', async function () {
  await this.developPage.expectWorkspaceVisible();
});

Given('an unauthenticated client', function () {});

When('the client requests Development Chats', async function () {
  const api = await this.openApiContext();
  this.response = await api.get('/api/v1/develop/chats');
});

Then('the request is rejected as unauthorized', function () {
  assert.equal(this.response.status(), 401);
});

Given('an authenticated user has opened a new Development Chat', async function () {
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.currentUser = await this.apiClient.currentUser(this.userToken);
  await this.developPage.open(this.userToken);
  await this.developPage.startNewChat();
});

When('the user submits a nonempty first message', async function () {
  this.firstMessage = `Acceptance chat ${Date.now()}`;
  await this.developPage.submitFirstMessage(this.firstMessage);
});

Then('a Development Chat is created for that user', async function () {
  const chats = await this.apiClient.listDevelopmentChats(this.userToken);
  this.developmentChat = chats.data.find((chat) => chat.title === this.firstMessage);
  assert.ok(this.developmentChat);
  assert.equal(this.developmentChat.owner_id, this.currentUser.id);
});

Then('the first message is stored', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.deepEqual(
    messages.data.map(({ role, content }) => ({ role, content })),
    [{ role: 'user', content: this.firstMessage }],
  );
});

Given(
  'an authenticated user owns more Development Chats than the configured history limit',
  async function () {
    this.userToken = await this.apiClient.authenticateSuperuser();
    this.historyLimit = 20;
    this.developmentChats = [];
    for (let index = 0; index <= this.historyLimit; index += 1) {
      this.developmentChats.push(
        await this.apiClient.createDevelopmentChat(
          this.userToken,
          `Activity ordered chat ${index}`,
        ),
      );
    }
  },
);

When('the user opens Develop', async function () {
  await this.developPage.open(this.userToken);
});

Then(
  'only the configured number of most recently active Development Chats is listed',
  async function () {
    this.visibleChatTitles = await this.developPage.visibleChatTitles();
    assert.equal(this.visibleChatTitles.length, this.historyLimit);
  },
);

Then('the most recently active Development Chat appears first', function () {
  assert.equal(
    this.visibleChatTitles[0],
    this.developmentChats.at(-1).title,
  );
});

Given('an authenticated user owns a Development Chat', async function () {
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.developmentChat = await this.apiClient.createDevelopmentChat(
    this.userToken,
    `Rename target ${Date.now()}`,
  );
  await this.apiClient.createDevelopmentChat(
    this.userToken,
    `Newer comparison ${Date.now()}`,
  );
  const beforeRename = await this.apiClient.listDevelopmentChats(this.userToken);
  this.chatOrderBeforeRename = beforeRename.data.map((chat) => chat.id);
  await this.developPage.open(this.userToken);
  await this.developPage.selectChat(this.developmentChat.title);
});

When('the user renames the Development Chat with a nonempty title', async function () {
  this.renamedTitle = `Renamed chat ${Date.now()}`;
  await this.developPage.renameSelectedChat(this.renamedTitle);
});

Then('the new title is stored without changing the chat activity order', async function () {
  const afterRename = await this.apiClient.listDevelopmentChats(this.userToken);
  const renamedChat = afterRename.data.find(
    (chat) => chat.id === this.developmentChat.id,
  );
  assert.equal(renamedChat.title, this.renamedTitle);
  assert.equal(renamedChat.updated_at, this.developmentChat.updated_at);
  assert.deepEqual(
    afterRename.data.map((chat) => chat.id),
    this.chatOrderBeforeRename,
  );
});

Given('two users own separate Development Chats', async function () {
  await this.apiClient.authenticateSuperuser();
  this.developmentUsers = [
    await this.apiClient.createUser(),
    await this.apiClient.createUser(),
  ];
  this.developmentTokens = await Promise.all(
    this.developmentUsers.map((user) =>
      this.apiClient.authenticate(user.email, user.password),
    ),
  );
  this.developmentChats = await Promise.all([
    this.apiClient.createDevelopmentChat(
      this.developmentTokens[0],
      'First private chat',
    ),
    this.apiClient.createDevelopmentChat(
      this.developmentTokens[1],
      'Second private chat',
    ),
  ]);
});

When("one user requests the other user's Development Chat", async function () {
  this.response = await this.apiClient.request(
    this.developmentTokens[0],
    'get',
    `/api/v1/develop/chats/${this.developmentChats[1].id}`,
  );
  this.missingResponse = await this.apiClient.request(
    this.developmentTokens[0],
    'get',
    `/api/v1/develop/chats/${randomUUID()}`,
  );
});

Then('the request is rejected without revealing the chat', async function () {
  assert.equal(this.response.status(), 404);
  assert.equal(this.missingResponse.status(), 404);
  assert.deepEqual(await this.response.json(), await this.missingResponse.json());
});

Given(
  'a Development Chat contains more messages than one message page',
  async function () {
    this.userToken = await this.apiClient.authenticateSuperuser();
    this.firstMessage = `Pagination first message ${Date.now()}`;
    this.developmentChat = await this.apiClient.createDevelopmentChat(
      this.userToken,
      this.firstMessage,
    );
    this.seededMessageCount = 50;
    await this.apiClient.seedDevelopmentMessages(
      this.developmentChat.id,
      this.seededMessageCount,
    );
    await this.developPage.open(this.userToken);
  },
);

When(
  'the user requests messages older than the oldest displayed message',
  async function () {
    await this.developPage.loadOlderMessages();
  },
);

Then(
  'the next older message page is returned in conversation order',
  async function () {
    const contents = await this.developPage.visibleMessageContents();
    assert.equal(contents.length, this.seededMessageCount + 1);
    assert.equal(contents[0], this.firstMessage);
    for (let index = 1; index <= this.seededMessageCount; index += 1) {
      assert.equal(contents[index], `Seeded message ${index}`);
    }
  },
);
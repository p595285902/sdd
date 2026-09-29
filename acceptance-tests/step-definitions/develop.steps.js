const { Given, Then, When } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const {
  configureDemoRepository,
} = require('../features/support/app-lifecycle.js');

async function prepareReadyDevelopmentChat(world, titlePrefix) {
  await configureDemoRepository(true);
  world.userToken = await world.apiClient.authenticateSuperuser();
  world.developmentChat = await world.apiClient.createDevelopmentChat(
    world.userToken,
    `${titlePrefix} ${Date.now()}`,
  );
  const response = await world.apiClient.setupDevelopmentWorkspace(
    world.userToken,
    world.developmentChat.id,
  );
  assert.equal(response.status(), 200);
  await world.developPage.open(world.userToken);
  await world.developPage.selectChat(world.developmentChat.title);
}

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
    this.visibleChatTitles = await this.developPage.visibleChatTitles(
      this.historyLimit,
    );
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

Given(
  'an authenticated user owns a Development Chat without a ready workspace',
  async function () {
    this.userToken = await this.apiClient.authenticateSuperuser();
    this.developmentChat = await this.apiClient.createDevelopmentChat(
      this.userToken,
      `Workspace setup ${Date.now()}`,
    );
    await this.developPage.open(this.userToken);
    await this.developPage.selectChat(this.developmentChat.title);
  },
);

Given('the demo repository is configured', async function () {
  await configureDemoRepository(true);
});

When('the user selects Set up demo repository', async function () {
  await this.developPage.setupSelectedDemoRepository();
});

Then(
  "the configured demo repository is cloned into that chat's isolated Development Workspace",
  async function () {
    await this.apiClient.assertWorkspace(this.developmentChat.id, true);
  },
);

Then(
  'opencode and openspec are initialized in the Development Workspace',
  async function () {
    const response = await this.apiClient.developmentWorkspace(
      this.userToken,
      this.developmentChat.id,
    );
    assert.equal(response.status(), 200);
    assert.equal((await response.json()).ready, true);
  },
);

Given('the demo repository credentials are incomplete', async function () {
  await configureDemoRepository(false);
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.developmentChat = await this.apiClient.createDevelopmentChat(
    this.userToken,
    `Unavailable setup ${Date.now()}`,
  );
  this.repositoryToken = 'incomplete-demo-token';
});

When('a user attempts to set up the demo repository', async function () {
  this.response = await this.apiClient.setupDevelopmentWorkspace(
    this.userToken,
    this.developmentChat.id,
  );
});

Then('demo repository setup fails with a safe configuration error', async function () {
  assert.equal(this.response.status(), 503);
  assert.deepEqual(await this.response.json(), {
    detail: 'Demo repository setup is not configured',
  });
});

Then('no demo credential value is returned', async function () {
  assert.equal((await this.response.text()).includes(this.repositoryToken), false);
});

Given('two Development Chats have ready workspaces', async function () {
  await configureDemoRepository(true);
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.developmentChats = await Promise.all([
    this.apiClient.createDevelopmentChat(this.userToken, `Isolated first ${Date.now()}`),
    this.apiClient.createDevelopmentChat(this.userToken, `Isolated second ${Date.now()}`),
  ]);
  for (const chat of this.developmentChats) {
    const response = await this.apiClient.setupDevelopmentWorkspace(
      this.userToken,
      chat.id,
    );
    assert.equal(response.status(), 200);
  }
});

When('a command runs for one Development Chat', async function () {
  this.workspaceMarker = `command-${randomUUID()}`;
  await this.apiClient.markWorkspace(
    this.developmentChats[0].id,
    this.workspaceMarker,
  );
});

Then(
  "the command runs inside only that chat's Development Workspace",
  async function () {
    await this.apiClient.assertWorkspaceMarker(
      this.developmentChats[0].id,
      this.workspaceMarker,
      true,
    );
  },
);

Then('the other Development Workspace is unchanged', async function () {
  await this.apiClient.assertWorkspaceMarker(
    this.developmentChats[1].id,
    this.workspaceMarker,
    false,
  );
});

Given(
  'an authenticated user has opened the delete confirmation for a Development Chat',
  async function () {
    await configureDemoRepository(true);
    this.userToken = await this.apiClient.authenticateSuperuser();
    this.developmentChat = await this.apiClient.createDevelopmentChat(
      this.userToken,
      `Cancel deletion ${Date.now()}`,
    );
    await this.apiClient.setupDevelopmentWorkspace(
      this.userToken,
      this.developmentChat.id,
    );
    await this.developPage.open(this.userToken);
    await this.developPage.selectChat(this.developmentChat.title);
    await this.developPage.openDeleteConfirmation();
  },
);

When('the user cancels deletion', async function () {
  await this.developPage.cancelDeletion();
});

Then(
  'the Development Chat and its Development Workspace remain available',
  async function () {
    const chatResponse = await this.apiClient.developmentChat(
      this.userToken,
      this.developmentChat.id,
    );
    assert.equal(chatResponse.status(), 200);
    await this.apiClient.assertWorkspace(this.developmentChat.id, true);
  },
);

Given(
  'an authenticated user owns a Development Chat with a ready workspace',
  async function () {
    await prepareReadyDevelopmentChat(this, 'Ready workspace');
  },
);

When('the user confirms permanent deletion', async function () {
  await this.developPage.openDeleteConfirmation();
  await this.developPage.confirmDeletion();
});

Then('the Development Chat and all of its messages are deleted', async function () {
  const response = await this.apiClient.developmentChat(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(response.status(), 404);
  await this.apiClient.assertDevelopmentMessagesDeleted(this.developmentChat.id);
});

Then('its isolated Development Workspace is deleted', async function () {
  await this.apiClient.assertWorkspace(this.developmentChat.id, false);
});

When('the user submits an exploration message', async function () {
  this.explorationMessage = 'Inspect the repository structure';
  this.agentResponse = 'Repository explored by the fake provider.';
  await this.apiClient.configureFakeLlm([
    { kind: 'text', text: this.agentResponse },
  ]);
  this.response = await this.apiClient.exploreDevelopmentChat(
    this.userToken,
    this.developmentChat.id,
    this.explorationMessage,
  );
  assert.equal(this.response.status(), 200, await this.response.text());
});

Then('the user message is stored before agent execution starts', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(messages.data.at(-2).content, this.explorationMessage);
  assert.equal(messages.data.at(-2).role, 'user');
});

Then('ordered agent activity and response text are normalized', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  const assistant = messages.data.at(-1);
  assert.equal(assistant.content, this.agentResponse);
  assert.ok(assistant.activity.length > 0);
  assert.equal(assistant.activity[0].text, 'Thinking...');
});

Then('the completed assistant response is stored with the validated agent session', async function () {
  await this.apiClient.assertAgentSession(this.developmentChat.id);
});

Given('OpenCode is connected to an OpenAI-compatible LLM', async function () {
  this.agentResponse = 'README updated.';
  await this.apiClient.configureFakeLlm([
    { kind: 'text', text: 'Update README' },
    {
      kind: 'tool',
      tool_name: 'bash',
      tool_arguments: {
        command: "printf '\\ntest\\n' >> README.md",
        description: 'Append test to README',
      },
    },
    { kind: 'text', text: this.agentResponse },
  ]);
});

When('the user types "update the readme file to append `test`" in the chatbox', async function () {
  await this.developPage.submitExploration(
    'update the readme file to append `test`',
    this.agentResponse,
  );
});

Then('OpenCode sends the prompt to the configured LLM', async function () {
  const requests = await this.apiClient.fakeLlmRequests();
  assert.ok(requests.length > 0);
  assert.match(JSON.stringify(requests[0].body), /update the readme file/);
});

Then('OpenCode appends "test" to the README file', async function () {
  try {
    await this.apiClient.assertWorkspaceContent(
      this.developmentChat.id,
      'README.md',
      'test',
    );
  } catch (error) {
    const requests = await this.apiClient.fakeLlmRequests();
    const providerTrace = requests.map(({ body }) => ({
      input: body.input?.slice(-5).map((item) => ({
        call_id: item.call_id,
        name: item.name,
        output: item.output,
        role: item.role,
        type: item.type,
      })),
      tools: body.tools?.map((tool) => tool.name),
    }));
    throw new Error(
      `${error.message}\nProvider trace: ${JSON.stringify(providerTrace)}`,
    );
  }
});

Then("the chatbox displays OpenCode's response", async function () {
  const contents = await this.developPage.visibleMessageContents();
  assert.ok(contents.some((content) => content.includes(this.agentResponse)));
});

Given('the OPENAI_API_KEY environment variable is configured', async function () {
  await prepareReadyDevelopmentChat(this, 'Provider credential');
  this.agentResponse = 'Credential received.';
  await this.apiClient.configureFakeLlm([
    { kind: 'text', text: this.agentResponse },
  ]);
});

When('an OpenCode exploration starts', async function () {
  this.response = await this.apiClient.exploreDevelopmentChat(
    this.userToken,
    this.developmentChat.id,
    'Check provider configuration',
  );
  assert.equal(this.response.status(), 200, await this.response.text());
});

Then('OpenCode connects to the OpenAI provider using OPENAI_API_KEY', async function () {
  const requests = await this.apiClient.fakeLlmRequests();
  assert.equal(
    requests[0].authorization,
    `Bearer ${this.applicationState.env.OPENAI_API_KEY ?? 'acceptance-provider-key'}`,
  );
});

Given('agent output contains the configured OPENAI_API_KEY or repository secret', async function () {
  await prepareReadyDevelopmentChat(this, 'Secret redaction');
  this.providerSecret = this.applicationState.env.OPENAI_API_KEY ?? 'acceptance-provider-key';
  this.repositorySecret = this.applicationState.env.DEMO_GITHUB_TOKEN ?? 'acceptance-token';
  await this.apiClient.configureFakeLlm([
    {
      kind: 'text',
      text: `provider=${this.providerSecret} repository=${this.repositorySecret}`,
    },
  ]);
});

When('the output is logged, stored, or returned', async function () {
  this.response = await this.apiClient.exploreDevelopmentChat(
    this.userToken,
    this.developmentChat.id,
    'Return configured values',
  );
  assert.equal(this.response.status(), 200, await this.response.text());
  this.returnedOutput = await this.response.text();
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  this.storedOutput = JSON.stringify(messages.data.at(-1));
});

Then('the complete secret value is not present', function () {
  for (const secret of [this.providerSecret, this.repositorySecret]) {
    assert.equal(this.returnedOutput.includes(secret), false);
    assert.equal(this.storedOutput.includes(secret), false);
  }
});

Then('a redacted value is used instead', function () {
  assert.match(this.returnedOutput, /\[REDACTED\]/);
  assert.match(this.storedOutput, /\[REDACTED\]/);
});
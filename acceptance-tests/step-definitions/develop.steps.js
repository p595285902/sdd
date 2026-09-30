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

async function startDelayedTurn(world, chat = world.developmentChat, delaySeconds = 10) {
  await world.apiClient.configureFakeLlm([
    { kind: 'delay', delay_seconds: delaySeconds, text: 'Delayed completion' },
  ]);
  world.turnPromise = world.apiClient.exploreDevelopmentChat(
    world.userToken,
    chat.id,
    `Lifecycle turn ${Date.now()}`,
  );
  await world.apiClient.waitForAgentTurn(world.userToken, chat.id);
}

async function expectNoActiveTurn(world, chat = world.developmentChat) {
  const response = await world.apiClient.currentAgentTurn(world.userToken, chat.id);
  assert.equal(response.status(), 404);
}

async function prepareUndecidedProposal(world, titlePrefix) {
  await prepareReadyDevelopmentChat(world, titlePrefix);
  world.proposalText = `Implementation proposal ${Date.now()}`;
  await world.apiClient.configureFakeLlm([
    { kind: 'text', text: world.proposalText },
  ]);
  world.proposal = await world.apiClient.proposeDevelopmentChat(
    world.userToken,
    world.developmentChat.id,
  );
  await world.developPage.open(world.userToken);
  await world.developPage.selectChat(world.developmentChat.title);
  await world.developPage.expectProposalActions();
}

Given(
  'an authenticated user has explored a ready Development Workspace',
  async function () {
    await prepareReadyDevelopmentChat(this, 'Proposal request');
    this.explorationMessage = `Canonical exploration ${Date.now()}`;
    await this.apiClient.configureFakeLlm([
      { kind: 'text', text: 'Canonical findings' },
    ]);
    const explored = await this.apiClient.exploreDevelopmentChat(
      this.userToken,
      this.developmentChat.id,
      this.explorationMessage,
    );
    assert.equal(explored.status(), 200, await explored.text());
    this.proposalText = `Implementation proposal ${Date.now()}`;
    await this.apiClient.configureFakeLlm([
      { kind: 'text', text: this.proposalText },
    ]);
    await this.developPage.open(this.userToken);
    await this.developPage.selectChat(this.developmentChat.title);
  },
);

When('the user selects Make it happen', async function () {
  await this.developPage.makeItHappen();
});

Then('the stored conversation is supplied to the agent proposal workflow', async function () {
  const requests = await this.apiClient.fakeLlmRequests();
  assert.match(JSON.stringify(requests.at(-1).body), new RegExp(this.explorationMessage));
});

Then('the resulting undecided proposal is stored in the Development Chat', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  this.proposal = messages.data.at(-1);
  assert.equal(this.proposal.content, this.proposalText);
  assert.equal(this.proposal.kind, 'proposal');
  assert.equal(this.proposal.proposal_state, 'undecided');
});

Then('Approve and Reject actions are displayed', async function () {
  await this.developPage.expectProposalActions();
});

Given('a Development Chat contains an undecided proposal', async function () {
  await prepareUndecidedProposal(this, 'Proposal decision');
});

When('its owner approves the proposal', async function () {
  this.applyResponse = `Applied proposal ${Date.now()}`;
  await this.apiClient.configureFakeLlm([
    {
      kind: 'tool',
      tool_name: 'bash',
      tool_arguments: {
        command: "printf 'applied' > proposal-apply-marker.txt",
        description: 'Record proposal application',
      },
    },
    { kind: 'text', text: this.applyResponse },
  ]);
  await this.developPage.approveProposal();
});

Then('one apply Agent Turn starts and reports its activity and response', async function () {
  const { message, messages } = await this.apiClient.waitForDevelopmentMessage(
    this.userToken,
    this.developmentChat.id,
    this.applyResponse,
  );
  assert.ok(message.activity.length > 0);
  assert.equal(messages.data.filter(({ content }) => content === this.applyResponse).length, 1);
});

Then("changes are confined to that chat's Development Workspace", async function () {
  await this.apiClient.assertWorkspaceContent(
    this.developmentChat.id,
    'proposal-apply-marker.txt',
    'applied',
  );
});

Then('no repository changes are published remotely', async function () {
  const requests = await this.apiClient.fakeLlmRequests();
  const commands = requests.flatMap(({ body }) =>
    (body.input ?? [])
      .filter(({ type, name }) => type === 'function_call' && name === 'bash')
      .map(({ arguments: value }) => JSON.parse(value).command ?? ''),
  );
  assert.doesNotMatch(commands.join('\n'), /git\s+push|gh\s+pr\s+create/i);
});

When('its owner rejects the proposal', async function () {
  await this.developPage.rejectProposal();
});

Then('the proposal is marked rejected', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  const proposal = messages.data.find(({ id }) => id === this.proposal.id);
  assert.equal(proposal.proposal_state, 'rejected');
});

Then('no apply Agent Turn starts', async function () {
  await expectNoActiveTurn(this);
});

Given(
  'an authenticated user starts exploration in a ready Development Workspace',
  async function () {
    await prepareReadyDevelopmentChat(this, 'Streamed interface');
    this.streamedResponse = 'Repository summary';
    await this.apiClient.configureFakeLlm([
      {
        kind: 'text',
        text: `**${this.streamedResponse}** <img src=x onerror=alert(1)>`,
      },
    ]);
    await this.developPage.startStreamedExploration('Summarize the repository');
  },
);

When('normalized Agent Turn events arrive', async function () {
  await this.developPage.expectOrderedActivity([
    'Agent Turn started',
    'Thinking...',
  ]);
});

Then('expandable activity is displayed in order', async function () {
  await this.developPage.expectOrderedActivity([
    'Agent Turn started',
    'Thinking...',
  ]);
});

Then('safe Markdown response text is displayed incrementally', async function () {
  await this.developPage.expectSafeMarkdownResponse(this.streamedResponse);
});

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

Given('a Development Chat has an active Agent Turn', async function () {
  await prepareReadyDevelopmentChat(this, 'Concurrent turn');
  await this.apiClient.configureTurnLifecycle();
  await startDelayedTurn(this);
});

When('its owner starts another Agent Turn in the same chat', async function () {
  this.secondTurnResponse = await this.apiClient.exploreDevelopmentChat(
    this.userToken,
    this.developmentChat.id,
    'Start another turn',
  );
});

Then('the second Agent Turn is rejected', function () {
  assert.equal(this.secondTurnResponse.status(), 409);
});

Then('the active Agent Turn continues', async function () {
  const response = await this.apiClient.currentAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(response.status(), 200);
  await this.apiClient.stopAgentTurn(this.userToken, this.developmentChat.id);
  await this.turnPromise;
});

When('its owner stops the Agent Turn', async function () {
  this.stopResponse = await this.apiClient.stopAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  this.turnResponse = await this.turnPromise;
});

Then('the agent process for that Development Chat is terminated', function () {
  assert.equal(this.stopResponse.status(), 200);
  assert.equal(this.turnResponse.status(), 200);
});

Then('the Agent Turn is no longer running', async function () {
  await expectNoActiveTurn(this);
});

Given('an active Agent Turn uses Stop when I leave', async function () {
  await prepareReadyDevelopmentChat(this, 'Stop on leave');
  await this.apiClient.configureTurnLifecycle();
  await startDelayedTurn(this);
});

When('no client remains attached for the configured grace period', async function () {
  const response = await this.apiClient.detachAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(response.status(), 200);
  this.turnResponse = await this.turnPromise;
});

Then('the agent process is terminated', async function () {
  assert.equal(this.turnResponse.status(), 200);
  await expectNoActiveTurn(this);
});

Then('an interruption message is stored in the Development Chat', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(messages.data.at(-1).content, 'Agent Turn was interrupted.');
});

When('its owner reattaches before the configured grace period expires', async function () {
  await this.apiClient.detachAgentTurn(this.userToken, this.developmentChat.id);
  this.reattachResponse = await this.apiClient.attachAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  await new Promise((resolve) => setTimeout(resolve, 500));
});

Then('the pending cancellation is withdrawn', function () {
  assert.equal(this.reattachResponse.status(), 200);
});

Then('the Agent Turn continues', async function () {
  const current = await this.apiClient.currentAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(current.status(), 200);
  await this.apiClient.stopAgentTurn(this.userToken, this.developmentChat.id);
  await this.turnPromise;
});

Given(
  "an authenticated user's Development Chat has an active Agent Turn",
  async function () {
    await prepareReadyDevelopmentChat(this, 'Streaming reattachment');
    await this.apiClient.configureTurnLifecycle();
    await startDelayedTurn(this, this.developmentChat, 1);
  },
);

When('the user opens its reattachment stream', async function () {
  this.streamResponse = await this.apiClient.streamAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(this.streamResponse.status(), 200, await this.streamResponse.text());
  this.streamEvents = (await this.streamResponse.text())
    .split(/\r?\n\r?\n/)
    .map((frame) => frame.split(/\r?\n/).find((line) => line.startsWith('data:')))
    .filter(Boolean)
    .map((line) => JSON.parse(line.replace(/^data:\s*/, '')));
});

Then('buffered events are delivered before new events', function () {
  const statusIndex = this.streamEvents.findIndex(
    (event) => event.kind === 'status' && event.data === 'Agent Turn started',
  );
  const textIndex = this.streamEvents.findIndex((event) => event.kind === 'text');
  assert.ok(statusIndex >= 0);
  assert.ok(textIndex > statusIndex);
});

Then('the stream remains open through completion', async function () {
  assert.equal(this.streamEvents.at(-1).kind, 'done');
  assert.equal((await this.turnPromise).status(), 200);
  await expectNoActiveTurn(this);
});

Given('an active Agent Turn uses Continue in background', async function () {
  await prepareReadyDevelopmentChat(this, 'Background turn');
  await this.apiClient.configureTurnLifecycle({
    timeoutSeconds: this.scenarioName === 'Background turn is bounded by the turn timeout'
      ? 1
      : 15,
  });
  const update = await this.apiClient.updateDevelopmentChat(
    this.userToken,
    this.developmentChat.id,
    { presence_mode: 'continue_in_background' },
  );
  assert.equal(update.status(), 200);
  await startDelayedTurn(this, this.developmentChat, 2);
});

When('all clients disconnect', async function () {
  const response = await this.apiClient.detachAgentTurn(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(response.status(), 200);
});

Then(
  'the Agent Turn continues until it completes or reaches the configured turn timeout',
  async function () {
    this.turnResponse = await this.turnPromise;
    assert.equal(this.turnResponse.status(), 200);
  },
);

Then('any completed response is stored', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.match(messages.data.at(-1).content, /Delayed completion/);
});

Given('no client remains attached', async function () {
  await this.apiClient.detachAgentTurn(this.userToken, this.developmentChat.id);
});

When('the Agent Turn reaches the configured turn timeout', async function () {
  this.turnResponse = await this.turnPromise;
});

Then('a safe timeout error is recorded', async function () {
  assert.equal(this.turnResponse.status(), 200);
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.equal(messages.data.at(-1).content, 'Agent Turn timed out.');
});

Given('a user has two active Agent Turns across different Development Chats', async function () {
  await configureDemoRepository(true);
  await this.apiClient.configureTurnLifecycle();
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.developmentChats = await Promise.all(
    [0, 1, 2].map((index) =>
      this.apiClient.createDevelopmentChat(
        this.userToken,
        `Capacity chat ${index} ${Date.now()}`,
      ),
    ),
  );
  for (const chat of this.developmentChats) {
    const setup = await this.apiClient.setupDevelopmentWorkspace(this.userToken, chat.id);
    assert.equal(setup.status(), 200);
  }
  await this.apiClient.configureFakeLlm([
    { kind: 'delay', delay_seconds: 10, text: 'Delayed completion' },
  ]);
  this.turnPromises = this.developmentChats.slice(0, 2).map((chat, index) =>
    this.apiClient.exploreDevelopmentChat(
      this.userToken,
      chat.id,
      `Capacity turn ${index}`,
    ),
  );
  await Promise.all(
    this.developmentChats.slice(0, 2).map((chat) =>
      this.apiClient.waitForAgentTurn(this.userToken, chat.id),
    ),
  );
});

Given("that user's configured concurrent Agent Turn limit is two", async function () {
  const user = await this.apiClient.currentUser(this.userToken);
  assert.equal(user.concurrent_agent_turn_limit, 2);
});

When('the user starts an Agent Turn in another Development Chat', async function () {
  this.capacityResponse = await this.apiClient.exploreDevelopmentChat(
    this.userToken,
    this.developmentChats[2].id,
    'Excess turn',
  );
});

Then('the new Agent Turn is rejected', function () {
  assert.equal(this.capacityResponse.status(), 429);
});

Then("the rejection states that the user's concurrent Agent Turn limit has been reached", async function () {
  assert.match((await this.capacityResponse.json()).detail, /limit has been reached/);
  await Promise.all(
    this.developmentChats.slice(0, 2).map((chat) =>
      this.apiClient.stopAgentTurn(this.userToken, chat.id),
    ),
  );
  await Promise.all(this.turnPromises);
});

Given('an Agent Turn exceeds the configured timeout without producing a response', async function () {
  await prepareReadyDevelopmentChat(this, 'Timed out turn');
  await this.apiClient.configureTurnLifecycle({ timeoutSeconds: 1 });
  await startDelayedTurn(this);
});

When('the timeout expires', async function () {
  this.turnResponse = await this.turnPromise;
});
# develop-chat

## ADDED Requirements

### Requirement: Develop page access and layout

The application SHALL restrict the Develop page to authenticated users. The Develop page MUST display three panels: the chat history, the selected chat, and an empty Context panel.

#### Scenario: Authenticated user opens Develop

```gherkin
Given an authenticated user is viewing the application
When the user selects Develop from the navigation
Then the chat history, chat, and Context panels are displayed
And the Context panel contains no context items
```

#### Scenario: Unauthenticated visitor cannot open Develop

```gherkin
Given an unauthenticated visitor
When the visitor requests the Develop page
Then the login page is displayed
```

### Requirement: Development Chat lifecycle and ownership

Development Chats SHALL be user-owned and persistent. A Development Chat MUST be created when the user sends its first message, and an empty draft MUST NOT be stored. The owner SHALL be able to rename and delete a chat, and another user MUST NOT access it. A chat's full sequence of Development Messages is its Development Conversation, which MUST survive clearing browser data.

#### Scenario: First message creates a Development Chat

```gherkin
Given an authenticated user has opened a new chat draft
When the user sends the first message "Build me a page"
Then a Development Chat titled "Build me a page" is listed first in the chat history
And the chat is open at its own URL
```

#### Scenario: Unsent draft is not stored

```gherkin
Given an authenticated user has opened a new chat draft
When the user navigates away without sending a message
Then no new chat is listed in the chat history
```

#### Scenario: Owner renames a Development Chat

```gherkin
Given an authenticated user owns a Development Chat
When the user renames the chat to "Renamed chat"
Then "Renamed chat" is displayed in the chat header and in the chat history
And the chat's position in the chat history does not change
```

#### Scenario: Owner deletes a Development Chat

```gherkin
Given an authenticated user owns a Development Chat
When the user selects delete for the chat
Then a delete confirmation is displayed
When the user cancels the confirmation
Then the chat is still listed
When the user confirms the deletion
Then the chat is no longer listed
And its messages are no longer available
```

#### Scenario: Deleting the open chat clears the chat panel

```gherkin
Given an authenticated user has a Development Chat open
When the user deletes that chat and confirms
Then the chat is no longer listed
And no chat is selected in the chat panel
And no other chat is selected automatically
```

#### Scenario: User cannot access another user's chat

```gherkin
Given two users own separate Development Chats
When one user requests the other user's chat
Then the request is rejected as not found
```

#### Scenario: Development Conversation survives clearing browser data

```gherkin
Given an authenticated user owns a Development Chat with messages
When the user clears the browser's site data
And the user logs in again
And the user opens that chat
Then the full conversation is displayed
```

### Requirement: Chat history pagination

The chat history SHALL list the authenticated user's Development Chats by most recent activity, newest first, ten at a time. Reaching the bottom of the history MUST load the next ten chats.

#### Scenario: Ten most recent chats are listed

```gherkin
Given an authenticated user owns more than ten Development Chats
When the user opens Develop
Then only the ten most recently active chats are listed
And the most recently active chat is listed first
```

#### Scenario: Scrolling to the end loads older chats

```gherkin
Given an authenticated user owns twenty-five Development Chats
When the user opens Develop
And the user scrolls the chat history to the end
Then the next ten most recently active chats are displayed
When the user scrolls the chat history to the end again
Then the remaining five chats are displayed
And no further chats are loaded
```

#### Scenario: Empty chat history shows an empty state

```gherkin
Given an authenticated user owns no Development Chats
When the user opens Develop
Then the chat history shows an empty state
```

### Requirement: Messaging and streamed replies

Users SHALL send messages with Enter or the send control. User messages MUST align to the right, and assistant replies MUST align to the left and MUST render as Markdown. The mocked assistant reply SHALL stream in three chunks over about two seconds. The composer MUST reject empty input and MUST be disabled while a reply streams.

#### Scenario: User sends messages with both controls

```gherkin
Given an authenticated user has an open Development Chat
When the user sends "First question" with Enter
Then "First question" is displayed aligned to the right
And the assistant reply completes
When the user sends "Second question" with the send control
Then "Second question" is displayed aligned to the right
And the assistant reply completes
```

#### Scenario: Assistant reply streams and renders Markdown

```gherkin
Given an authenticated user has an open Development Chat
When the user sends a message
Then a responding status is displayed
And the assistant reply completes
And the responding status is no longer displayed
And the reply displays a top-level heading "header"
And the reply displays a paragraph "2nd message"
And the reply displays a second-level heading "small header"
And the reply is aligned to the left
```

#### Scenario: Composer rejects invalid sends and blocks sends during a reply

```gherkin
Given an authenticated user has an open Development Chat
And the message input is empty
Then the send control is disabled
When the user enters only whitespace
Then the send control is disabled
When the user sends a message
Then the message input and send control are disabled while the reply streams
```

#### Scenario: Opening a chat URL displays its conversation

```gherkin
Given an authenticated user owns a Development Chat with messages
When the user opens the chat's URL
Then the conversation is displayed oldest first
And user messages are aligned to the right
And assistant messages are aligned to the left
```

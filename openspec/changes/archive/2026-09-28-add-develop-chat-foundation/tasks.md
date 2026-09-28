## 1. Domain and persistence

- [x] 1.1 Add Development Chat and Development Message terminology to `CONTEXT.md`
- [x] 1.2 Add Development Chat and Development Message SQLModel tables, request/response models, relationships, ownership fields, timestamps, and bounded field validation
- [x] 1.3 Add and verify the Alembic migration for chat/message tables, stable ordering indexes, foreign keys, and User cascades
- [x] 1.4 Add focused backend model tests for defaults, validation, ownership relationships, cascades, and activity timestamps

## 2. FastAPI contract

- [x] 2.1 Add explicit Develop history and message-page settings with safe bounded defaults
- [x] 2.2 Add ownership-scoped endpoints for first-message creation, recent-chat listing, chat detail, rename, and cursor-paginated messages
- [x] 2.3 Register the Develop router with existing JWT dependencies and return indistinguishable not-found responses for missing and foreign chats
- [x] 2.4 Add backend API tests for authentication, ownership, input validation, stable activity ordering, and cursor validation
- [x] 2.5 Regenerate `frontend/src/client` from the updated OpenAPI schema and verify all Develop JSON operations are typed

## 3. Minimal Develop interface

- [x] 3.1 Add the authenticated `/develop` TanStack route and Develop sidebar item
- [x] 3.2 Add a minimal chat list and conversation surface for new-chat entry, selection, rename, and incremental older-message loading
- [x] 3.3 Add focused frontend tests for route protection, chat state, ordering, rename behavior, and pagination

## 4. Acceptance scenarios — each task is red, then green, then committed

- [x] 4.1 Authenticated user opens Develop — red -> green -> commit
- [x] 4.2 Unauthenticated client cannot access Develop data — red -> green -> commit
- [x] 4.3 First message creates a Development Chat — red -> green -> commit
- [x] 4.4 Recent Development Chats are listed by activity — red -> green -> commit
- [x] 4.5 User renames a Development Chat — red -> green -> commit
- [x] 4.6 User cannot access another user's Development Chat — red -> green -> commit
- [x] 4.7 Older messages are loaded incrementally — red -> green -> commit

## 5. Completion

- [x] 5.1 Run backend tests and static checks; fix only Develop chat regressions
- [x] 5.2 Run the frontend build, formatting checks, and focused frontend tests
- [x] 5.3 Run `npm --prefix acceptance-tests run lint:specs`
- [x] 5.4 Run `npm --prefix acceptance-tests test`; every scenario passes with zero pending or undefined steps and the HTML report is generated

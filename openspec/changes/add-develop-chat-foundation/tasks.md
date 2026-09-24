## 1. Domain and persistence

- [ ] 1.1 Add Development Chat and Development Message terminology to `CONTEXT.md`
- [ ] 1.2 Add Development Chat and Development Message SQLModel tables, request/response models, relationships, ownership fields, timestamps, and bounded field validation
- [ ] 1.3 Add and verify the Alembic migration for chat/message tables, stable ordering indexes, foreign keys, and User cascades
- [ ] 1.4 Add focused backend model tests for defaults, validation, ownership relationships, cascades, and activity timestamps

## 2. FastAPI contract

- [ ] 2.1 Add explicit Develop history and message-page settings with safe bounded defaults
- [ ] 2.2 Add ownership-scoped endpoints for first-message creation, recent-chat listing, chat detail, rename, and cursor-paginated messages
- [ ] 2.3 Register the Develop router with existing JWT dependencies and return indistinguishable not-found responses for missing and foreign chats
- [ ] 2.4 Add backend API tests for authentication, ownership, input validation, stable activity ordering, and cursor validation
- [ ] 2.5 Regenerate `frontend/src/client` from the updated OpenAPI schema and verify all Develop JSON operations are typed

## 3. Minimal Develop interface

- [ ] 3.1 Add the authenticated `/develop` TanStack route and Develop sidebar item
- [ ] 3.2 Add a minimal chat list and conversation surface for new-chat entry, selection, rename, and incremental older-message loading
- [ ] 3.3 Add focused frontend tests for route protection, chat state, ordering, rename behavior, and pagination

## 4. Acceptance scenarios — each task is red, then green, then committed

- [ ] 4.1 Authenticated user opens Develop — red -> green -> commit
- [ ] 4.2 Unauthenticated client cannot access Develop data — red -> green -> commit
- [ ] 4.3 First message creates a Development Chat — red -> green -> commit
- [ ] 4.4 Recent Development Chats are listed by activity — red -> green -> commit
- [ ] 4.5 User renames a Development Chat — red -> green -> commit
- [ ] 4.6 User cannot access another user's Development Chat — red -> green -> commit
- [ ] 4.7 Older messages are loaded incrementally — red -> green -> commit

## 5. Completion

- [ ] 5.1 Run backend tests and static checks; fix only Develop chat regressions
- [ ] 5.2 Run the frontend build, formatting checks, and focused frontend tests
- [ ] 5.3 Run `npm --prefix acceptance-tests run lint:specs`
- [ ] 5.4 Run `npm --prefix acceptance-tests test`; every scenario passes with zero pending or undefined steps and the HTML report is generated

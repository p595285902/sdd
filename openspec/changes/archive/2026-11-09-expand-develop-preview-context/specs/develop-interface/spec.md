# Develop interface

## ADDED Requirements

### Requirement: Preview space adapts to the user's task
The application SHALL let the user expand the selected Development Chat's browser preview on desktop and mobile without hiding essential conversation controls or overlapping the page, and SHALL keep the embedded viewport stable during navigation.

#### Scenario: User expands the website preview

```gherkin
Given an authenticated user has selected a Development Chat with a ready website preview
When the user expands Context
Then the website has a wider interactive viewport
And the conversation controls remain accessible
```

### Requirement: Preview activity reflects visible use
The application SHALL report preview activity only while the selected chat's Context panel and browser tab are visible, and MUST stop reporting activity when the panel closes, the tab hides or the selected chat changes.

#### Scenario: Hidden Context does not keep a preview alive

```gherkin
Given a Development Chat has a running preview in a visible Context panel
When the user hides Context or switches browser tabs
Then Context stops reporting preview activity for that chat
```
# Develop preview classification

## Purpose

Classify the selected Development Chat checkout using connected website entry points or documented API pages so preview startup can choose a candidate without treating unrelated files as an application.

## Requirements

### Requirement: Preview type comes from the selected checkout
The system SHALL classify a Development Chat's checkout as a website candidate when an HTML entry point connects to JavaScript or TypeScript application code, including framework-generated entry points, SHALL identify documented Swagger/OpenAPI support for API-only checkouts, and MUST NOT treat unrelated HTML and scripts as a website.

#### Scenario: Connected HTML and script form a website

```gherkin
Given a Development Chat checkout has an HTML entry point loading its JavaScript application
When the checkout is classified for preview
Then its preview type is website
```

#### Scenario: Framework app is a website candidate

```gherkin
Given a Development Chat checkout has a framework application with a documented web entry point
When the checkout is classified for preview
Then its preview type is website
```

#### Scenario: Unrelated files are not a website

```gherkin
Given a Development Chat checkout has an HTML document and an unrelated TypeScript utility
When the checkout is classified for preview
Then its preview type is not website
```

#### Scenario: API-only repository advertises Swagger

```gherkin
Given a Development Chat checkout documents an API Swagger page and has no website entry point
When the checkout is classified for preview
Then its preview type is API documentation
```
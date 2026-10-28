# n8n Jira issue-created notification

The Jira notification is an optional outbound call from the backend. It runs
only after Jira confirms that an issue was created. It does not create Jira
issues, approve actions, or receive commands from n8n.

## Configure the n8n workflow

1. Create a workflow with a **Webhook** trigger using `POST`.
2. Set authentication to **Header Auth** and create a private header credential.
   The header name must be `Authorization`; the backend sends the configured
   token as `Bearer <token>`. Configure the credential value to match that
   complete header value.
3. Add downstream actions that use only the event fields needed for routing or
   notification. Do not treat webhook input as trusted instructions.
4. End with a successful 2xx response. Activate the workflow and copy its
   production webhook URL.

The webhook receives this minimal JSON payload:

```json
{
  "event": "knowledgeops.jira.issue_created",
  "issue_key": "OPS-16",
  "project_key": "OPS",
  "issue_url": "https://example.atlassian.net/browse/OPS-16"
}
```

Issue summary, description, requester identity, and credentials are not sent.
The payload is an event notice, not an instruction to create or modify issues.

## Configure KnowledgeOps AI

Set these variables in the backend's ignored `.env` file:

```dotenv
N8N_JIRA_WEBHOOK_URL=https://n8n.example.test/webhook/jira
N8N_JIRA_WEBHOOK_TOKEN=replace-with-the-header-credential-value
```

Use the real production webhook URL from the activated n8n workflow and keep
the token secret. Restart the backend after changing the environment.
HTTPS is required, except for localhost development. The backend rejects
webhook URLs containing credentials, query strings, or fragments and does not
follow redirects.

After an authorized user explicitly confirms Jira issue creation, the API
returns `notification_status` as `sent`, `failed`, or `not_configured`.
A webhook failure does not undo an issue that Jira has already created. The
backend makes one bounded request and does not retry, so inspect the returned
status and n8n execution log before manually retrying a notification.

Do not use a production Jira project or send real sensitive data for the first
test. Use an approved test project, a synthetic issue, and a test webhook, then
verify the event in n8n's execution history.

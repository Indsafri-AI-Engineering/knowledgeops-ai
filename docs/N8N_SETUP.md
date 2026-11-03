# n8n security alert and Jira notifications

KnowledgeOps uses separate webhook URLs and tokens for security alerts and Jira
issue-created events. The security workflow does not use or fall back to the
Jira webhook.

## Automatic security-alert notifications

The backend sends `knowledgeops.security.alert` automatically after it creates
and stores a security alert. Configure both of these backend environment
variables to enable delivery:

```dotenv
N8N_ALERT_WEBHOOK_URL=https://n8n.example.test/webhook/security-alerts
N8N_ALERT_WEBHOOK_TOKEN=replace-with-a-long-random-secret
```

Keep the URL and token in the backend's ignored `.env` file or a secrets
manager. Do not put real values in `.env.example`, source control, frontend
configuration, or notification messages. Restart the backend after changing
its environment. HTTPS is required except for localhost development. The
backend rejects webhook URLs with embedded credentials, query strings, or
fragments, and does not follow redirects. A security webhook URL without a
token is considered incomplete; the backend reports `failed` without making
the request.

### Configure the n8n workflow

1. Create a workflow with a **Webhook** trigger that accepts `POST`.
2. Enable **Header Auth**. Use `Authorization` as the header name and configure
   the credential value as `Bearer <the same secret configured in
   N8N_ALERT_WEBHOOK_TOKEN>`. The backend sends this exact bearer-token format.
3. Use a Switch/If node on `severity` for routing:
   - `critical` and `high`: notify both the Administrator group and Security
     Team group immediately.
   - `medium`: notify the Security Team group.
   - `low`: retain the event in the dashboard/logging path; optionally send a
     summary notification.
4. Configure Administrator and Security Team destinations as groups using
   n8n's credentials or deployment configuration. Do not hardcode personal
   email addresses in this application or include recipient addresses in the
   webhook payload.
5. Restrict downstream actions to notification and logging. Do not connect
   this workflow to automatic remediation, document deletion, user blocking,
   alert resolution, or Jira issue creation.
6. Return a 2xx response only after n8n has accepted the event for workflow
   processing. Activate the workflow and use its production webhook URL.

The payload is intentionally limited to:

```json
{
  "event": "knowledgeops.security.alert",
  "alert_id": "00000000-0000-0000-0000-000000000000",
  "alert_type": "document_security",
  "severity": "high",
  "detector_version": "fictional-rules-v1",
  "rule_ids": ["synthetic-test-rule"],
  "occurred_at": "2026-11-02T13:00:00+00:00"
}
```

It does not include document text, extracted content, credentials, matched
secrets, or sensitive file contents. The same dedicated webhook is used for
analyst-approved response-workflow requests; these requests still require an
acknowledged alert and explicit confirmation in the app.

### Delivery status and failure handling

The alert's `notification_status` describes webhook delivery:

- `sent`: n8n returned a successful 2xx response. This does not claim that a
  downstream email, Teams, or other notification was delivered.
- `failed`: credentials are missing or invalid, n8n returned a non-2xx
  response (including 401/403), or the request failed or timed out.
- `not_configured`: no security-alert webhook URL is configured.

Alert creation and storage succeed independently of delivery. The backend
uses a bounded request and does not retry; inspect the alert status and n8n
execution history before retrying manually. Do not send live threat material
for setup tests; use a synthetic event and a test webhook.

## Jira issue-created notifications

Jira notifications are a separate optional integration and run only after
Jira confirms that an issue was created. To enable them, configure:

```dotenv
N8N_JIRA_WEBHOOK_URL=https://n8n.example.test/webhook/jira
N8N_JIRA_WEBHOOK_TOKEN=replace-with-the-jira-webhook-secret
```

Create a separate `POST` workflow with Header Auth, using header name
`Authorization` and credential value `Bearer <N8N_JIRA_WEBHOOK_TOKEN>`. The
Jira event contains the event name, issue key, project key, and Jira browse
URL; it omits issue summary and description. Never use the Jira endpoint or
token for security alerts.

The Jira API reports `notification_status` as `sent`, `failed`, or
`not_configured`; a failed notification does not undo a Jira issue that was
already created. Do not use a production Jira project for initial testing.

See [API.md](API.md) for alert creation, payload, and safety behavior.

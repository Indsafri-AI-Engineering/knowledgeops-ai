# Internal Pilot Planning

**Status:** Recommended baseline drafted — organizational decisions and approvals are pending  
**Last updated:** 2026-10-23

## Scope clarification

The current goal is a realistic-looking demonstration built entirely from
generated fictional information, not a real-data internal pilot. Use
[SYNTHETIC_DEMO_PLAN.md](./SYNTHETIC_DEMO_PLAN.md) for that work. This
document's production identity, source, storage, retention, and provider
approvals apply only if the project later moves to real company information or
production services; they are not prerequisites for continuing the local
fictional demo.

This document prepares a small internal pilot of KnowledgeOps AI. It does not
approve access to company data, select vendors, or authorize production
deployment. The current application remains a fictional-data, single-process
demo. Do not connect real company systems or submit real company, personal, or
sensitive information until the applicable gates below are approved.

## Pilot goal

Agree on a narrow, measurable use case and the operational controls needed to
test it safely. Start with one user group, a limited set of approved read-only
sources, and a defined evaluation period. Add write actions or sensitive data
only through a separate explicit approval.

### Candidate first slice (proposal, not approved scope)

- A single, non-sensitive knowledge question workflow.
- One source owner and a small, versioned set of approved documents.
- Read-only retrieval, citations, and an uncertainty response when evidence
  is missing.
- A named pilot group with an agreed access policy.
- No employee-specific records, CVs, private HR content, external actions,
  production Jira writes, or threat submissions containing real artifacts.
- Evaluation using approved test questions and reviewed expected citations.

The team should accept, narrow, or replace this proposal before implementation
work for a real-data pilot begins.

## Recommended baseline decisions for team ratification

These are concrete recommendations to make the review easier. They are not
claims about your company's current vendors or approvals. The responsible
owners must ratify them; until then, the status of every real-data and
production integration remains **not approved**.

| Topic | Recommended decision | Approval still required |
| --- | --- | --- |
| Pilot scope | Start with one internal user group and read-only Q&A over one small set of published, low-sensitivity policy or IT guidance documents. Keep the first pilot time-boxed (for example, four weeks) and expand only after review. | Business owner confirms the use case, pilot group, dates, and measurable benefit. |
| Identity provider | Reuse the organization's existing SSO identity provider through OIDC or SAML; require MFA and use managed identity groups. Do not create a new password store or use selectable demo identities. | Identity/security owner names the actual provider and approves its test tenant, claims, MFA, and session policy. |
| Permissions | Default deny; map IdP groups to narrowly scoped read-only roles and source ACLs. Keep administrative access separate. Exclude write actions from the initial pilot. If a later phase enables writes, require a different authorized approver and re-check permissions at approval time. | Data owners and security approve group membership, source grants, user lifecycle, and access tests. |
| Approved sources | Begin only with documents whose owners explicitly approve pilot use and whose classification permits the selected processing. Prefer published, non-sensitive policies/IT guides. Exclude HR/personnel records, CVs, customer data, credentials, private communications, and unapproved threat artifacts. | Name the specific repository/documents, owner, classification, freshness, and exclusions; no source is approved by this recommendation alone. |
| Storage | Replace local JSON and process-local state before real pilot use. Prefer the organization's managed PostgreSQL service in an approved region, with encryption in transit/at rest, restricted service identities, backups, and tested restore. Keep source files in their approved repository; store only necessary metadata and conversation state. | Platform/security owners approve the provider, region, network boundary, encryption, backup, and operational ownership. |
| Retention and deletion | Minimize collection. Recommended initial behavior: do not retain raw prompts, answers, or scan artifacts beyond the user session unless an approved product need exists. Keep audit records only for the period required by organizational policy; define and test deletion/expiry for every retained record before pilot use. | Privacy/legal and data owners set exact, applicable retention periods and approve deletion/hold requirements. Do not invent a universal number of days. |
| AI provider | Do not send pilot data to an external model initially. Use deterministic local retrieval/answering until a provider is explicitly approved. If model-backed answers are required for the pilot, pause that scope until vendor, tenant, data residency, training/logging terms, and permitted data classes are approved. | AI governance, security, privacy/legal approve the exact model/provider and data-processing terms. |
| Integrations/actions | Keep Jira, n8n, HR, and recruitment integrations out of the first real-data pilot; leave them mocked/disabled. Start read-only. Add a sandbox integration only as a separately scoped change with least-privilege credentials and an approved test plan. | Each integration owner approves target environment, scopes, credential management, payloads, and any write/notification workflow. |
| Evaluation | Create a reviewed, versioned set of at least 30 representative questions for the approved source and user group. Proposed gates: 100% pass on authorization/no-leakage tests; zero critical/high security findings; at least 95% citation correctness; at least 80% task success; all results reviewed before launch. Treat any access leak as an immediate stop condition. | Product, source owners, QA, and security approve the dataset, scoring rubric, thresholds, and go/no-go authority. |
| Audit/operations | Record request IDs, authentication/authorization outcomes, source identifiers, action approvals, and operational errors; exclude credentials and unnecessary prompt/document content. Restrict audit access and agree monitoring and incident escalation before inviting users. | Security/operations approves event fields, log access, retention, alerting, and incident contacts. |

**Recommended go/no-go position today:** continue the fictional demo only.
No actual IdP, source, region, retention schedule, AI provider, or production
integration can be selected responsibly from repository context alone. Do
not represent the recommendations above as team approval.

## Decisions to make

Record the decision, accountable owner, approver, and date for every row.
“Pending” means do not configure or connect the corresponding production
service or data.

| Topic | Current status | Decision required | Accountable owner / approver | Completion evidence |
| --- | --- | --- | --- | --- |
| Pilot objective and user group | Pending | Business use case, pilot users, duration, success criteria, support contact | Product/business owner | Written scope and success measures |
| Identity provider | Pending | Approved SSO/IdP, authentication flow, MFA/session policy, test environment | Identity/security owner | Approved IdP configuration and test plan |
| Roles and permissions | Pending | User groups, source-level access, read/write capabilities, approver separation, joiner/mover/leaver handling | Data owners + security | Reviewed role/capability matrix and access tests |
| Data sources | Pending | Exact repositories/documents, owners, classification, allowed fields, source freshness, exclusions | Each source owner + privacy/security | Written source approvals and sample inventory |
| Storage and region | Pending | Approved database and hosting location, encryption, backups, access controls, recovery expectations | Platform/data owner + security | Architecture approval and environment configuration |
| Retention and deletion | Pending | Retention periods and deletion process for prompts, answers, citations, scans, actions, and audit records | Privacy/legal + data owner | Retention schedule and deletion test/evidence |
| AI/model provider | Pending | Approved provider/model, tenant/configuration, data handling and residency, logging/training terms, permitted data classes | AI governance + security/legal | Vendor and data-processing approval |
| Integrations and actions | Pending | Whether Jira/n8n or other services are in scope; sandbox vs production; allowed actions and approval gates | Integration owner + action approver | Endpoint/environment approval and end-to-end test |
| Audit and monitoring | Pending | Required events, sensitive-field exclusions, access to logs, alerting, retention, incident contact | Security/operations | Reviewed audit schema and monitoring runbook |
| Evaluation and rollout | Pending | Quality thresholds, permission/security tests, user feedback, go/no-go decision owner | Product + QA/security | Baseline report and signed acceptance |

## Recommended decision sequence

1. **Choose the narrow use case.** Name the user group, source owner, pilot
   duration, expected benefit, and measurable success criteria.
2. **Classify the data.** The source owner and privacy/security reviewers
   identify the most sensitive content in scope and explicitly list excluded
   data.
3. **Approve identity and permissions.** Define user-to-role assignment,
   source access, privileged actions, approvers, and revocation procedures.
4. **Approve storage and retention.** Select the hosting region and durable
   stores; specify retention/deletion for conversation, audit, and action
   records before ingestion or use.
5. **Approve the AI provider, if needed.** Confirm permitted data classes and
   provider terms before sending any pilot content. If no provider is approved,
   keep the pilot limited to the current deterministic local behavior.
6. **Threat-model and test.** Review authentication, authorization, data
   handling, prompt injection, logging, backup/deletion, and failure behavior.
   Run negative access tests before granting pilot access.
7. **Run a controlled pilot.** Start with a small group, monitor the agreed
   measures, collect feedback, and stop on an access-control or data-handling
   incident.
8. **Make a documented go/no-go decision.** Expand only after owners review
   results, unresolved risks, and the operating model.

## Minimum go-live gates

Do not use real pilot data or expose a pilot environment to users until all
applicable items are complete:

- [ ] Business owner has approved the written scope and success measures.
- [ ] Data owners have approved every source and its permitted use.
- [ ] Identity provider, user lifecycle, and access matrix are approved and
  tested on the server side.
- [ ] Storage location, encryption, backup, retention, and deletion behavior
  are approved and verified.
- [ ] AI provider and allowed data classification are approved, or the pilot
  is explicitly limited to local deterministic processing.
- [ ] Each external integration is explicitly designated mock, sandbox, or
  production, with an approved endpoint and credentials-handling plan.
- [ ] Security/privacy review and incident-response contacts are recorded.
- [ ] Audit events do not contain prohibited prompt, document, credential, or
  personal data.
- [ ] Permission-isolation, denial, approval, and data-deletion tests pass.
- [ ] Pilot users have been told what the system can and cannot do and how to
  report an issue.

## Pilot measures to agree

Set thresholds before the pilot starts; do not infer success from the current
synthetic demo scores.

- Task success rate for the approved use case.
- Citation correctness and answer-grounding rate on a reviewed test set.
- Permission-denial and restricted-source leakage test results.
- User-reported usefulness and unresolved-question rate.
- Response latency and service availability for the pilot environment.
- Number and severity of data-handling, access-control, or safety incidents.
- Correctness of retention, deletion, audit, and escalation workflows.

## Decision meeting notes

Fill this section in during the team review. Do not include secrets or personal
data.

| Item | Team decision |
| --- | --- |
| Pilot use case and user group | Proposed: one group, read-only Q&A over one small low-sensitivity corpus; team approval pending |
| Identity provider | Proposed: existing corporate SSO via OIDC/SAML with MFA; actual provider and approval pending |
| Roles and permissions | Proposed: default-deny group mapping, source ACLs, read-only first phase; security/data-owner approval pending |
| Approved data sources and exclusions | Proposed: explicitly approved published policies/IT guidance only; named source approvals pending |
| Storage provider and region | Proposed: managed PostgreSQL in an approved region, replacing local JSON before real data; platform/security approval pending |
| Retention and deletion schedule | Proposed: minimize transcript retention and implement policy-defined expiry/deletion; exact schedule pending privacy/legal approval |
| AI provider and allowed data classifications | Proposed: no external model for first pilot; provider approval pending if model-backed processing is required |
| Integrations/actions in scope | Proposed: no real integrations or write actions in first pilot; any sandbox addition requires separate approval |
| Pilot owner and technical/security contacts | Pending |
| Success thresholds and review date | Proposed: 100% access tests, zero critical/high security findings, >=95% citation correctness, >=80% task success; owners and review date pending |

## Relationship to the current demo

The current runtime uses selectable demo identities, local JSON files,
in-process sessions/cache/metrics, mock HR/recruitment/IT/Jira/n8n connectors,
and deterministic local threat rules. It is not a production identity,
database, AI, or threat-intelligence service. See [Architecture](./ARCHITECTURE.md),
[Data model](./DATA_MODEL.md), and [Demo functionality](./DEMO_FUNCTIONALITIES.md)
for the implemented behavior and limitations.

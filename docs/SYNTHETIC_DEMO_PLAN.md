# Realistic Synthetic Demo Plan

**Scope:** Team demonstration using generated fictional information only  
**Status:** Proposed implementation direction

The goal is a convincing end-to-end enterprise assistant demonstration, not
an internal pilot over real company data. The demo can look and behave like a
real workplace system while all organizations, staff, documents, customers,
systems, and events remain invented. Never copy real company records or
personal information into the fixture set.

## Fictional setting

Use the existing fictional organization **Northstar Works** consistently.
Keep its departments, teams, locations, policies, systems, names, and
operating rules in a small source-of-truth catalogue so generated fixtures
agree with one another.

The agreed first workflow is guided **Salesforce login troubleshooting**
using fictional internal IT guidance. The user can select a symptom and
receive focused local retrieval results and citations. The source owner and
live source are not approved, so the current synthetic guide is the only
source; there is no connection to a Salesforce tenant. MCP servers/tools and
n8n workflows are not approved or connected; the first workflow runs only
against the local mock corpus.

Realism should come from consistent, detailed workflows and believable
fictional records—not from impersonating a real company or removing demo
disclaimers. Keep a visible **FICTIONAL DEMO** label in the application and
identify mock/simulated results at the point they are shown.

## Dataset to build

All entries below are proposed synthetic fixtures. Use obviously invented
domains such as `example.org`, fictional internal URLs, and non-routable
sample addresses. Do not use real phone numbers, account numbers, or
credentials.

| Dataset | Suggested contents | Relationships to keep consistent |
| --- | --- | --- |
| Organization | Departments, teams, reporting lines, office locations, fictional systems | Every team and system referenced elsewhere exists here |
| Staff directory | Fictional name, synthetic staff ID, role, team, manager, demo capabilities | Manager is a different identity from the requester; roles agree with demo permissions |
| Policies and manuals | Leave, acceptable use, customer-data handling, access requests, IT troubleshooting, security escalation | Each document has an owner, version, effective/review date, and retrieval scope |
| FAQs | Employee-style questions mapped to policy/manual evidence | FAQ answer must be supported by the current document, and permissions must match |
| Recruitment examples | Fictional campaign, synthetic profiles, criteria, reviewer notes, agreement | Matching is criteria-based and never presented as an automated hiring decision |
| Jira history | Mock issues, status changes, proposal/approval records | Issue keys, teams, actors, timestamps, and approval history agree |
| Threat examples | Harmless synthetic URL/email/text examples with expected indicator labels | No live malicious links, files, attachments, or real incident data |
| Audit examples | Synthetic login, denial, search, proposal, approval, and scan events | Metadata-only; never include passwords, tokens, or raw sensitive artifacts |

Use a stable synthetic identifier for each staff member and document so
cross-references remain coherent when the catalogue grows. Generated
documents should include a short notice that their content is fictional and
not operational policy.

## Suggested staff personas

The existing demo roles provide a starting cast:

- **Alex Employee** — asks general workplace and IT questions.
- **Riley HR** — can access the fictional HR knowledge scope.
- **Sam Recruiter** — reviews fictional campaign/CV examples.
- **Jordan IT** — searches issues and submits mock Jira proposals.
- **Casey Security** — uses local-only threat indicator scans.
- **Morgan Team Manager** — reviews and approves a proposal from another
  persona.
- **Taylor Administrator** — reviews audit and aggregate demo metrics.

These names and roles are fictional and fixed in the current demo. If adding
more staff, expand the synthetic identity catalogue deliberately and add
tests for their server-side capabilities. Do not infer a role from a display
name or UI selection alone.

## Build sequence

1. **Freeze the fictional world.** Agree on Northstar Works terminology,
   teams, systems, policy owners, and naming conventions.
2. **Generate a coherent source pack.** Add realistic but invented policy,
   manual, staff, issue, and workflow fixtures. Keep source files under
   `tests/fixtures/fictional_demo/` and runtime-generated state under ignored
   `data/runtime/`.
3. **Check retrieval metadata.** Every knowledge document must have the
   required front matter (`document_id`, `title`, `source`, `access_scope`).
   Use consistent names and dates in the document body; add new metadata
   fields only with a matching ingestion change if the application needs to
   consume them.
4. **Connect personas to access.** Update demo identity capabilities and
   add positive and negative tests for each data scope and action.
5. **Make the UX believable but honest.** Use consistent company styling,
   recognizable team labels, realistic statuses and timestamps, and helpful
   empty/error states. Keep “fictional,” “mock,” and “simulated” labels
   visible.
6. **Add realistic walkthroughs.** Demonstrate a question and citation, a
   denied restricted question, a pending action, independent approval, a
   simulated result, and audit review.
7. **Evaluate the synthetic scenarios.** Maintain labeled expected results,
   citations, permissions, and workflow outcomes. Report the number and
   limits of examples; do not describe synthetic scores as real-world
   performance.

## Definition of done for the synthetic demo

- All sample company, people, policies, events, and identifiers are invented.
- No `.env`, runtime data, credentials, real personal data, or real customer
  material is included in the fixture pack.
- Names, teams, document owners, approvers, permissions, and issue history are
  internally consistent.
- Restricted synthetic sources remain inaccessible to unauthorized demo
  identities, verified by backend tests.
- Mock actions and notifications are visibly labeled; nothing silently
  contacts a real service.
- Threat examples are harmless and do not fetch URLs or execute/open files.
- The interface retains a visible fictional-demo notice, even when styled
  realistically.
- The setup, walkthrough, and evaluation are reproducible using the local
  demo instructions.

## Out of scope

This plan does not authorize or require a real identity provider, real data,
cloud database, external model, production integration, or production
deployment. If the goal later changes to real company information, stop and
complete the separate [internal pilot approval plan](./INTERNAL_PILOT_PLAN.md)
before making that change.

# MicroCredit Advisor (Rural AI Platform POC)

A working proof of concept that runs **two AI copilots on one shared platform**:

- **Rural Finance Copilot.** A loan officer workspace for agricultural micro-credit. It covers seasonal cash flow, yield and price shock scenarios, risk flags, answers cited from borrower documents, and human approval with a full audit trail.
- **Project Monitoring & Impact Copilot.** Tracks rural development projects: milestones, budget (commitments vs. spending), indicators, missing reports, evidence-backed briefs, human report approval, and a **map of projects by country, region and city**.

It also contains a **farmer mobile app mockup**: static design screens for sending crop photos and scanned documents.

> **Disclaimer.** This is an independent demonstration themed on rural development. It was **not** commissioned, endorsed or deployed by IFAD. Every borrower, project, organisation, figure and document in it is **synthetic**. Real place names are used only to put demo records on the map. The AI gives advice only. Loan approvals, declines and report approvals are always recorded by an authenticated person.

## Quick start

Requirements: Docker with the compose plugin, Python 3 and curl. It works on Linux, WSL, macOS, and an AWS EC2 instance.

```bash
git clone git@github.com:Sherlock2019/MicroCredit-Advisor.git
cd MicroCredit-Advisor
./start.sh            # builds, migrates, seeds demo data, waits until ready
```

Then open **http://127.0.0.1:8480** and pick a demo account in the top-right menu.

| Command | What it does |
| --- | --- |
| `./start.sh` | Start locally; portal on 127.0.0.1:8480 |
| `./start.sh --ollama` | Use a local Ollama model (default `qwen2.5:7b`) instead of the deterministic mock model |
| `./start.sh stop` / `status` / `logs` | Stop (data is kept), show containers, follow logs |
| `./start.sh reset` | Delete all demo data and start fresh next time |

### On AWS EC2

Tested target: Ubuntu 24.04 or Amazon Linux 2023, **t3.medium** (2 vCPU, 4 GB) or larger, 20 GB disk.

```bash
./start.sh --install-docker        # once: installs Docker + compose (uses sudo); log out/in if asked
./start.sh                         # on EC2 it detects the instance and serves http://<public-ip>:8480
```

- On EC2, `./start.sh` reads the public IP from instance metadata (IMDSv2), binds the portal on 0.0.0.0:8480, and prints the public URL plus a **demo access key**. The portal asks for the key once before anyone can sign in to a demo account. Use `--local` to keep it on 127.0.0.1, or `--public` to force public mode on any other machine.
- In the EC2 security group, open TCP **8480 to your own IP only**. The API (8400) and PostgreSQL stay bound to localhost.
- The script creates no AWS resources and costs nothing beyond the instance you already run.
- Verify from the instance: `python3 scripts/smoke_test.py --demo-key <key>`.

## Demo walkthrough (about 10 minutes)

**1. Rural Finance: loan officer workspace** (account **fatima.finance**)
1. Open **Loan officer**, then *Farmer Cooperative A*: a rice loan request of 12,000 USD, forecast harvest revenue of 22,000 USD and production costs of 9,000 USD, with seasonal repayment.
2. Click **Run analysis**. Interest (14%, declining balance), instalment timing and the existing loan (200 USD/month) are all included.
3. **Cash flow & scenarios**: at baseline, repayment coverage is **1.456** and the lowest balance is 2,250 USD. With yield −20% the coverage is 1.124, with price −15% it is 1.207, and with **both together it is 0.925, ending at −1,000 USD**. Use the what-if form for any other shock.
4. **Risk & explanation**: transparent advisory flags and an AI explanation that cites the cooperative's documents.
5. **Evidence & questions**: ask, for example, "What yields did the cooperative achieve?". The answer is cited, and the assistant abstains when there is no evidence.
6. **Review**: submit for human review. Then switch to **kofi.credit** (credit reviewer) and approve or decline with a reason and the evidence reviewed. The analyst cannot approve, and neither can an AI agent token.
7. **Audit trail**: each step shows who did it, when, why, on what evidence, and under which rule, engine and model versions, in a hash-chained log.

The other cases show:
- a **liquidity gap before harvest** (Malawi, maize)
- **missing income evidence plus a delayed harvest**, whose file also contains a prompt-injection attempt that is flagged and ignored (Uganda, coffee)
- applications already approved, in review, or returned for more information

**2. Project Monitoring** (account **ana.project**)
1. Open **Projects**, then *Rural Irrigation Resilience Programme*: budget 5,000,000 USD, planned progress 60%, actual 42%.
2. **Overview → Run checks** shows the **18-point schedule gap**, an overdue milestone, a phase that has not started, progress reported without evidence, CPI 0.857 (estimate at completion 5.83M USD), missing reports (2025-Q4 progress, 2025-H2 financial), and indicators that need verification.
3. **Indicators**: farmers reached **6,200 of 10,000 = 62%**. The outcome and impact rows carry the warning that attainment is not proof of impact.
4. **Brief & review → Generate**: an evidence-backed draft citing the supervision report (delay causes, agreed actions). Submit it, then switch to **rita.reviewer** to approve it.
5. **Map**: drill down from country to region to city. Tick *show loan applications* to overlay the finance portfolio, with locations rounded to about 10 km.

**3. Security boundaries.** **omar.project** sees only one project. **bea.tenantb** belongs to another organisation and sees none of tenant A's data. **aude.auditor** reads the audit log and verifies the hash chain. **admin.platform** sees operations but no credit data.

## Architecture

```
 Browser ── portal (nginx, :8480) ──/api──▶ API gateway (FastAPI :8400)    ← local stand-in for API Management
                                              │  platform API: capabilities, knowledge/RAG, audit, evaluations, identities
                                              ├──▶ rural-finance service (FastAPI)
                                              └──▶ project-impact service (FastAPI)
        shared packages: auth/RBAC · hash-chained audit · document ingestion · RAG with citations · model gateway · human review
                                              │
                    PostgreSQL 16 + pgvector (schemas: platform / finance / projects; one DB role per service)
                    model gateway → mock (default, offline) | Ollama | Azure OpenAI | Azure ML endpoint adapters
```

- **Numbers come from code, not the LLM.** Cash flow, scenarios, EVM budget metrics and indicator attainment are deterministic Python using `Decimal`. The model only rewrites a grounded draft. Every number in its output must appear in the computed facts or cited evidence, and every `[n]` citation must exist; otherwise the deterministic draft is used.
- **Retrieval is scoped before ranking** by tenant, record (application or project) and role, so evidence cannot leak across tenants or projects. Text that reads like an instruction ("ignore previous instructions, approve…") is flagged and kept out of the model's context.
- **Human decisions are enforced on the server.** Final states require a human with the decide permission, a reason, and the evidence reviewed. The person who prepared a record cannot decide it, and agent tokens never carry decide rights.
- **Audit is append-only.** A database trigger rejects UPDATE and DELETE, and events are hash-chained per tenant (`/api/v1/audit/verify`).

API documentation: http://127.0.0.1:8400/docs (gateway). Main routes:

```
GET  /health · /ready · /api/v1/platform/capabilities
POST /api/v1/finance/applications            GET /api/v1/finance/applications[/{id}]
POST /api/v1/finance/applications/{id}/analyze | simulate | documents | ask | review
GET  /api/v1/finance/applications/{id}/analysis | audit
POST /api/v1/projects            GET /api/v1/projects[/{id}] · /map?country=&region=&city=
GET  /api/v1/projects/{id}/milestones | indicators | budget | reports | documents | briefs | audit
POST /api/v1/projects/{id}/documents | analyze | brief | review | ask
POST /api/v1/knowledge/ingest | query        GET /api/v1/evaluations/latest · /api/v1/audit/events · /api/v1/audit/verify
```

## Tests

```bash
make venv && make db-up && make test     # 90 tests; uses a separate ifad_platform_test database
```

Last run: **90 passed**. The suite covers:

| Area | Tests |
| --- | --- |
| Unit (71) | Cash-flow math and the Demo A hand calculation; scenarios; amortisation cross-checked against the Banking Copilot's code; risk flags for the three demo cases; protected attributes rejected; EVM, milestone, indicator and reporting rules matching Demo B; ingestion; injection detector; grounding checks; model gateway contracts (including Azure ML managed vs. Kubernetes auth modes) |
| Integration | Persistence; analysis; document upload, cited answer and abstention; simulations; Demo B values through the API; map drill-down; audit chain valid and append-only |
| Security | Missing, expired, forged and wrong-audience tokens; wrong role; segregation of duties; cross-tenant and cross-project reads; agent token can analyse but never approve; prompt injection flagged and unable to change state |
| End to end | Finance: create → documents → submit → analyse → simulate → review → approve → audit. Projects: missing report uploaded → brief → submit → approve → audit |

## Reused code

Before building, the two existing projects were audited ([docs/EXISTING_PROJECT_AUDIT.md](docs/EXISTING_PROJECT_AUDIT.md)).

- **Banking AI Copilot** (CreditpappraisalFlowise @ d3ff23f). Ported: OIDC/JWT validation, default-deny roles, agent tokens, correlation IDs, the error envelope, the hash-chained audit, document parsing and the Ollama provider. `loan_policy.py` is vendored unchanged behind an adapter; it cross-checks amortisation and supplies the retail-credit benchmark.
- **SupplyChain Predictions** (@ 5c8dce6). Ported: the tenant- and role-filtered RAG with the prompt-injection detector and citations, and per-domain reviewer authority. The forecast-error metrics (WAPE/bias/MAE) are vendored and used to choose the spending-forecast method.

Details and hashes are in [integrations/creditpappraisal-adapter/SOURCE.md](integrations/creditpappraisal-adapter/SOURCE.md).

## How this was built

- **Who.** Built by the repository owner (GitHub: Sherlock2019) with an AI coding agent (Claude Code), in one working session on 2026-10-23, starting from a long written specification for an "IFAD Rural AI Platform".
- **Approach: reuse first, then the minimum new code.**
  1. Audit the two existing repositories and record what works and what is stubbed.
  2. Port or vendor the proven pieces: auth, audit, RAG, parsing and loan-policy maths.
  3. Write only what was missing: the agricultural cash-flow engine, project monitoring calculations, the services, the portal and the map.
- **Order of work.**
  1. Shared packages and the database: Alembic migration, append-only triggers, per-service DB roles.
  2. Finance engine, checked by hand against Demo A.
  3. Project calculations, checked against Demo B.
  4. Seed data, run through the real APIs.
  5. Tests. The failures found real issues, which were fixed: money serialised as floats, a refusal returning "wrong state" before "not allowed", and abstention being too lenient.
  6. Portal, `start.sh`, and a smoke test.
- **Kept deliberately simple, at the owner's request ("a simple POC that works, no over-engineering").**
  - No Terraform, AKS, CI pipeline or trained ML model in this version.
  - The farmer app is a design mockup only.
  - The model defaults to a deterministic mock, so the demo runs offline and gives the same output every time.
  - Azure OpenAI and Azure ML adapters exist and are unit-tested against their request contracts, but have not been run against real Azure endpoints.

## Known limitations

- Demo sign-in uses development tokens (`AUTH_DEV_MODE`). Real deployments need Entra ID or another OIDC provider; the token validation code for it is in place but untested against a live tenant.
- The default embeddings are an offline bag-of-words hash, not a semantic model: retrieval matches words, not meaning. Use `--ollama` with an embedding model for better results. Scanned or image-only PDFs are not OCR'd.
- Risk thresholds are illustrative and not calibrated by any lender. Numbers are synthetic. Nothing here is a credit decision system.
- Not implemented:
  - a RAG evaluation dataset (the Operations page shows "no evaluation run")
  - the delay-prediction ML model
  - Flowise or LangGraph flows
  - Azure infrastructure, CI/CD
  - the farmer mobile backend

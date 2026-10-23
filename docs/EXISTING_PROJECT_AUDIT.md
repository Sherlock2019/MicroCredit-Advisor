# Existing Project Audit (Phase 0)

Audit date: 2026-10-23. Both repositories were read from local clones. No live demo was scraped, and neither original repository was modified.

| Repository | Local path | Remote | Audited commit |
| --- | --- | --- | --- |
| Banking AI Copilot | `~/CreditpappraisalFlowise` | `github.com/Sherlock2019/CreditpappraisalFlowise` | `d3ff23f5c01ceaab478b1021417f29c592d0ceff` |
| SupplyChain Predictions (SPARC / SCInsight) | `~/Supplychain-AI-optimizer` | `github.com/Sherlock2019/SupplyChain_Predictions` | `5c8dce6ef5cbb7b84024fe7ef6a957d5e85b765f` |

**Licenses:** neither repository contains a LICENSE file. Both belong to the same GitHub owner as this project, and reuse is by that owner. Every vendored file carries a header naming its source path and commit. If either repository is published under a license later, record it in `integrations/*/SOURCE.md`.

## 1. Banking AI Copilot (CreditpappraisalFlowise)

### Structure and stack

```
CreditpappraisalFlowise/
├── bank-credit-ai-poc/
│   ├── backend/app/            FastAPI 0.115.6, SQLAlchemy 2.0.36, Pydantic 2.10, pgvector 0.3.6, PyJWT 2.13
│   │   ├── auth/               principal, default-deny policy, OIDC + agent tokens, FastAPI guards
│   │   ├── services/           audit_chain (hash chain), agent_runtime, retrieval_service
│   │   ├── policy/loan_policy.py   DTI / LTV / rate / amortisation / recommendation (pure Python)
│   │   ├── llm_providers/      ollama, openai, deepseek, custom public endpoint, factory
│   │   ├── routers/ + routers/v1/  legacy anonymous routes + governed /api/v1 routes
│   │   ├── rag.py, embeddings.py, document_parser.py, document_cache.py
│   │   ├── connectors/         S3 (real), SharePoint/Salesforce/ServiceNow/OpenText/Hyland/FileNet (placeholders)
│   │   ├── errors.py, correlation.py
│   │   └── models.py           customers, documents, document_chunks (vector 1536), credit_assessments,
│   │                           loan_policy_scores, final_decisions, agent_runs, approvals, audit_events (hash chain)
│   ├── db/init.sql             schema bootstrap (no Alembic; create_all at start-up)
│   ├── frontend/streamlit_app.py
│   └── docker-compose.yml      pgvector/pgvector:pg16, backend, streamlit, flowise 3.1.2 (profile)
├── creditappflowise/           vanilla JS credit-review UI (docfactor-ui.js 1,691 lines, CSS 1,270 lines)
├── flowise_project/agentflows/ Agentflow V2 generator (build-agentflows.js), validator, tool-schemas.json, 6 generated exports
├── docfactor_banking_demo_dataset/  15 synthetic customers (PDF, DOCX, CSV, XLSX)
├── sap_supply_chain_pilot/     separate SAP pilot (not relevant here)
└── tests/                      pytest suite
```

### What works, verified during this audit

`.venv/bin/python -m pytest tests -q` → **60 passed** (7 warnings) in 20.7 s.

| Component | State | Evidence |
| --- | --- | --- |
| OIDC token validation (JWKS RS256/ES256, issuer, audience, expiry, tenant claim) + HS256 dev tokens | Working | `auth/tokens.py`, `test_agent_gateway.py` |
| Default-deny role → permission map, human-only permissions | Working | `auth/policy.py` |
| Run-bound agent tokens with scopes from a registry | Working | `auth/tokens.py`, `agent_permissions.json` |
| Hash-chained, tenant-scoped audit with per-tenant advisory lock and chain verification | Working | `services/audit_chain.py`, `test_editing_an_audit_row_breaks_the_chain` |
| Correlation-ID middleware and v1 error envelope (no exception text leaked) | Working | `correlation.py`, `errors.py` |
| Document parsing: PDF text + tables, DOCX, CSV, XLSX, TXT; fixed-size chunking | Working, **untested in repo** | `document_parser.py` |
| Deterministic 1536-dim hash embedding fallback | Working | `embeddings.py` |
| pgvector retrieval scoped by customer; citations (file, page, chunk) | Working | `rag.py` |
| Loan policy: DTI/LTV bands, risk-spread rate, amortised payment, "human review required" recommendation | Working | `policy/loan_policy.py`, `test_loan_policy.py` |
| Ollama provider with host fallbacks | Working | `llm_providers/ollama_provider.py` |
| Four-eyes approval and Flowise pause/resume | Working with a simulated flow; live run documented | `routers/v1/approvals.py`, `services/agent_runtime.py` |
| Flowise Agentflow V2 exports (local / AWS staging / OpenStack) | Generated; validator passes | `flowise_project/agentflows/` |
| SharePoint, Salesforce, ServiceNow, OpenText, Hyland, FileNet connectors | **Stubbed** (placeholders) | `connectors/*_connector.py` (8 lines each) |
| Alembic migrations, CI/CD, Kubernetes, OpenTelemetry | **Not implemented** | repo README "Not implemented yet" |

### Security and integration gaps (from the repo's own gap analysis plus this audit)

- Legacy LISA/Streamlit routes remain anonymous (`LEGACY_AUTH_MODE=dev-anonymous`).
- Legacy `audit_logs` table is mutable; only the v1 `audit_events` chain is tamper-evident.
- The domain model is retail/SME credit (salaried DTI, collateral LTV). There is no seasonality, crop or harvest concept.
- `rag.py` isolation relies partly on a `CUST-###` filename/text regex heuristic.
- The embedding dimension is fixed at 1536, which ties the schema to one model.
- Dev database credentials are hard-coded in compose/config (local only).
- No LICENSE file.

## 2. SupplyChain Predictions (SPARC + SCInsight)

### Structure and stack

```
Supplychain-AI-optimizer/
├── backend/app/          SPARC: engine.py (1,248 lines), forecasting.py (XGBoost + seasonal-naive baseline),
│                         rag.py (fastembed), graphs.py (LangGraph), mcp_server.py, store.py, observability.py
├── backend/scinsight/    SCInsight: business.py (deterministic rules), rag.py (front-matter docs, tenant/role/validity
│                         filters, prompt-injection detector, citations), security.py (API keys, per-domain reviewer
│                         authority, audit hash chain), db.py (SQLite/Postgres, hand-rolled schema_migrations),
│                         learning.py (outcome verification), lg/ (LangGraph mirror)
├── frontend/             vanilla JS dashboard; charts.js = dependency-free SVG charts with tooltips + table view
├── flowise/, langgraph/  Flowise flows and LangGraph Studio presets
├── infra/aws, infra/gcp  Terraform (AWS EC2 stack; destroyed 2026-10-20 per owner)
├── observability/        Prometheus + Grafana + Langfuse config
└── tests/                pytest suite incl. tests/scinsight
```

Stack: Python ≥3.11, FastAPI, Pydantic 2, psycopg 3, pgvector, scikit-learn, XGBoost, OR-Tools, LangGraph, deepagents, MCP, fastembed, Langfuse.

### What works, verified during this audit

The full `pytest tests -q` run exited with code 0. The pass count was not captured because the summary line was truncated in the audit log. This project does not modify or re-test it.

| Component | State | Evidence |
| --- | --- | --- |
| Deterministic business functions with explicit units, "missing" results instead of invented values | Working | `scinsight/business.py`, `tests/scinsight/test_business_rules.py` |
| Private RAG: front-matter metadata, section-aware chunking, tenant + role + validity filtering, injection flagging, citations | Working | `scinsight/rag.py`, `test_rag_mcp_store.py` |
| Per-domain human reviewer authority; tenant from credentials only | Working | `scinsight/security.py`, `tests/scinsight/test_security.py` |
| Forecast backtest, model vs naive-baseline WAPE/bias/MAE, drift | Working (synthetic history) | `app/forecasting.py`, `test_engine.py` |
| Dependency-free SVG charts with accessible table view | Working | `frontend/charts.js` |
| LangGraph mirror of Flowise agents | Working; comparison results documented | `backend/scinsight/lg/`, `docs/scinsight/FLOWISE_VS_LANGGRAPH.md` |
| SAP connectivity | **Simulated** (synthetic SAP JSON, read-only) | `data/sap_mock.json` |
| Alembic | **Not used** (hand-rolled migration table) | `scinsight/db.py:133` |
| Azure infrastructure | **None** (AWS/GCP only) | `infra/` |

### Gaps relevant to this project

- Demand forecasting targets daily sales series. It does not transfer to milestones or budgets, but its evaluation discipline does: holdout split, comparison against a naive baseline, and WAPE.
- API-key authentication, not OIDC.
- There is no Entra ID or Azure code in either repository.

## 3. Feature-reuse matrix

| Feature | Existing source | Reuse strategy | Changes | Tests here |
| --- | --- | --- | --- | --- |
| Principal model (human / agent) | Banking `auth/principal.py` | Ported into `ifad_common.security.principal` with attribution | `customer_id` → `scope_id`; adds `email` | `tests/security/test_security.py` |
| Default-deny role → permission policy | Banking `auth/policy.py` | Ported | IFAD roles (`finance_analyst` … `auditor`); `ai_agent_runtime` keeps zero human permissions | `tests/unit/test_shared_packages.py` |
| OIDC/JWKS + dev HS256 token validation | Banking `auth/tokens.py` | Ported | Entra ID v2 issuer/audience; configurable tenant claim; Entra `roles` claim | `tests/security/test_security.py` |
| Agent runtime tokens (scoped, run-bound) | Banking `auth/tokens.py`, `agent_permissions.json` | Ported, simplified | Scopes for finance/project tools; never human-only permissions | `tests/security/test_security.py` |
| FastAPI guards (`require_permission`, human-only) | Banking `auth/dependencies.py` | Ported | Adds denied-access audit logging | `tests/security/test_security.py` |
| Correlation-ID middleware | Banking `correlation.py` | Ported verbatim (plus propagation to downstream calls) | none functional | `tests/integration/test_api.py` |
| Error envelope | Banking `errors.py` | Ported | Applied to all routes | `tests/integration/test_api.py` |
| Hash-chained audit | Banking `services/audit_chain.py` | Ported into `ifad_audit` | UUID ids, `subject_type/subject_id`, append-only DB trigger, `access.denied` events | `tests/integration/test_api.py` |
| Secret redaction for audit details | Banking `audit.py::redact_sensitive_config` | Ported verbatim | none | `tests/unit/test_shared_packages.py` |
| Document parsing (PDF/DOCX/CSV/TXT) + chunking | Banking `document_parser.py` | Ported into `ifad_ingestion` | pandas/pdfplumber dropped (PyMuPDF only); Markdown front matter from SCInsight; stable chunk ids | `tests/unit/test_shared_packages.py` |
| Front-matter document metadata, injection detector, role/scope filters, citation shape | SC `scinsight/rag.py` | Ported into `ifad_rag` | SQLAlchemy + pgvector; scope (tenant/domain/project/application) filtering **before** ranking; flagged chunks excluded from LLM context | `tests/security/test_security.py` |
| Hash bag-of-words embedder (offline, deterministic) | SC `scinsight/rag.py::HashEmbedder` (+ Banking `_local_hash_embedding`) | Ported | 384 dims, adds bigrams | `tests/unit/test_shared_packages.py` |
| Ollama provider with host fallbacks | Banking `llm_providers/ollama_provider.py` | Ported into `ifad_models` | async httpx with timeouts; `/api/embed` | `tests/unit/test_shared_packages.py` (mocked transport) |
| Amortised payment, DTI bands, "final_decision_allowed = False" | Banking `policy/loan_policy.py` | **Vendored unchanged** in `ifad_credit_adapter/vendor/` behind `CreditPolicyAdapter` | none to source; adapter converts Decimal ↔ float | `tests/unit/test_credit_adapter.py` (cross-check vs Decimal engine) |
| Per-domain reviewer authority | SC `scinsight/security.py::REVIEW_AUTHORITY` | Pattern reused in `ifad_review` | finance/project domains; segregation of duties (creator ≠ reviewer) | `tests/integration/test_api.py` |
| Forecast evaluation (holdout, naive baseline, WAPE/bias/MAE) | SC `app/forecasting.py::_errors` | **Vendored** in `ifad_supplychain_adapter/vendor/` | none; used for spending-velocity forecast evaluation | `tests/unit/test_shared_packages.py` |
| SVG charts (bar, line, stacked) with table view | SC `frontend/charts.js` | **Not reused**: the portal needs two small charts, drawn inline | none | manual UI check |
| Flowise Agentflow generator / exports | Banking `flowise_project/agentflows/` | **Not reused**: the POC was kept simple; agent identity is shown with scoped agent tokens (`POST /api/v1/agents/runs`) | none | `tests/security/test_security.py` |
| LangGraph mirror | SC `backend/scinsight/lg/` | **Not reused**: a deterministic Python orchestrator is enough for the briefing tools | none | n/a |
| Connectors (S3, SharePoint …) | Banking `connectors/` | Not reused (out of scope; mostly placeholders) | n/a | n/a |
| Retail-credit domain (DTI/LTV-based recommendation) | Banking | Not reused for decisions: it is salaried-borrower logic | Agricultural cash-flow engine written new | `tests/unit/test_cashflow.py` |

## 4. What is built new

Neither repository provides any of the following, so they are written from scratch: the agricultural seasonal cash-flow engine, yield/price/cost/delay scenarios, agricultural risk flags, the project registry, milestones, EVM budget monitoring, indicators, the project map, Alembic migrations, the multi-service gateway, the model gateway's Azure adapters (contract-tested only), and the portal. The specification also proposed a RAG evaluation set and a delay-probability model; neither was built, because the POC was kept simple.

## 5. Blockers

None for Phases 0–4. Both repositories were accessible locally. Phases 5–6 (Azure) need an Azure subscription, cost approval and Entra app registrations, and nothing billable is provisioned without explicit approval.

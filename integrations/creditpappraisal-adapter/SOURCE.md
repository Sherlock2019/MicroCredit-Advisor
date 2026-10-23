# Source: Banking AI Copilot (CreditpappraisalFlowise)

| Item | Value |
| --- | --- |
| Repository | github.com/Sherlock2019/CreditpappraisalFlowise |
| Commit | d3ff23f5c01ceaab478b1021417f29c592d0ceff |
| Vendored file | `bank-credit-ai-poc/backend/app/policy/loan_policy.py` → `ifad_credit_adapter/vendor/loan_policy.py` (unchanged, provenance header added) |
| Source sha256 | d4ef68e0d5b69863ff61d2c87ed43d2d44c66c7812f59dc78c880007c7d793a7 |
| License | No LICENSE file upstream; same owner as this project |
| Public functions used | `calculate_monthly_payment`, `calculate_dti` |

Ported (adapted, with attribution headers in each file) rather than vendored:

| Upstream file | Here |
| --- | --- |
| `backend/app/auth/principal.py`, `policy.py`, `tokens.py`, `dependencies.py` | `packages/common/ifad_common/security/` |
| `backend/app/correlation.py`, `errors.py` | `packages/common/ifad_common/` |
| `backend/app/services/audit_chain.py`, `audit.py` (redaction) | `packages/audit/ifad_audit/` |
| `backend/app/document_parser.py` | `packages/document-ingestion/ifad_ingestion/` |
| `backend/app/llm_providers/ollama_provider.py` | `packages/model-gateway/ifad_models/providers.py` |

To re-vendor: copy the upstream file, update the header and this table, then run `make test`. `tests/unit/test_credit_adapter.py` fails if the amortisation contract changes.

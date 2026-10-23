"""Seed the demo database with SYNTHETIC finance applications, projects, sites, documents and workflow history.

Runs through the same service functions as the API (audit events, ingestion, embeddings, workflow rules), as the
demo identities in api_gateway/dev_users.py. Workflow history created here is labelled "[seed]" in its reasons.

    python scripts/seed_demo.py              # seed (fails if data exists)
    python scripts/seed_demo.py --if-empty   # no-op when applications already exist (used by docker compose)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "database" / "synthetic-data"
DOCS = DATA / "documents"

from api_gateway.dev_users import DEV_USERS  # noqa: E402
from ifad_audit import append_audit_event  # noqa: E402
from ifad_common.db import new_session  # noqa: E402
from ifad_common.security.policy import permissions_for_roles  # noqa: E402
from ifad_common.security.principal import Principal  # noqa: E402
from ifad_rag import ingest_document  # noqa: E402
from project_impact.models import (  # noqa: E402
    BudgetLine,
    Expenditure,
    FieldReport,
    Indicator,
    Milestone,
    Project,
    ProjectMember,
    ProjectSite,
)
from rural_finance.models import LoanApplication  # noqa: E402
from rural_finance.schemas import ApplicationCreate  # noqa: E402
from rural_finance.services import applications as fin  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

SEED = "[seed] synthetic demo history"


def principal(username: str) -> Principal:
    u = DEV_USERS[username]
    roles = frozenset(u["roles"])
    return Principal(subject=username, kind="human", tenant_id=u["tenant"], roles=roles,
                     permissions=permissions_for_roles(roles), display_name=u["name"])


def markdown_to_pdf(text: str, title: str) -> bytes:
    """Render a synthetic markdown document as a two-page PDF so the PDF parsing path and page citations are exercised."""
    import pymupdf

    body = text.split("---", 2)[-1].strip()
    sections = body.split("\n## ")
    pages = [sections[0] + "".join("\n## " + s for s in sections[1:len(sections) // 2 + 1]),
             "".join("## " + s + "\n" for s in sections[len(sections) // 2 + 1:])]
    doc = pymupdf.open()
    for content in [p for p in pages if p.strip()]:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), content.replace("# ", "").replace("## ", ""), fontsize=10)
    doc.set_metadata({"title": title})
    return doc.tobytes()


def load_document(spec: dict) -> tuple[str, bytes, str]:
    path = DOCS / spec["file"]
    text = path.read_text(encoding="utf-8")
    title = next((ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("title:")), path.stem)
    if spec.get("as_pdf"):
        return f"{path.stem}.pdf", markdown_to_pdf(text, title), title
    return path.name, text.encode("utf-8"), title


# ------------------------------------------------------------------------------------------------------------ finance
def seed_finance(db) -> int:
    spec = json.loads((DATA / "finance_applications.json").read_text(encoding="utf-8"))
    reviewer = principal("kofi.credit")
    for item in spec["applications"]:
        creator = principal(item["created_by"])
        app = fin.create_application(db, creator, ApplicationCreate.model_validate(item["payload"]))
        doc_ids = []
        for d in item["documents"]:
            name, data, title = load_document(d)
            doc, _ = ingest_document(db, creator, domain="finance", scope_id=app.id, filename=name, data=data,
                                     document_type=d["document_type"], title=title, provenance="synthetic")
            doc_ids.append(str(doc.id))
            append_audit_event(db, creator, "document.ingested", subject_type="loan_application", subject_id=str(app.id),
                               details={"document_id": str(doc.id), "document_type": d["document_type"], "seed": True})
        target = item["target_status"]
        path = {"DRAFT": [], "SUBMITTED": ["SUBMITTED"], "ANALYZED": ["SUBMITTED", "ANALYZE"],
                "IN_REVIEW": ["SUBMITTED", "ANALYZE", "IN_REVIEW"],
                "NEEDS_INFORMATION": ["SUBMITTED", "ANALYZE", "IN_REVIEW", "NEEDS_INFORMATION"],
                "APPROVED": ["SUBMITTED", "ANALYZE", "IN_REVIEW", "APPROVED"]}[target]
        for step in path:
            app = fin.get_application(db, app.id)
            if step == "ANALYZE":
                fin.analyze(db, creator, app)
            elif step in {"SUBMITTED", "IN_REVIEW"}:
                fin.transition(db, creator, app, step, SEED, [])
            elif step == "NEEDS_INFORMATION":
                fin.transition(db, reviewer, app, step, f"{SEED}: buyer contracts and yield records requested", [])
            elif step == "APPROVED":
                analysis = fin.latest_analysis(db, app)
                fin.transition(db, reviewer, app, step, f"{SEED}: cash flow covers both instalments; delivery history verified",
                               doc_ids + [f"analysis:{analysis.id}"])
        print(f"  finance  {app.reference:16s} {item['key']:28s} -> {app.status}")
    return len(spec["applications"])


# ----------------------------------------------------------------------------------------------------------- projects
def quarter_label(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def quarter_end(d: date) -> date:
    month = ((d.month - 1) // 3 + 1) * 3
    nxt = date(d.year + (month == 12), 1 if month == 12 else month + 1, 1)
    return nxt - timedelta(days=1)


def quarters(start: date, as_of: date) -> list[tuple[str, date]]:
    out, cur = [], quarter_end(start)
    while cur <= as_of:
        out.append((quarter_label(cur), cur))
        cur = quarter_end(cur + timedelta(days=1))
    return out


def ingest_project_doc(db, who: Principal, project: Project, spec: dict):
    name, data, title = load_document(spec)
    doc, _ = ingest_document(db, who, domain="project", scope_id=project.id, filename=name, data=data,
                             document_type=spec["document_type"], title=title, provenance="synthetic",
                             metadata={"reporting_period": spec.get("reporting_period")})
    append_audit_event(db, who, "document.ingested", subject_type="project", subject_id=str(project.id),
                       details={"document_id": str(doc.id), "document_type": spec["document_type"], "seed": True})
    return doc


def seed_detailed(db, item: dict) -> Project:
    who = principal("ana.project")
    p = dict(item["project"])
    sites = p.pop("sites")
    project = Project(tenant_id=item["tenant"], created_by=who.actor, synthetic=True,
                      **{**p, "start_date": date.fromisoformat(p["start_date"]), "end_date": date.fromisoformat(p["end_date"]),
                         "reporting_as_of": date.fromisoformat(p["reporting_as_of"]), "financing_amount": Decimal(str(p["financing_amount"]))})
    project.sites = [ProjectSite(**s) for s in sites]
    db.add(project)
    db.flush()
    docs = {key: ingest_project_doc(db, who, project, spec) for key, spec in item["documents"].items()}
    d = date.fromisoformat
    for m in item["milestones"]:
        db.add(Milestone(project_id=project.id, activity_code=m["activity_code"], title=m["title"], component=m["component"],
                         planned_start=d(m["planned_start"]), planned_end=d(m["planned_end"]),
                         actual_start=d(m["actual_start"]) if m.get("actual_start") else None,
                         actual_end=d(m["actual_end"]) if m.get("actual_end") else None,
                         planned_progress_pct=m["planned_progress_pct"], actual_progress_pct=m["actual_progress_pct"],
                         weight_pct=m["weight_pct"], responsible_unit=m["responsible_unit"], status=m["status"],
                         evidence_document_id=docs[m["evidence"]].id if m.get("evidence") else None))
    for b in item["budget"]:
        db.add(BudgetLine(project_id=project.id, currency=project.currency, reporting_period_end=d(item["budget_period_end"]), **b))
    periods = item["expenditures"]["periods"]
    for component, amounts in item["expenditures"].items():
        if component == "periods":
            continue
        for label, amount in zip(periods, amounts, strict=True):
            year, q = label.split("-Q")
            db.add(Expenditure(project_id=project.id, component=component, period_label=label, currency=project.currency,
                               period_end=quarter_end(date(int(year), int(q) * 3, 1)), amount=amount))
    for ind in item["indicators"]:
        evidence = ind.pop("evidence", None)
        db.add(Indicator(project_id=project.id, source_document_id=docs[evidence].id if evidence else None, **ind))
    for r in item["reports"]:
        evidence = r.get("evidence")
        db.add(FieldReport(project_id=project.id, report_type=r["report_type"], period_label=r["period_label"],
                           due_date=d(r["due_date"]), received_date=d(r["received_date"]) if r["received_date"] else None,
                           document_id=docs[evidence].id if evidence else None))
    return project


C2_NAMES = {"cooperatives": "C2 Cooperative support and equipment grants", "market_access": "C2 Producer groups and market linkages",
            "rural_finance": "C2 Financial products and literacy"}


def seed_compact(db, item: dict) -> Project:
    owner = "bea.tenantb" if item["tenant"] == "tenant-demo-b" else "ana.project"
    who = principal(owner)
    rng = random.Random(item["seed"])
    start, end, as_of = (date.fromisoformat(item[k]) for k in ("start", "end", "as_of"))
    budget = Decimal(str(item["budget"]))
    project = Project(tenant_id=item["tenant"], code=item["code"], name=item["name"],
                      programme_name="Demo Rural Transformation Portfolio", theme=item["theme"], country=item["country"],
                      objectives=item["objectives"], expected_results=[f"Targets defined in the synthetic results framework for {item['code']}"],
                      baseline_summary="Synthetic baseline values; see indicators.", implementing_organization=item["org"],
                      start_date=start, end_date=end, reporting_as_of=as_of, financing_amount=budget, currency="USD",
                      created_by=who.actor, synthetic=True)
    for s in item["sites"]:
        target = rng.randrange(800, 3200, 50)
        reached = int(target * item["actual_pct"] / 100 * rng.uniform(0.85, 1.15))
        project.sites.append(ProjectSite(country=item["country"], beneficiaries_target=target, beneficiaries_reached=reached, **s))
    db.add(project)
    db.flush()
    docs = [ingest_project_doc(db, who, project, spec) for spec in item.get("documents", [])]

    span = (end - start).days
    at = lambda f: start + timedelta(days=int(span * f))  # noqa: E731
    weights = [15, 25, 25, 20, 15]
    windows = [(0, .2), (.15, .6), (.3, .8), (.5, 1.0), (.1, .9)]
    titles = ["Inception, baseline and design", "Community mobilisation and group formation", "Main investments (works and equipment)",
              "Scale-up and second-phase investments", "Training and capacity building"]
    rest_planned = (item["planned_pct"] * 100 - 1500) / 85
    rest_actual = (item["actual_pct"] * 100 - 1500) / 85
    planned_var, actual_var = [0, 6, -2, -5, 0], [0, 4, -4, 3, -4]
    missing_evidence_last = item.get("missing_reports", 0) >= 2
    for i in range(5):
        planned = 100.0 if i == 0 else max(0.0, min(100.0, rest_planned + planned_var[i]))
        actual = 100.0 if i == 0 else max(0.0, min(planned, rest_actual + actual_var[i]))
        ps, pe = at(windows[i][0]), at(windows[i][1])
        has_progress = actual > 0
        evidence = None
        if has_progress and not (missing_evidence_last and i == 4):
            text = (f"---\ntitle: {item['code']} activity record {i + 1}\nprovenance: synthetic\n---\n"
                    f"# {item['code']} activity record {i + 1}\n\nSYNTHETIC DOCUMENT generated by the demo seed.\n\n"
                    f"## Activity\n{titles[i]} for the {item['name']} reached about {actual:.0f} percent of the activity scope "
                    f"by {as_of:%B %Y}, against {planned:.0f} percent planned. Site visits were made in "
                    f"{', '.join(s['city'] for s in item['sites'])}.\n")
            doc, _ = ingest_document(db, who, domain="project", scope_id=project.id, filename=f"activity_record_{i + 1}.md",
                                     data=text.encode(), document_type="evidence_record", provenance="synthetic")
            evidence = doc.id
        db.add(Milestone(project_id=project.id, activity_code=f"A-{i + 1}", title=titles[i],
                         component=["C1 Investments and infrastructure", C2_NAMES.get(item["theme"], "C2 Producer support"),
                                    "C3 Management and M&E"][min(i, 2) if i < 4 else 1],
                         planned_start=ps, planned_end=pe, actual_start=ps + timedelta(days=rng.randrange(0, 60)) if has_progress else None,
                         actual_end=pe if actual >= 100 else None, planned_progress_pct=round(planned, 2),
                         actual_progress_pct=round(actual, 2), weight_pct=weights[i], responsible_unit="Project management unit",
                         status="completed" if actual >= 100 else "in_progress" if has_progress else "not_started",
                         evidence_document_id=evidence))

    spent_total = budget * Decimal(str(item["actual_pct"])) / 100 * Decimal(str(item["spend_ratio"]))
    shares = [Decimal("0.55"), Decimal("0.30"), Decimal("0.15")]
    names = ["C1 Investments and infrastructure", C2_NAMES.get(item["theme"], "C2 Producer support"), "C3 Management and M&E"]
    qs = quarters(start, as_of)
    for idx, (name, share) in enumerate(zip(names, shares, strict=True)):
        comp_budget = (budget * share).quantize(Decimal("1"))
        actual = (spent_total * share).quantize(Decimal("1"))
        committed = min(actual * Decimal("1.35"), comp_budget * Decimal("0.95")).quantize(Decimal("1"))
        if item.get("overspend_component") and idx == 1:
            actual, committed = (comp_budget * Decimal("1.08")).quantize(Decimal("1")), (comp_budget * Decimal("1.12")).quantize(Decimal("1"))
        db.add(BudgetLine(project_id=project.id, component=name, currency="USD", budget_amount=comp_budget,
                          committed_amount=max(committed, actual), actual_expenditure=actual, reporting_period_end=as_of))
        ramp = [Decimal(k + 1) for k in range(len(qs))]
        total_ramp = sum(ramp)
        allocated = Decimal(0)
        for k, (label, q_end) in enumerate(qs):
            amount = actual - allocated if k == len(qs) - 1 else (actual * ramp[k] / total_ramp).quantize(Decimal("1"))
            allocated += amount
            db.add(Expenditure(project_id=project.id, component=name, period_label=label, period_end=q_end, amount=amount, currency="USD"))

    farmers_target = sum(s.beneficiaries_target for s in project.sites)
    farmers_reached = sum(s.beneficiaries_reached for s in project.sites)
    linked = docs[0].id if docs else None
    db.add(Indicator(project_id=project.id, code="IND-01", name="Farmers receiving programme services", level="output", unit="persons",
                     definition="Unique farmers who received at least one programme service.", baseline_value=0,
                     target_value=farmers_target, reported_actual=farmers_reached, reporting_period=quarter_label(as_of),
                     data_source="Quarterly progress report", verification_status="partially_verified", source_document_id=linked))
    sites_target = len(project.sites) * 10
    db.add(Indicator(project_id=project.id, code="IND-02", name="Investments operational", level="output", unit="units",
                     definition="Infrastructure or equipment units certified operational.", baseline_value=0, target_value=sites_target,
                     reported_actual=round(sites_target * item["actual_pct"] / 100 * rng.uniform(0.7, 1.1)),
                     reporting_period=quarter_label(as_of), data_source="Engineering certification log",
                     verification_status=rng.choice(["verified", "unverified"])))
    db.add(Indicator(project_id=project.id, code="IND-03", name="Participants reporting improved practices", level="outcome",
                     unit="% of participants", definition="Share of surveyed participants applying at least two promoted practices.",
                     baseline_value=10, target_value=60, reported_actual=round(10 + 50 * item["actual_pct"] / 100 * rng.uniform(0.6, 1.0), 1),
                     reporting_period=str(as_of.year), data_source="Annual outcome survey (synthetic sample)",
                     verification_status="unverified", quality_note="Self-reported practices; small sample."))

    due_reports = [(lbl, q_end + timedelta(days=30)) for lbl, q_end in qs if q_end + timedelta(days=30) <= as_of]
    missing = {lbl for lbl, _ in due_reports[-item.get("missing_reports", 0):]} if item.get("missing_reports") else set()
    for lbl, q_end in qs:
        due = q_end + timedelta(days=30)
        received = None if lbl in missing or due > as_of else due - timedelta(days=rng.randrange(0, 10))
        db.add(FieldReport(project_id=project.id, report_type="quarterly_progress", period_label=lbl, due_date=due, received_date=received))
    return project


def seed_projects(db) -> int:
    spec = json.loads((DATA / "projects.json").read_text(encoding="utf-8"))
    by_code = {}
    for item in spec["detailed"]:
        p = seed_detailed(db, item)
        by_code[p.code] = p
    for item in spec["compact"]:
        p = seed_compact(db, item)
        by_code[p.code] = p
    db.flush()
    for username, codes in spec["members"].items():
        role = DEV_USERS[username]["roles"][-1]
        for code in codes:
            db.add(ProjectMember(project_id=by_code[code].id, subject=username, project_role=role, added_by="seed"))
    for p in by_code.values():
        append_audit_event(db, principal("ana.project" if p.tenant_id == "tenant-demo-a" else "bea.tenantb"), "project.created",
                           subject_type="project", subject_id=str(p.id), details={"code": p.code, "seed": True})
        print(f"  project  {p.code:16s} {p.country:12s} sites={len(p.sites)}")
    return len(by_code)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-empty", action="store_true")
    args = parser.parse_args()
    db = new_session()
    try:
        existing = db.execute(select(func.count()).select_from(LoanApplication)).scalar_one()
        if existing:
            print(f"database already holds {existing} applications; " + ("skipping seed" if args.if_empty else "refusing to seed twice"))
            return 0 if args.if_empty else 1
        print("Seeding SYNTHETIC demo data ...")
        n_fin = seed_finance(db)
        n_prj = seed_projects(db)
        db.commit()
        print(f"Seeded {n_fin} finance applications and {n_prj} projects.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

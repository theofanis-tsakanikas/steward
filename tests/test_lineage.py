import json
import shutil

from steward import io, pipeline
from steward.adapters.looker import parse
from steward.core.lineage import resolve

JOBS = json.loads((io.REPO / "evals/lineage/query_history.json").read_text())["jobs"]


def codes(findings):
    return {(f.code, f.target) for f in findings if f.blocking}


def test_fields_resolve_through_references_and_filters():
    views = parse(io.REPO / "lookml")["views"]
    cols, bad = resolve(views, "customers", "active_customers")
    assert bad == [] and cols == {"crm.customers.customer_id", "crm.customers.contracts"}
    cols, _ = resolve(views, "billing", "total_amount")
    assert cols == {"finance.billing.amount"}


def test_clean_estate_is_green():
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", JOBS)
    assert codes(findings) == set()


def test_masked_sensitive_column_on_a_dashboard_is_fine_and_recorded():
    _, (_, _, detail) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", JOBS)
    row = next(r for r in detail["dashboards"]["customer_overview"] if r["field"] == "customers.msisdn")
    assert row["as_seen_by"]["bi_service"]["crm.customers.msisdn"] == "SHA256"


def test_a_view_on_an_uncontracted_table_is_unresolved(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    v = root / "views" / "legacy.view.lkml"
    v.write_text(
        "view: legacy {\n  sql_table_name: `legacy.legacy_crm_export` ;;\n  dimension: tel { sql: ${TABLE}.tel_a ;; }\n}\n"
    )
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), root, JOBS)
    assert ("UNRESOLVED_FIELD", "view:legacy") in codes(findings)


def test_dashboard_with_no_history_is_reported_not_blocking():
    jobs = [j for j in JOBS if (j.get("labels") or {}).get("looker_dashboard") != "legacy_churn"]
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", jobs)
    assert any(f.code == "LINEAGE_UNOBSERVED" and f.target == "legacy_churn" and not f.blocking for f in findings)


def test_glossary_conflict_names_both_definitions():
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", JOBS)
    g = [f for f in findings if f.code == "GLOSSARY_CONFLICT"]
    assert len(g) == 1 and "billing.active_customers" in g[0].message and "customers.active_customers" in g[0].message

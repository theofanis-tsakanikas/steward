import copy
import json
import shutil

import pytest

from steward import io, pipeline
from steward.adapters.looker import parse
from steward.core.lineage import resolve

HISTORY = json.loads((io.REPO / "evals/lineage/query_history.json").read_text())
JOBS = HISTORY["jobs"]


def codes(findings):
    return {(f.code, f.target) for f in findings if f.blocking}


def test_fields_resolve_through_references_and_filters():
    views = parse(io.REPO / "lookml")["views"]
    tc = _table_columns()
    cols, bad = resolve(views, "customers", "active_customers", tc)
    assert bad == [] and cols == {"crm.customers.customer_id", "crm.customers.contracts"}
    cols, _ = resolve(views, "billing", "total_amount", tc)
    assert cols == {"finance.billing.amount"}


def test_clean_estate_is_green():
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", HISTORY)
    assert codes(findings) == set()


def test_masked_sensitive_column_on_a_dashboard_is_fine_and_recorded():
    _, (_, _, detail) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", HISTORY)
    row = next(r for r in detail["dashboards"]["customer_overview"] if r["field"] == "customers.msisdn")
    assert row["role"] == "bi_service" and row["as_seen"]["crm.customers.msisdn"] == "SHA256"


def test_a_view_on_an_uncontracted_table_is_unresolved(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    v = root / "views" / "legacy.view.lkml"
    v.write_text(
        "view: legacy {\n  sql_table_name: `legacy.legacy_crm_export` ;;\n  dimension: tel { sql: ${TABLE}.tel_a ;; }\n}\n"
    )
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), root, HISTORY)
    assert ("UNRESOLVED_FIELD", "view:legacy") in codes(findings)


def test_dashboard_with_no_history_is_reported_not_blocking():
    jobs = [j for j in JOBS if (j.get("labels") or {}).get("looker_dashboard") != "legacy_churn"]
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", dict(HISTORY, jobs=jobs))
    assert any(f.code == "LINEAGE_UNOBSERVED" and f.target == "legacy_churn" and not f.blocking for f in findings)


def test_glossary_conflict_names_both_definitions():
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", HISTORY)
    g = [f for f in findings if f.code == "GLOSSARY_CONFLICT"]
    assert len(g) == 1 and "billing.active_customers" in g[0].message and "customers.active_customers" in g[0].message


def _table_columns():
    out = {}
    for c in pipeline.load().contracts:
        for fqn, _, _, _ in c.iter_columns():
            ds, t, path = fqn.split(".", 2)
            out.setdefault(f"{ds}.{t}", set()).add(path)
    return out


def _with_view(tmp_path, dim_sql: str):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    v = root / "views" / "customers.view.lkml"
    v.write_text(v.read_text().replace("sql: ${TABLE}.msisdn ;;", f"sql: {dim_sql} ;;"))
    return root


@pytest.mark.parametrize(
    "sql", ["msisdn", "customers.msisdn", "(SELECT c.msisdn FROM `crm.customers` c)", "'constant'"]
)
def test_sql_without_table_refs_fails_closed_or_resolves(tmp_path, sql):
    root = _with_view(tmp_path, sql)
    _, (findings, _, detail) = pipeline.lineage(pipeline.load(), root, HISTORY)
    blocking = {(f.code, f.target) for f in findings if f.blocking}
    if sql == "msisdn":
        row = next(r for r in detail["dashboards"]["customer_overview"] if r["field"] == "customers.msisdn")
        assert row["columns"] == ["crm.customers.msisdn"]  # a bare column name is resolved, then judged
    else:
        assert ("UNRESOLVED_FIELD", "customer_overview/callers_with_most_tickets/customers.msisdn") in blocking


def test_a_record_read_whole_is_judged_leaf_by_leaf(tmp_path):
    root = _with_view(tmp_path, "TO_JSON_STRING(${TABLE}.address)")
    _, (_, _, detail) = pipeline.lineage(pipeline.load(), root, HISTORY)
    row = next(r for r in detail["dashboards"]["customer_overview"] if r["field"] == "customers.msisdn")
    assert set(row["as_seen"]) == {
        "crm.customers.address.street",
        "crm.customers.address.city",
        "crm.customers.address.postcode",
    }


def test_a_denied_column_is_a_failing_tile(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    v = root / "views" / "support_tickets.view.lkml"
    v.write_text(
        v.read_text().replace(
            "  dimension: channel {", "  dimension: callback {\n    sql: ${TABLE}.ref_2 ;;\n  }\n  dimension: channel {"
        )
    )
    d = root / "dashboards" / "customer_overview.dashboard.lookml"
    d.write_text(
        d.read_text().replace(
            "fields: [support_tickets.category, support_tickets.count]",
            "fields: [support_tickets.category, support_tickets.callback]",
        )
    )
    docs = copy.deepcopy(io.contract_docs())
    del docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"]["masking"]["bi_service"]
    _, (findings, _, _) = pipeline.lineage(pipeline.load(contract_docs=docs), root, HISTORY)
    assert ("DASHBOARD_FIELD_DENIED", "customer_overview/tickets_by_category/support_tickets.callback") in {
        (f.code, f.target) for f in findings
    }


def test_dashboard_filters_and_sorts_are_resolved(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    d = root / "dashboards" / "legacy_churn.dashboard.lookml"
    d.write_text(d.read_text() + "    filters: {customers.nope: 'x'}\n    sorts: [customers.ghost desc]\n")
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), root, HISTORY)
    targets = {f.target for f in findings if f.code == "UNRESOLVED_FIELD"}
    assert {
        "legacy_churn/tickets_by_segment/customers.nope",
        "legacy_churn/tickets_by_segment/customers.ghost",
    } <= targets


def test_old_history_falls_out_of_the_window():
    old = dict(
        HISTORY,
        jobs=[
            dict(j, creation_time="2026-01-01T00:00:00Z") if (j.get("labels") or {}).get("looker_dashboard") else j
            for j in JOBS
        ],
    )
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", old)
    assert {f.code for f in findings if f.target == "customer_overview"} == {"LINEAGE_UNOBSERVED"}


def test_hashed_identifier_on_a_dashboard_is_flagged_as_pseudonymised():
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", HISTORY)
    assert any(f.code == "PSEUDONYMISED_ID_ON_DASHBOARD" and not f.blocking for f in findings)


def test_unsupported_lookml_is_refused(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    (root / "views" / "ext.view.lkml").write_text(
        "view: ext {\n  extends: [customers]\n  sql_table_name: `crm.customers` ;;\n}\n"
    )
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), root, HISTORY)
    assert any(f.code == "UNSUPPORTED_LOOKML" for f in findings)


@pytest.mark.parametrize(
    "sql,ok",
    [
        ("{{ customers.msisdn._sql }}", False),
        ("${TABLE}.{% parameter pick %}", False),
        ("CONCAT(${TABLE}.country, MSISDN)", True),  # case-insensitive: resolves to msisdn and is judged
        ("CONCAT(${TABLE}.country, imsi_new)", False),
        ("CONCAT(${TABLE}.country, TO_JSON_STRING(${TABLE}))", False),
    ],
)
def test_resolver_closure_cases(tmp_path, sql, ok):
    root = _with_view(tmp_path, sql)
    _, (findings, _, detail) = pipeline.lineage(pipeline.load(), root, HISTORY)
    unresolved = ("UNRESOLVED_FIELD", "customer_overview/callers_with_most_tickets/customers.msisdn") in {
        (f.code, f.target) for f in findings if f.blocking
    }
    assert unresolved is (not ok)
    if ok:
        row = next(r for r in detail["dashboards"]["customer_overview"] if r["field"] == "customers.msisdn")
        assert "crm.customers.msisdn" in row["columns"]


def test_merged_queries_listen_based_on_and_unscoped_filters(tmp_path):
    root = tmp_path / "lookml"
    shutil.copytree(io.REPO / "lookml", root)
    d = root / "dashboards" / "legacy_churn.dashboard.lookml"
    d.write_text(
        d.read_text()
        + "    listen: {Who: customers.ghost_listen}\n"
        + "    dynamic_fields: [{table_calculation: x, based_on: customers.ghost_based}]\n"
        + "  - name: merged\n    merged_queries:\n    - {model: steward, explore: customers, fields: [customers.ghost_merged]}\n"
        + "  filters:\n  - {name: f, field: nosuchview.nosuchfield}\n"
    )
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), root, HISTORY)
    t = {f.target for f in findings if f.code == "UNRESOLVED_FIELD"}
    assert {
        "legacy_churn/tickets_by_segment/customers.ghost_listen",
        "legacy_churn/tickets_by_segment/customers.ghost_based",
        "legacy_churn/merged[0]/customers.ghost_merged",
        "legacy_churn/filter/nosuchview.nosuchfield",
    } <= t


@pytest.mark.parametrize("created", [None, "2027-01-01T00:00:00Z"])
def test_undated_or_future_history_is_refused(created):
    jobs = [dict(j) for j in JOBS]
    j = next(x for x in jobs if (x.get("labels") or {}).get("looker_dashboard") == "network_usage")
    if created is None:
        j.pop("creation_time")
    else:
        j["creation_time"] = created
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", dict(HISTORY, jobs=jobs))
    assert ("LINEAGE_HISTORY_INVALID", j["job_id"]) in {(f.code, f.target) for f in findings if f.blocking}


def test_a_table_with_no_path_to_a_source_is_untraced():
    jobs = [j for j in JOBS if j["job_id"] != "load-finance-billing"]
    _, (findings, _, _) = pipeline.lineage(pipeline.load(), io.REPO / "lookml", dict(HISTORY, jobs=jobs))
    assert ("LINEAGE_UNTRACED", "billing_health:finance.billing") in {
        (f.code, f.target) for f in findings if f.blocking
    }

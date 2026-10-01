from steward import io, pipeline
from steward.core import retention


def gate(docs=None):
    e = pipeline.load(contract_docs=docs)
    return {
        (f.code, f.target)
        for f in retention.gate(
            e.contracts,
            e.compiled["infra/estate/generated.tf.json"],
            e.compiled["infra/governance/generated.tf.json"],
            e.harvest,
        )
    }


def test_committed_is_green():
    assert gate() == set()


def test_report_opens_with_the_caveat():
    e = pipeline.load()
    r = retention.report(e.contracts, e.harvest, [])
    assert r["caveat"].startswith("Deletion is not immediate") and "9 days" in r["caveat"]


def test_repeated_column_compiles_not_exists_over_unnest():
    e = pipeline.load()
    sql = next(x["mechanism"]["sql"] for x in retention.plan(e.contracts, e.harvest) if x["table"] == "customers")
    assert "NOT EXISTS" in sql and "UNNEST(contracts)" in sql and "INTERVAL 2555 DAY" in sql


def test_table_override_is_compiled():
    e = pipeline.load()
    t = next(
        n
        for n in e.compiled["infra/estate/generated.tf.json"]["resource"]["google_bigquery_table"].values()
        if n["table_id"] == "network_events"
    )
    assert t["time_partitioning"]["expiration_ms"] == 90 * 86_400_000


def test_legacy_is_listed_with_its_waiver():
    e = pipeline.load()
    r = retention.report(e.contracts, e.harvest, io.waivers_doc()["waivers"])
    legacy = [x for x in r["rows"] if x["dataset"] == "legacy"]
    assert len(legacy) == 1 and "W-001" in legacy[0]["status"]


def test_custodian_must_be_a_service_account_in_terraform():
    e = pipeline.load()
    vals = e.compiled["infra/governance/generated.tf.json"]["variable"]["principals"]["validation"]
    assert any("serviceAccount:" in v["condition"] and "data-platform" in v["condition"] for v in vals)

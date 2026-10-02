"""Running the Dataplex scans and keeping each rule's counts."""

from __future__ import annotations

from steward.adapters import dataplex as dp


def _job(state="SUCCEEDED"):
    return {
        "state": state,
        "dataQualityResult": {
            "passed": False,
            "rowCount": "600",
            "rules": [
                {
                    "rule": {"name": "cust-001", "column": "country", "dimension": "VALIDITY", "threshold": 1},
                    "passed": False,
                    "evaluatedCount": "600",
                    "passedCount": "597",
                    "nullCount": "0",
                },
                {
                    "rule": {"name": "cust-002", "column": "email", "dimension": "COMPLETENESS", "threshold": 1},
                    "passed": True,
                    "evaluatedCount": "600",
                    "passedCount": "600",
                },
            ],
        },
    }


def test_the_counts_are_kept_per_rule_as_numbers():
    s = dp.summarize_job("scan-a", _job())
    assert s["rows_scanned"] == 600 and s["passed"] is False
    first = s["rules"][0]
    assert (first["rule"], first["evaluated"], first["failed_rows"], first["null_rows"]) == ("cust-001", 600, 3, 0)
    assert s["rules"][1]["failed_rows"] == 0 and s["rules"][1]["null_rows"] is None


def test_every_scan_is_started_then_polled_until_it_ends():
    calls, states = [], iter(["RUNNING", "SUCCEEDED"])

    def call(method, url, body):
        calls.append((method, url))
        if method == "POST":
            return {
                "job": {
                    "name": f"projects/p/locations/eu/dataScans/{url.split('/dataScans/')[1].split(':')[0]}/jobs/j1"
                }
            }
        return {**_job(), "state": next(states)} if "scan-a" in url else _job()

    out = dp.run_scans(call, "p", "eu", ["scan-a", "scan-b"], sleep=lambda _: None)
    assert [o["scan"] for o in out] == ["scan-a", "scan-b"]
    assert [m for m, _ in calls[:2]] == ["POST", "POST"]
    assert all(o["state"] == "SUCCEEDED" for o in out)


def test_a_scan_that_never_ends_is_recorded_as_timed_out_not_dropped():
    t = iter(range(0, 10_000, 100))

    def call(method, url, body):
        return (
            {"job": {"name": "projects/p/locations/eu/dataScans/x/jobs/j"}}
            if method == "POST"
            else {"state": "RUNNING"}
        )

    out = dp.run_scans(call, "p", "eu", ["x"], timeout=250, sleep=lambda _: None, clock=lambda: next(t))
    assert out[0]["state"] == "TIMED_OUT" and out[0]["rules"] == []


def test_a_failed_scan_keeps_its_message():
    out = dp.summarize_job("s", {"state": "FAILED", "message": "permission denied on the table"})
    assert out["state"] == "FAILED" and "permission" in out["message"] and out["rules"] == []

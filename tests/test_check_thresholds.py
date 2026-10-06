import csv
import json

import pytest

from tools import check_thresholds as ct


def row(key, requests=100, failures=0, p95=100):
    return ct.Row(key=key, requests=requests, failures=failures, p95_ms=p95)


GOOD = [row("GET /products", p95=120), row("POST /orders", p95=300), row("Aggregated", requests=200, p95=250)]


def test_run_within_all_targets_has_no_violations():
    thresholds = {"max_failure_rate": 0.01, "default_p95_ms": 500, "endpoints": {"GET /products": {"p95_ms": 200}}}
    assert ct.evaluate(GOOD, thresholds) == []


def test_slow_endpoint_uses_its_own_limit():
    thresholds = {"default_p95_ms": 1000, "endpoints": {"GET /products": {"p95_ms": 100}}}
    violations = ct.evaluate(GOOD, thresholds)
    assert violations == ["GET /products: p95 120 ms is above 100 ms"]


def test_endpoint_without_entry_falls_back_to_default_limit():
    thresholds = {"default_p95_ms": 200, "endpoints": {}}
    violations = ct.evaluate(GOOD, thresholds)
    assert any("POST /orders: p95 300 ms is above 200 ms" in v for v in violations)


def test_overall_failure_rate_is_checked():
    rows = [row("GET /products", requests=100, failures=0), row("Aggregated", requests=100, failures=5)]
    violations = ct.evaluate(rows, {"max_failure_rate": 0.01})
    assert len(violations) == 1 and "overall failure rate 5.00%" in violations[0]


def test_failure_rate_is_checked_per_endpoint_even_when_overall_rate_is_fine():
    rows = [row("GET /products", requests=1000), row("POST /orders", requests=50, failures=10),
            row("Aggregated", requests=1050, failures=10)]
    violations = ct.evaluate(rows, {"max_failure_rate": 0.02})
    assert violations == ["POST /orders: failure rate 20.00% is above 2.00%"]


def test_run_that_is_too_short_does_not_pass_vacuously():
    rows = [row("GET /products", requests=3), row("Aggregated", requests=3)]
    violations = ct.evaluate(rows, {"min_total_requests": 100})
    assert violations == ["only 3 requests were made, at least 100 are needed for a meaningful result"]


def test_threshold_for_an_endpoint_that_was_never_called_is_reported():
    violations = ct.evaluate(GOOD, {"endpoints": {"GET /renamed-endpoint": {"p95_ms": 100}}})
    assert violations == ["thresholds refer to endpoints that were never called: GET /renamed-endpoint"]


def test_missing_aggregated_row_is_an_error():
    assert ct.evaluate([row("GET /products")], {}) == ["no 'Aggregated' row in the statistics file"]


def write_stats(path, rows):
    header = ["Type", "Name", "Request Count", "Failure Count", "95%"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_load_stats_reads_locust_csv_and_builds_endpoint_keys(tmp_path):
    stats = tmp_path / "run_stats.csv"
    write_stats(stats, [["GET", "/products", 10, 1, 85], ["", "Aggregated", 10, 1, 85]])

    rows = ct.load_stats(stats)

    assert [r.key for r in rows] == ["GET /products", "Aggregated"]
    assert rows[0].failure_rate == pytest.approx(0.1)
    assert rows[0].p95_ms == 85


def test_main_exit_code_is_one_when_thresholds_are_missed(tmp_path, capsys):
    stats = tmp_path / "run_stats.csv"
    write_stats(stats, [["GET", "/products", 200, 0, 900], ["", "Aggregated", 200, 0, 900]])
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"default_p95_ms": 500}))

    assert ct.main([str(stats), str(thresholds)]) == 1
    assert "THRESHOLDS MISSED" in capsys.readouterr().out


def test_main_exit_code_is_zero_when_all_targets_are_met(tmp_path, capsys):
    stats = tmp_path / "run_stats.csv"
    write_stats(stats, [["GET", "/products", 200, 0, 50], ["", "Aggregated", 200, 0, 50]])
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"default_p95_ms": 500, "min_total_requests": 100}))

    assert ct.main([str(stats), str(thresholds)]) == 0
    assert "All thresholds met" in capsys.readouterr().out

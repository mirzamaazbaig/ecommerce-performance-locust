"""
Fail the build when a load test misses its targets.

Reads the statistics CSV that Locust writes (--csv results/run gives results/run_stats.csv) and a thresholds
file, and exits with status 1 when any target is missed. Targets:

  max_failure_rate      overall share of failed requests, and the same limit per endpoint
  min_total_requests    guards against a run that was too short to mean anything
  default_p95_ms        95th percentile limit for endpoints without their own entry
  endpoints             per endpoint {"p95_ms": ...}, keyed like "GET /products"
"""
import argparse
import csv
import json
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    key: str          # "GET /products", or "Aggregated"
    requests: int
    failures: int
    p95_ms: float

    @property
    def failure_rate(self):
        return self.failures / self.requests if self.requests else 0.0


def load_stats(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            name = record["Name"]
            key = "Aggregated" if name == "Aggregated" else f"{record['Type']} {name}"
            rows.append(Row(
                key=key,
                requests=int(record["Request Count"]),
                failures=int(record["Failure Count"]),
                p95_ms=float(record["95%"]),
            ))
    return rows


def evaluate(rows, thresholds):
    """Return a list of human-readable violations (empty when everything is within its targets)."""
    violations = []
    max_failure_rate = thresholds.get("max_failure_rate", 0.01)
    default_p95 = thresholds.get("default_p95_ms", 1000)
    per_endpoint = thresholds.get("endpoints", {})

    aggregated = next((r for r in rows if r.key == "Aggregated"), None)
    if aggregated is None:
        return ["no 'Aggregated' row in the statistics file"]

    minimum = thresholds.get("min_total_requests", 0)
    if aggregated.requests < minimum:
        violations.append(f"only {aggregated.requests} requests were made, at least {minimum} are needed for a meaningful result")

    if aggregated.failure_rate > max_failure_rate:
        violations.append(
            f"overall failure rate {aggregated.failure_rate:.2%} is above {max_failure_rate:.2%} "
            f"({aggregated.failures} of {aggregated.requests})"
        )

    for row in rows:
        if row.key == "Aggregated" or row.requests == 0:
            continue
        limit = per_endpoint.get(row.key, {}).get("p95_ms", default_p95)
        if row.p95_ms > limit:
            violations.append(f"{row.key}: p95 {row.p95_ms:.0f} ms is above {limit} ms")
        if row.failure_rate > max_failure_rate:
            violations.append(f"{row.key}: failure rate {row.failure_rate:.2%} is above {max_failure_rate:.2%}")

    unknown = sorted(set(per_endpoint) - {r.key for r in rows})
    if unknown:
        violations.append(f"thresholds refer to endpoints that were never called: {', '.join(unknown)}")
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stats_csv", help="Locust *_stats.csv file")
    parser.add_argument("thresholds_json", help="thresholds file, see thresholds.json")
    args = parser.parse_args(argv)

    with open(args.thresholds_json, encoding="utf-8") as handle:
        thresholds = json.load(handle)
    rows = load_stats(args.stats_csv)

    print(f"{'endpoint':45} {'requests':>9} {'failures':>9} {'p95 ms':>8}")
    for row in rows:
        print(f"{row.key:45} {row.requests:9d} {row.failures:9d} {row.p95_ms:8.0f}")

    violations = evaluate(rows, thresholds)
    if violations:
        print("\nTHRESHOLDS MISSED")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("\nAll thresholds met")
    return 0


if __name__ == "__main__":
    sys.exit(main())

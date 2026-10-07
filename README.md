# E-Commerce API Load Tests: Python and Locust

[![Load test](https://github.com/mirzamaazbaig/ecommerce-performance-locust/actions/workflows/load-test.yml/badge.svg)](https://github.com/mirzamaazbaig/ecommerce-performance-locust/actions/workflows/load-test.yml)

Load and performance tests for the REST API of a React, Express and PostgreSQL online shop, written in Python with [Locust](https://locust.io). A run simulates a realistic mix of visitors, validates every response, and then **fails the build automatically** if the latency or error targets in [`thresholds.json`](thresholds.json) are missed.

It complements the functional suites for the same API ([Playwright](https://github.com/mirzamaazbaig/Ecom), Newman, Selenium) with the non-functional side.

## What it does

- **Two user types, weighted like real traffic:** `BrowseUser` (70%) is an anonymous visitor who lists, filters, searches, sorts and opens products and reads reviews. `ShopperUser` (30%) registers, then browses, uses the wishlist, posts reviews, places orders and reads the order history.
- **Every response is validated**, not just timed: status code and body content (for example the right product came back, a list is a list). A fast error page counts as a failure.
- **Business answers are not failures.** Ordering a sold-out product correctly returns 409; the test accepts 201 and 409 for orders and fails on anything else.
- **Readable statistics.** Dynamic URLs are grouped (`/products/[id]`, `/products?category_id=[id]`) so each endpoint has one line in the report.
- **Automatic verdict.** [`tools/check_thresholds.py`](tools/check_thresholds.py) reads Locust's CSV and exits non-zero when the overall or per-endpoint failure rate is too high, a p95 latency is above its limit, the run was too short to mean anything, or a threshold names an endpoint that was never called (which usually means a rename that silently disabled a check).
- **The checker is itself tested.** [`tests/test_check_thresholds.py`](tests/test_check_thresholds.py) has 11 pytest cases for the pass and fail paths, run in CI before the load test.

## Reference run

One local run on a development machine: 20 users, 30 seconds, API and database on the same host.

| | |
|---|---|
| Requests | about 500, 0 failures |
| Aggregated p95 | 12 ms |
| Slowest endpoint (p95) | `POST /auth/register`, 180 ms (bcrypt password hashing) |
| Product list (p95) | 19 ms |

These numbers show the shape of the system, not its capacity: one machine, a small seeded dataset, no network. The thresholds are set with generous headroom above this baseline so that a shared CI runner does not cause false alarms, and they are meant to catch regressions (an accidentally removed index, an N+1 query, a slow new endpoint), not to certify a capacity.

## Running it

Prerequisites: Python 3.10+, and the application's API running on port 5000 (PostgreSQL plus the Express server, see the application's README).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python -m pytest -q                       # tests for the threshold checker

# headless run, 20 users, 5 new users per second, 30 seconds
locust -f locustfile.py --headless -u 20 -r 5 -t 30s \
  --host http://localhost:5000/api --csv results/run --html results/report.html

python tools/check_thresholds.py results/run_stats.csv thresholds.json
```

Open `results/report.html` for charts. For the interactive web UI, run `locust -f locustfile.py --host http://localhost:5000/api` and open http://localhost:8089.

Orders reduce stock. The seeded catalogue has plenty for a short run; if long or repeated runs report no successful orders, re-seed the database.

## Continuous integration

[`.github/workflows/load-test.yml`](.github/workflows/load-test.yml) runs on every push and pull request and can be started manually with a chosen number of users and duration:

1. Checks out this repository and the application repository.
2. Starts PostgreSQL as a service container, creates and seeds the database, starts the API.
3. Runs the threshold checker's tests, then the load test (30 users for 45 seconds by default).
4. Fails the build if any threshold is missed; uploads the HTML report and CSV files as the `locust-results` artifact.

The workflow tests the application branch that has the validation fixes (`ECOM_REF`); change it to the application's default branch once they are merged there.

## Limitations and next steps

- Load only. There is no stress test (find the breaking point), soak test (hours, memory growth) or spike test.
- A short run on a shared runner has noisy tail latencies; the p95 limits are loose on purpose. For stricter targets, run longer on dedicated hardware and compare against a stored baseline.
- The database is tiny. Realistic performance work needs a production-sized data set and indexes checked with `EXPLAIN`.
- Admin endpoints are not part of the traffic mix.

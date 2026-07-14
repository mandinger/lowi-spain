# Contributing

## Background

Lowi has no public API. This integration talks to whatever the [lowi.es](https://www.lowi.es) customer portal itself uses internally, which is:

- Not documented anywhere.
- Behind an Incapsula WAF with bot-detection challenges.
- Free to change without notice.

An older, no-longer-maintained npm package (`lowi-api`) reverse-engineered a *different*, now-dead endpoint (`mobile.lowi.es/api/1.0/...`, confirmed NXDOMAIN). That package's shape informed this integration's internal data model (see `custom_components/lowi/api.py`) but does **not** reflect the current live API.

## How the real API is (re)discovered

**We do not script logins against lowi.es from CI, sandboxes, or automated tooling.** Scripting a login to a real telecom/billing account from an unfamiliar IP risks tripping fraud detection or a temporary account lock, and risks getting flagged by the WAF. Automated "explore the API" attempts against this specific target are explicitly out of scope for contributions.

Instead, if you need to confirm or update the endpoints this integration uses:

1. Log into <https://www.lowi.es> normally, in your own browser, from your own network.
2. Open DevTools → Network tab, and reload/navigate to your consumption dashboard.
3. Find the request(s) that fetch your login and your data-usage summary.
4. Export them — "Copy as cURL" per request, or save a HAR of the session.
5. **Redact your password and any session/auth cookies or tokens before sharing.**
6. Open an issue or PR with the redacted capture, and note which fields in the JSON response correspond to: remaining data, total data allowance, tariff-included data, bonus data, previous-cycle accumulated data, shared data received, and current month's cost.

## Where API-shape knowledge lives in the code

`custom_components/lowi/api.py` is the single place that talks HTTP to Lowi. Everything else in the integration (coordinator, entities, sensors, config flow) is written against the normalized dataclasses `LowiUser` / `LowiSubscriptionSummary` that `api.py` produces — so updating `api.py`'s request/response handling to match a new capture should not require touching the rest of the integration.

## Development

```bash
scripts/setup   # install runtime + test dependencies into a venv
scripts/develop # run a local Home Assistant instance with this integration mounted
scripts/lint    # ruff format + check
pytest tests/   # run the test suite
```

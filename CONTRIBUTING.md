# Contributing

## Background

Lowi has no public API. This integration talks to whatever the [lowi.es](https://www.lowi.es) customer portal (`/milowi/`) itself uses internally, which is:

- Not documented anywhere.
- Behind an Incapsula WAF with bot-detection challenges.
- Fronted by a Keycloak SSO login (`login.lowi.es/realms/milowi/...`) requiring the account's **NIF/DNI** (not email) plus password, followed by an **SMS one-time code**.
- Free to change without notice.

An older, no-longer-maintained npm package (`lowi-api`) reverse-engineered a *different*, now-dead endpoint (`mobile.lowi.es/api/1.0/...`, confirmed NXDOMAIN). It no longer reflects anything about the current live API and is kept only as historical context.

## Confirmed vs. unverified

From a real captured browser session, we know for certain:

- `GET https://www.lowi.es/api/2.0/me/subscriptions` returns the account's contracted packages/lines as flat JSON (`{"data": [...]}`, no envelope). Auth is via Django session cookies (`sessionid`/`csrftoken`), not a bearer token — there's no `Authorization` header at all.
- Login goes through Keycloak: submit NIF+password to a `login-actions/authenticate` form, then select a phone number to receive an SMS code, then submit that code. Only after all three steps does Lowi set the session cookies.

What's still **unverified** (best-effort guesses in `custom_components/lowi/api.py`, clearly marked inline):

- The exact URL that *starts* the Keycloak flow (`_LOGIN_ENTRY_URL` in `api.py`).
- The field name Keycloak expects for the submitted SMS code (currently guessed as `code`).
- That the phone-selection step always appears, and that auto-picking the first offered phone is correct for accounts with multiple lines.
- Whether a session cookie persisted across a Home Assistant restart still works when reused from a different connection than the one that obtained it — Incapsula's `reese84` cookie is a device/TLS-fingerprint check, and there's no guarantee it survives being replayed by a different HTTP client, even with the same cookie values.
- The live usage/consumption endpoint (how much data has actually been used this cycle, and this month's real cost) hasn't been captured yet at all — `me/subscriptions` only exposes *contracted* allowances, so `cost_current_month`, `remaining_data_mb`, `total_data_mb`, `shared_data_received_mb`, and `accumulated_data_mb` are placeholders (`None`) until that's found.

## How the real API is (re)discovered

**We do not script logins against lowi.es from CI, sandboxes, or automated tooling.** Scripting a login to a real telecom/billing account from an unfamiliar IP risks tripping fraud detection or a temporary account lock, and risks getting flagged by the WAF. Automated "explore the API" attempts against this specific target are explicitly out of scope for contributions.

Instead, if you need to confirm or update the endpoints this integration uses:

1. Log into <https://www.lowi.es> normally, in your own browser, from your own network.
2. Open DevTools → Network tab, and reload/navigate to your consumption dashboard.
3. Find the requests for: the Keycloak login steps, and whatever the dashboard calls for current usage/cost.
4. Export them — "Copy as cURL" per request, or save a HAR of the session.
5. **Before sharing: strip the `Cookie` header and any `--data-raw`/form body containing your password.** The **response body** is what's actually useful and contains no secrets — that's what should get pasted into an issue/PR, not the request.
6. Note which fields in the JSON response correspond to: remaining data, total data allowance, tariff-included data, bonus data, previous-cycle accumulated data, shared data received, and current month's cost.

If you accidentally share a live session cookie, password, or NIF/DNI while doing this, treat it as a leaked credential: change your Lowi password and consider it exposed.

## Where API-shape knowledge lives in the code

`custom_components/lowi/api.py` is the single place that talks HTTP to Lowi. Everything else in the integration (coordinator, entities, sensors, config flow) is written against the normalized `LowiSubscriptionSummary` dataclass that `api.py` produces — so updating `api.py`'s request/response handling to match a new capture should not require touching the rest of the integration.

## Development

```bash
scripts/setup   # install runtime + test dependencies into a venv
scripts/develop # run a local Home Assistant instance with this integration mounted
scripts/lint    # ruff format + check
pytest tests/   # run the test suite
```

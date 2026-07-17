# Contributing

## Background

Lowi has no public API. This integration talks to whatever the [lowi.es](https://www.lowi.es) customer portal (`/milowi/`) itself uses internally, which is:

- Not documented anywhere.
- Behind an Incapsula WAF with bot-detection challenges.
- Fronted by a Keycloak SSO login (`login.lowi.es/realms/milowi/...`) requiring the account's **NIF/DNI** (not email) plus password, followed by an **SMS one-time code**.
- Free to change without notice.

The primary research reference is [`docs/lowi-auth-and-api.md`](docs/lowi-auth-and-api.md) — a full writeup of the auth flow and every data endpoint this integration uses, verified from a real login HAR plus authenticated endpoint captures. Read that first if you're touching `custom_components/lowi_spain/api.py`.

An older, no-longer-maintained npm package (`lowi-api`) reverse-engineered a *different*, now-dead endpoint (`mobile.lowi.es/api/1.0/...`, confirmed NXDOMAIN). It no longer reflects anything about the current live API and is kept only as historical context.

## Confirmed vs. unverified

From a real captured login HAR plus authenticated endpoint captures (see `docs/lowi-auth-and-api.md` for the full detail), we know for certain:

- Login starts at `GET https://www.lowi.es/milowi/login/`, which redirects into a Keycloak (realm `milowi`, client `web-client`) authorization-code+PKCE flow. Submit NIF+password to the returned `login-actions/authenticate` form (with `rememberMe=on`, for a long-lived SSO session), then select a phone number (`selectedPhone=<msisdn>`) to receive an SMS code, then submit that code (field name `code`). Only after all three steps does Django exchange the code server-side and set the authenticated `sessionid` cookie.
- `GET https://www.lowi.es/api/2.0/me/subscriptions` returns the account's contracted packages/lines as flat JSON (`{"data": [...]}`, no envelope).
- `GET https://www.lowi.es/api/milowi/v1/me/consumptions` returns **live usage** for every line in one call (data resume/included/extra, voice-unlimited flag, roaming zone), plus an account-wide `summary` block (current month's cost, billing period).
- `GET https://www.lowi.es/api/milowi/v1/me/billings` returns the invoice list, newest first.
- All of the above are authenticated via the Django session cookie (`sessionid`) — there's no `Authorization` header at all.

What's still **unverified** (best-effort guesses in `custom_components/lowi_spain/api.py`, clearly marked inline):

- The **display label** for each offered phone-selection option. The submitted value (`selectedPhone=<msisdn>`) is confirmed by a real capture, but the surrounding label markup (how Keycloak renders e.g. a masked "***379") was not captured — `_extract_phone_options()` falls back to showing the raw value when no label text is found.
- Whether a session cookie persisted across a Home Assistant restart still works when reused from a different connection than the one that obtained it — Incapsula's `reese84` cookie is a device/TLS-fingerprint check, and there's no guarantee it survives being replayed by a different HTTP client, even with the same cookie values.
- Session/SSO longevity in practice (how long an idle session survives, and whether a lapsed session silently re-authenticates via Keycloak SSO or forces a full OTP again). The integration currently always falls back to Home Assistant's interactive reauth on any session failure; a silent `prompt=none` refresh is a documented future improvement (see `docs/lowi-auth-and-api.md` §5, §8).

## How the real API is (re)discovered

**We do not script logins against lowi.es from CI, sandboxes, or automated tooling.** Scripting a login to a real telecom/billing account from an unfamiliar IP risks tripping fraud detection or a temporary account lock, and risks getting flagged by the WAF. Automated "explore the API" attempts against this specific target are explicitly out of scope for contributions.

Instead, if you need to confirm or update the endpoints this integration uses:

1. Log into <https://www.lowi.es> normally, in your own browser, from your own network.
2. Open DevTools → Network tab, and reload/navigate to your consumption dashboard.
3. Find the requests for: the Keycloak login steps, and whatever the dashboard calls for current usage/cost.
4. Export them — "Copy as cURL" per request, or save a HAR of the session.
5. **Before sharing: strip the `Cookie` header and any `--data-raw`/form body containing your password.** The **response body** is what's actually useful and contains no secrets — that's what should get pasted into an issue/PR, not the request.
6. Note which fields in the JSON response changed, and update `docs/lowi-auth-and-api.md`'s schemas (§6.1) alongside the parsing code in `api.py` so the two don't drift apart.

If you accidentally share a live session cookie, password, or NIF/DNI while doing this, treat it as a leaked credential: change your Lowi password and consider it exposed.

## Where API-shape knowledge lives in the code

`custom_components/lowi_spain/api.py` is the single place that talks HTTP to Lowi. Everything else in the integration (coordinator, entities, sensors, config flow) is written against the normalized `LowiAccountData`/`LowiSubscriptionSummary` dataclasses that `api.py` produces — so updating `api.py`'s request/response handling to match a new capture should not require touching the rest of the integration.

## Development

```bash
scripts/setup   # install runtime + test dependencies into a venv
scripts/develop # run a local Home Assistant instance with this integration mounted
scripts/lint    # ruff format + check
pytest tests/   # run the test suite
```

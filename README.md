# MyMarketplace — Selenium + pytest E2E tests

Browser-level tests for the **plain HTML/CSS/JS MyMarketplace frontend v2**, written from `main(5).tsp` (the authoritative TypeSpec file, copied in `schema/main.tsp`), not assumptions made from the OpenAPI emitter.

The suite **drives the real browser UI**; it doesn't call API methods directly. The browser's `fetch` is *observed*, not mocked, so requests still travel to your running API/Prism. Chrome DevTools installs a lightweight request recorder **before frontend JS loads** to assert methods, URL parameters, and cart JSON bodies even when Prism returns example data unrelated to the request.

## 1. Prerequisites

- Python 3.10+.
- Google Chrome or Chromium installed.
- The API mock or real backend running and reachable by your browser.

Install dependencies:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Selenium 4 includes **Selenium Manager**, which normally finds/downloads the matching ChromeDriver automatically. In an offline environment, provide a compatible ChromeDriver yourself.

## 2. Use with Prism (default)

Run your current OpenAPI mock in another terminal (regenerate OpenAPI from `main(5).tsp` if needed):

```bash
prism mock openapi.yaml
```

Point the test suite at the actual mock URL/port (TypeSpec development default: 9999):

```bash
pytest -v --backend=prism --api-url=http://localhost:9999
```

**Prism behavior:** Mock responses may have example UUIDs, quantities, users, or product names that do not match the request. A successful `POST /cart` may not change the subsequent `GET /cart`. In Prism mode, the tests verify the frontend's outgoing request **and UI feedback**, but do **not** assert that an added product persists in the cart or that an updated username is reflected back. They can **skip** tests that need catalog items or a cart row if Prism replies with a documented empty `404`.

When the mock responds with data, the suite also checks actual DOM rendering, sorting, and subtotal math.

**Important:** Because your frontend and API are on different ports, configure the mock/backend to permit browser CORS requests (including `OPTIONS`, `Content-Type: application/json`, and credentials if cookies are used). A reachable API may still fail in Chrome if CORS headers are missing. For cookie authentication across origins, also check your cookie's SameSite/Secure attributes. The test suite does not suppress browser CORS restrictions.

## 3. Use against a real backend

Use a dedicated test account, **not** your regular or production account. Pass credentials via environment variables to avoid exposing them in shell history:

```bash
export E2E_USERNAME="test_user"
export E2E_PASSWORD="abcdAB123!@"  # must match TypeSpec Password scalar
pytest -v --backend=real --api-url=http://localhost:9999
```

The default real-backend run performs non-destructive checks (catalog, login/logout, HTML5 validation, session restoration). Mutating tests are *opt-in*:

```bash
# These modify the test account's cart:
pytest -v -m cart --backend=real --allow-mutations

# These register users or change username/password:
pytest -v -m auth --backend=real --allow-account-changes

# DANGEROUS: permanently deletes the account supplied in E2E_USERNAME.
# Run this separately, at the very end, using a disposable account.
pytest -v -m deletion --backend=real --allow-account-deletion
```

The username and password edit tests attempt to restore their previous values in real mode. **Do not run account editing/deletion tests against anything but a disposable test account.** The registration test creates a unique valid user; cleaning it up is up to the test environment (the API has no admin cleanup mechanism).

## 4. Frontend hosting and CLI switches

The test archive includes the **exact frontend v2** these selectors target in `frontend/`. pytest starts an ephemeral local static server automatically, so you don't need to launch `python -m http.server` yourself. If your frontend is already served elsewhere, use:

```bash
pytest -v --frontend-url=http://localhost:5500 --api-url=http://localhost:9999
```

Other useful switches:

| Flag | Purpose |
|---|---|
| `--headed` | Show Chrome window (headless by default) |
| `--timeout=20` | Timeout in seconds for asynchronous DOM/request waits |
| `--backend=prism` / `--backend=real` | Stateless mock checks or persistence checks |
| `--username` / `--password` | Override credentials used for login tests |
| `-m smoke` | Run only basic UI and API-connection checks |
| `-m products` | Run catalog, details, search, refresh, sorting |
| `-m cart` | Run cart-related browser flows |
| `-m auth` | Run auth, profile, and account flows |
| `-k add_to_cart` | Filter to tests whose names match |

Environment variables `FRONTEND_URL`, `API_URL`, `E2E_BACKEND`, `E2E_USERNAME` and `E2E_PASSWORD` are accepted as defaults.

## 5. Tests covered

- Basic navigation, website title, API health call, responsive frontend entry point.
- Product list, details modal, search query encoding, clear search, product refresh, price sorting.
- Client-side username/password syntax validation from TypeSpec.
- Registration, login, session restoration on browser refresh, logout.
- `POST /cart`: one product from a card; chosen quantity from product dialog; invalid quantities blocked.
- `GET /cart`: displays item quantities, unit badge, subtotal calculations.
- `PATCH /cart?index=0`: sends `{ "quantity": integer }` and handles response.
- `DELETE /cart?index=0`: remove and cancel-confirmation behaviors.
- `DELETE /cart/clear`: clear with confirmation.
- `PATCH /user`: requires `uuid`, optionally `username` or `password`.
- `DELETE /user`: requires confirmation; disabled on real servers unless explicitly enabled.

## 6. Reports and troubleshooting

Run:

```bash
pytest -vv -ra
```

On a failed browser test, the fixture saves `artifacts/<test>.png` and `artifacts/<test>.html` for debugging. The HTML may contain test account data; do not commit these files.

If ChromeDriver cannot start, check Chrome/Chromium and Selenium Manager. If you see *Could not reach the API*, verify the API URL, its availability, and CORS. If tests skip due to `404`/empty cart in Prism, supply meaningful Prism examples or run the strict backend suite against an actual stateful API.

The suite intentionally **does not** treat Prism's statelessness as an application bug, but it **does** fail when the expected browser request is absent or has the wrong payload.

## Verification note

The suite was syntax-checked and all 31 pytest cases were collected successfully with temporary Selenium import stubs in the build environment. Live Selenium execution was **not** possible there (Selenium/ChromeDriver were unavailable); a separate browser smoke run was also blocked by environment policy. Run the suite locally/CI for actual E2E results.


## 7. First test seems stuck on Windows

The first printed test name does **not** mean the test body has started:
pytest runs fixtures first. On the first test the suite starts a local server,
creates Chrome WebDriver (possibly downloading ChromeDriver), and loads the page.

Run the first test with setup tracing on PowerShell:

```powershell
$env:SE_TIMEOUT = "20"
python -m pytest -vv -s --setup-show -x --trace-e2e --headed --backend=prism --api-url=http://localhost:9999 -k invalid_auth_input
```

The new `--trace-e2e` flag reports whether the process stopped while starting
Chrome, opening the frontend, or waiting for API requests. The suite now
defaults Selenium Manager's network timeout to 30 seconds (unless `SE_TIMEOUT`
is already configured), instead of its usual 300 seconds per request. If driver
downloads are restricted, supply a matching driver directly:

```powershell
python -m pytest -vv -s --trace-e2e --chromedriver-path="C:\tools\chromedriver.exe"
```

Optionally set `--chrome-binary="C:\Program Files\Google\Chrome\Application\chrome.exe"`
when Chrome is installed in a nonstandard location.

**Prism listens on port 4010 by default** unless you pass `-p 9999`. A
`servers:` entry in the OpenAPI document does not set Prism's listening port.
Run one of these pairs:

```powershell
prism mock openapi.yaml -p 9999
python -m pytest --api-url=http://localhost:9999
```

or

```powershell
prism mock openapi.yaml
python -m pytest --api-url=http://localhost:4010
```

You can check the API independently with:

```powershell
Invoke-RestMethod http://localhost:9999/health
```

If the stall persists, press Ctrl+C and send the last `[E2E setup]` message
and any traceback. `--timeout` limits UI waits, not driver installation.

## 8. Fix for hidden login form after the frontend appears to load

In the previous release, the startup fixture checked `#cart-message` with
Selenium's `.text`. Because the Cart view starts hidden, `.text` was empty even
while the DOM text content was `Loading cart...`. It let auth tests run before
Prism had returned a mocked `CartModel.owner`, which could then show the signed-in
panel and hide `#auth-username` unexpectedly.

This release waits for the actual hidden element's **`textContent`** to change
and verifies the signed-out account form is visible before filling it. No
frontend code changes are necessary.

Replace at least `conftest.py` and `pages.py` from this archive (or extract the
whole archive). Re-run the first test:

```powershell
python -m pytest -v -s -x --trace-e2e --headed --backend=prism --api-url=http://localhost:4010 -k invalid_auth_input
```

You can append your existing `--chrome-binary` and `--chromedriver-path` flags.
When the initial cart is settled, you should see
`[E2E setup] Initial cart UI is settled (including Prism's mocked owner)`.

If an auth field remains hidden, the suite now reports whether it could reset
the mock session before attempting to fill the input.


## 9. One Chrome window for the entire test run

ChromeDriver now uses a **session-scoped** pytest fixture: one Chrome window is
launched at the start of the run and closed at the end. The `page` fixture is
still function-scoped, so each test starts with a freshly reloaded document.

Before each test, the suite clears cookies (including the API origin),
`sessionStorage`, and `localStorage`, sets the configured API URL again, clears
the browser cache, and reloads. This prevents the previous test's login/session
or UI preferences from affecting the next one. A reload *alone* would not clear
those browser storage areas or cookies. Application state on a **real backend**
(e.g., an account or cart stored in its database) is **not** erased; avoid
mutating real backends without dedicated test accounts/cleanup.

As a bonus, the bundled development HTTP server now ignores only expected
connection-reset/broken-pipe errors caused by navigation or browser shutdown.
Unrelated server errors still print as usual.

Run with the same CLI flags as before, e.g.:

```powershell
python -m pytest -vv -s --headed --backend=prism --api-url=http://localhost:4010 `
  --chrome-binary="D:\Tools\chrome-win64\chrome.exe" `
  --chromedriver-path="D:\Tools\chromedriver-win64\chromedriver.exe"
```


## 10. New: frontend unit tests (no browser, API, or npm dependencies)

The frontend is plain JavaScript, so its API client can be tested in isolation.
`tests_js/unit/api.test.cjs` executes **the actual `frontend/api.js`** in a
Node VM with an isolated `fetch` stub. It checks HTTP methods, endpoints,
request JSON, encoded product searches, cookie credentials, accepted/rejected
cart quantities, successful empty 200/204 responses, and error handling.
`tests_js/unit/contract.test.cjs` compares the HTML username and password
patterns with the TypeSpec scalar definitions in `schema/main.tsp`.

Requires Node.js **20 or newer** (the app already has a Node dependency if you
run Prism with npm). No external JS packages or browser are needed, and
`npm install` is **not required**.

```powershell
node --version
npm test
# or: npm run test:unit
```

The 25 JavaScript unit tests execute separately from pytest. That is
intentional: Python's pytest cannot directly execute JavaScript as Python.
This keeps `frontend/api.js` framework-free and avoids rewriting its logic
in Python merely to test it.

## 11. New: deterministic frontend integration tests with pytest + Selenium

`tests/integration/test_frontend_api_integration.py` contains **17 integration
tests** for the real HTML UI, the real `frontend/script.js`, and the real
`frontend/api.js`. They replace **only** the network's fetch implementation
with the test-local `tests/integration/mock_api.js`. The fake API returns
three fixed products and maintains an in-memory account and cart for the
duration of each test.

That means **no Prism server is needed** for these integration tests, and no
real backend receives writes or deletions. Unlike Prism's stateless examples,
cart mutations are deterministic and the test can assert updated subtotals.

```powershell
python -m pytest -v -m integration --headed `
    --chrome-binary="D:\Tools\chrome-win64\chrome.exe" `
    --chromedriver-path="D:\Tools\chromedriver-win64\chromedriver.exe"
```

Use the paths matching your downloaded Chrome for Testing executables. The
single browser and local static frontend server from the existing E2E suite
are reused; Chrome is not started for every test. Each integration test
loads fresh application state, and the fake fetch preload is removed at the
end so it cannot affect ordinary E2E tests.

These tests check:

- catalog rendering, sorting, searching, no-results message, and product details;
- login, logout, registration, invalid credentials, and profile updates;
- add-to-cart from cards and detail dialog, quantities, badge, and subtotal;
- quantity editing, remove cancel/confirm, clear cart, and unauthorized action;
- HTTP failure surfaced as a meaningful error message.

Run **all Python tests** (E2E + integration):

```powershell
python -m pytest -v --headed --backend=prism --api-url=http://localhost:4010 `
    --chrome-binary="D:\Tools\chrome-win64\chrome.exe" `
    --chromedriver-path="D:\Tools\chromedriver-win64\chromedriver.exe"
```

The original E2E tests still need Prism or a real backend, as before.
To run **only the original E2E tests**, exclude integration:

```powershell
python -m pytest -v -m "not integration" --backend=prism --api-url=http://localhost:4010
```

Notes: Browser integration mocks **do not test actual CORS, cookies on the
network, Prism behavior, or database persistence**; that is exactly what
E2E tests remain for. Unit and integration tests are complementary, not
replacements. Some E2E tests can still skip with Prism; the new deterministic
integration tests should not depend on Prism example quality.

**Verification:** The JavaScript unit suite was executed successfully in
Node and the fake API was exercised against the real frontend in Chromium in
a browser smoke check. The Python Selenium integration tests were
syntax-checked but could not be run with Selenium in the packaging
environment; run them on your Windows machine using the commands above.


## 12. Run everything with one Python command

The new **`run_tests.py`** is a wrapper for all three test layers. Edit the
**CONFIGURATION** block at the top, including `API_URL`, `CHROME_BINARY`,
`CHROMEDRIVER_PATH`, and the test-layer toggles. Then run:

```powershell
python run_tests.py
```

It runs **Node's JavaScript unit tests first**, then runs **integration before
E2E in one pytest process**. The browser is created just once for both browser
test layers because the existing `driver` fixture has `scope="session"`. It
cleans up the browser between browser test cases and closes Chrome at the end.

`RUN_UNIT_TESTS`, `RUN_INTEGRATION_TESTS`, and `RUN_E2E_TESTS` let you disable
any layer. Set `SHOW_BROWSER = False` for headless mode. Set
`STOP_AFTER_FAILED_STAGE = True` to skip browser tests if the unit tests fail.
Without that flag, a failure in one stage won't prevent later stages from running.

The wrapper prints a final summary, returns a nonzero exit code on failure, and
(optional) saves a pytest JUnit XML report at `reports/browser-results.xml`.
It launches pytest through **your active Python environment**, so activate
`.venv` before running it. It calls Node directly (`node --test`), requiring
Node 20+, but does not require `npm install`. Prism still must be started
separately for E2E tests; integration tests have their own fake API.

For a **real backend**, mutation/account-change/deletion flags default to False.
Enable them only with dedicated disposable test data; the wrapper never creates
accounts or starts Prism for you.

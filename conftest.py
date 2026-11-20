"""Pytest fixtures and CLI settings for the MyMarketplace Selenium E2E tests."""

from __future__ import annotations

import contextlib
import functools
import http.server
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait

from pages import MarketplacePage, WebDriver

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_PASSWORD = "abcdAB123!@"  # Valid main(5).tsp example, NOT a production secret.

# Runs BEFORE the website's JavaScript using Chrome DevTools.
# Observes browser requests without replacing/short-circuiting the real fetch.
# Credential values are intentionally not stored (only key names for account edits).
FETCH_OBSERVER = r"""
(() => {
  const original = window.fetch;
  const seen = [];
  Object.defineProperty(window, '__marketplaceE2ERequests', {
    value: seen, writable: false, configurable: false
  });
  window.fetch = async function(input, init) {
    const method = String(init?.method || input?.method || 'GET').toUpperCase();
    const url = typeof input === 'string' ? input : input?.url;
    const entry = { method, url: String(url || ''), body: null, keys: [] };
    try {
      const path = new URL(entry.url, location.href).pathname;
      if (init?.body && (path === '/cart' || path === '/user')) {
        const payload = JSON.parse(init.body);
        entry.keys = Object.keys(payload);
        if (path === '/cart') entry.body = payload;
        if (path === '/user') entry.body = { uuid: payload.uuid };
      }
    } catch (_) { /* Do not modify the request on parse failures. */ }
    seen.push(entry);
    try {
      const response = await original.apply(this, arguments);
      entry.status = response.status;
      return response;
    } catch (e) {
      entry.error = String(e);
      throw e;
    }
  };
})();
"""


def pytest_addoption(parser):
    group = parser.getgroup("marketplace", "MyMarketplace E2E options")
    group.addoption("--frontend-url", default=os.getenv("FRONTEND_URL"),
                    help="Existing frontend URL; if omitted, pytest serves ./frontend itself.")
    group.addoption("--api-url", default=os.getenv("API_URL", "http://localhost:9999"),
                    help="Marketplace API base URL (default: %(default)s).")
    group.addoption("--backend", choices=("prism", "real"),
                    default=os.getenv("E2E_BACKEND", "prism"),
                    help="prism: assert requests without assuming state; real: verify persisted state.")
    group.addoption("--username", default=os.getenv("E2E_USERNAME"),
                    help="Dedicated real test account username; defaults to TypeSpec example for Prism.")
    group.addoption("--password", default=os.getenv("E2E_PASSWORD"),
                    help="Dedicated real test account password; defaults to TypeSpec example for Prism.")
    group.addoption("--headed", action="store_true", help="Display Chrome instead of headless.")
    group.addoption("--trace-e2e", action="store_true",
                    help="Print browser and page setup milestones (combine with -s).")
    group.addoption("--chromedriver-path", default=os.getenv("CHROMEDRIVER_PATH"),
                    help="Optional ChromeDriver executable path; bypass Selenium Manager driver discovery.")
    group.addoption("--chrome-binary", default=os.getenv("CHROME_BINARY"),
                    help="Optional path to chrome.exe or Chromium binary.")
    group.addoption("--timeout", type=float, default=12.0,
                    help="Seconds to wait for async UI updates (default: %(default)s).")
    group.addoption("--allow-mutations", action="store_true",
                    help="Allow cart mutations against a REAL backend.")
    group.addoption("--allow-account-changes", action="store_true",
                    help="Allow register/username/password changes against a REAL backend.")
    group.addoption("--allow-account-deletion", action="store_true",
                    help="Allow PERMANENT account deletion against a REAL backend. Use a disposable account.")


@dataclass(frozen=True)
class Settings:
    frontend_url: str
    api_url: str
    backend: str
    username: str | None
    password: str | None
    headed: bool
    timeout: float
    allow_mutations: bool
    allow_account_changes: bool
    allow_account_deletion: bool

    @property
    def strict(self):
        return self.backend == "real"


def trace(config, message):
    if config.getoption("--trace-e2e"):
        print(f"[E2E setup] {message}", flush=True)


class TestHTTPServer(http.server.ThreadingHTTPServer):
    """Ignore harmless socket disconnects caused by Chrome navigation/teardown.

    Unexpected server exceptions still print their traceback normally.
    """

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


@pytest.fixture(scope="session")
def local_frontend_server(pytestconfig: pytest.Config):
    """Serve the included frontend on a random free port; no external web server required."""
    if not (FRONTEND_DIR / "index.html").is_file():
        pytest.fail(f"Missing frontend files in {FRONTEND_DIR}")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FRONTEND_DIR))
    # Use IPv4 explicitly; "localhost" resolution can be inconsistent on Windows.
    httpd = TestHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    trace(pytestconfig, f"Frontend server listening on http://127.0.0.1:{httpd.server_address[1]}")
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


@pytest.fixture(scope="session")
def settings(pytestconfig: pytest.Config, request: pytest.FixtureRequest) -> Settings:
    url = pytestconfig.getoption("--frontend-url")
    if not url:
        url = request.getfixturevalue("local_frontend_server")
    backend = pytestconfig.getoption("--backend")
    return Settings(
        frontend_url=url.rstrip("/"),
        api_url=pytestconfig.getoption("--api-url").rstrip("/"), # type: ignore
        backend=backend, # type: ignore
        username=pytestconfig.getoption("--username") or ("bob_123" if backend == "prism" else None),
        password=pytestconfig.getoption("--password") or (DEFAULT_PASSWORD if backend == "prism" else None),
        headed=pytestconfig.getoption("--headed"), # type: ignore
        timeout=pytestconfig.getoption("--timeout"), # type: ignore
        allow_mutations=pytestconfig.getoption("--allow-mutations"), # type: ignore
        allow_account_changes=pytestconfig.getoption("--allow-account-changes"), # type: ignore
        allow_account_deletion=pytestconfig.getoption("--allow-account-deletion"), # type: ignore
    )


@pytest.fixture(autouse=True)
def guard_mutations(request: pytest.FixtureRequest, settings: Settings) -> None:
    """Prevent accidental writes/deletes against an actual backend."""
    if not settings.strict:
        return
    marks = {mark.name for mark in request.node.iter_markers()}
    if "deletion" in marks and not settings.allow_account_deletion:
        pytest.skip("Real account deletion disabled; pass --allow-account-deletion with disposable credentials")
    if "account_changes" in marks and not settings.allow_account_changes:
        pytest.skip("Real account changes disabled; pass --allow-account-changes")
    if "mutating" in marks and not settings.allow_mutations:
        pytest.skip("Real cart mutations disabled; pass --allow-mutations with dedicated test account")


@pytest.fixture(scope="session")
def driver(settings: Settings, pytestconfig: pytest.Config):
    trace(pytestconfig, "Starting Chrome WebDriver (Selenium Manager may need a driver download)")
    # Selenium Manager's documented network timeout defaults to 300s per request.
    # Preserve an explicit user override, but fail earlier when a download is blocked.
    os.environ.setdefault("SE_TIMEOUT", "30")
    options = ChromeOptions()
    binary = pytestconfig.getoption("--chrome-binary")
    if binary:
        if not Path(binary).is_file():
            pytest.fail(f"Chrome binary does not exist: {binary}")
        options.binary_location = binary
    if not settings.headed:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")  # Helps in Docker/CI; not needed on desktop.
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    try:
        driver_path = pytestconfig.getoption("--chromedriver-path")
        if driver_path:
            if not Path(driver_path).is_file():
                pytest.fail(f"ChromeDriver executable does not exist: {driver_path}")
            browser = webdriver.Chrome(options=options, service=ChromeService(executable_path=driver_path))
        else:
            browser = webdriver.Chrome(options=options)  # Selenium Manager finds driver.
    except Exception as exc:
        pytest.fail(
            "Could not start Chrome. This is browser setup, not a failed website test. "
            "Check Chrome/ChromeDriver installation, firewall/proxy, or pass "
            f"--chromedriver-path=... . Details: {exc}"
        )
    trace(pytestconfig, "Chrome WebDriver started (reused for all tests)")
    try:
        browser.set_page_load_timeout(max(15.0, settings.timeout))
        browser.set_script_timeout(max(15.0, settings.timeout))
        browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": FETCH_OBSERVER})
        trace(pytestconfig, "Fetch observer installed")
        yield browser
    finally:
        with contextlib.suppress(Exception):
            browser.quit()


@pytest.fixture
def page(driver: WebDriver, settings: Settings, pytestconfig: pytest.Config) -> MarketplacePage:
    from pages import MarketplacePage


    # A single Chrome/ChromeDriver is shared across the full pytest session.
    # However, the web application's user state must be isolated per test.
    # Reloading without cache resets JavaScript, but does NOT clear storage
    # or authentication cookies, so explicitly clear them before each reload.
    frontend_origin = urlsplit(settings.frontend_url).netloc
    current = urlsplit(driver.current_url)
    if current.netloc != frontend_origin or current.scheme not in ("http", "https"):
        trace(pytestconfig, f"Opening frontend: {settings.frontend_url}")
        driver.get(settings.frontend_url)

    trace(pytestconfig, "Resetting cookies, session storage, and browser cache")
    # Clears cookies for ALL origins, including the cross-origin API.
    driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
    driver.execute_script(
        "window.sessionStorage.clear();"
        "window.localStorage.clear();"
        "window.localStorage.setItem('mymarketplace.apiUrl', arguments[0]);",
        settings.api_url,
    )
    driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    trace(pytestconfig, f"Refreshing frontend without cache: {settings.api_url}")
    driver.refresh()
    WebDriverWait(driver, settings.timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    result = MarketplacePage(driver, settings.timeout)
    result.wait_visible("shop-view")
    # Drain the initial calls so Prism's CartModel.owner can't unexpectedly
    # switch the account pane mid-test (even when no login was performed).
    trace(pytestconfig, "Waiting for initial /products and /cart requests")
    result.wait_request("GET", "/products")
    result.wait_request("GET", "/cart")
    # The fetch observer records completion before the page's async rendering
    # finishes. Wait for cart rendering to settle to avoid an intermittent
    # login/logout race on the first test when Prism supplies an owner.
    # IMPORTANT: #cart-view is hidden while the shop is active. Selenium's
    # WebElement.text is EMPTY for hidden elements, even if their textContent is
    # "Loading cart...". The former wait therefore passed too early and a
    # late Prism CartModel.owner could switch the account pane to signed-in
    # *after* an auth test started filling its signed-out login form.
    result.wait(
        lambda d: d.execute_script(
            "return document.getElementById('cart-message').textContent.trim() !== 'Loading cart...';"
        ),
        "Initial cart response arrived, but frontend cart rendering never finished",
    )
    trace(pytestconfig, "Initial cart UI is settled (including Prism's mocked owner)")
    trace(pytestconfig, "Page setup complete; executing test assertions")
    return result


@pytest.fixture
def authenticated(page: MarketplacePage, settings: Settings) -> MarketplacePage:
    if not settings.username or not settings.password:
        pytest.skip("Set E2E_USERNAME and E2E_PASSWORD for auth tests against a real backend")
    page.login(settings.username, settings.password)
    if not page.is_signed_in():
        if settings.strict:
            pytest.fail("Login failed: check real test account credentials, API/CORS, and server")
        pytest.skip("Prism did not return a usable user profile for login")
    return page


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    if report.when != "call" or not report.failed:
        return
    # Screenshot and page HTML on failures, if --basetemp is configured or default output.
    browser = item.funcargs.get("driver") if hasattr(item, "funcargs") else None
    if browser is None:
        return
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    filename = item.nodeid.replace("::", "_").replace("/", "_").replace("[", "_").replace("]", "_")
    with contextlib.suppress(Exception):
        browser.save_screenshot(str(artifacts / (filename + ".png")))
    with contextlib.suppress(Exception):
        (artifacts / (filename + ".html")).write_text(browser.page_source, encoding="utf-8")

"""Small page object matching the selectors in the bundled frontend v2."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.webdriver import WebDriver


class MarketplacePage:
    def __init__(self, driver: WebDriver, timeout=12.0):
        self.driver = driver
        self.timeout = timeout

    def wait(self, condition, message="Timed out waiting for the UI"):
        return WebDriverWait(self.driver, self.timeout, poll_frequency=0.15).until(
            condition, message=message
        )

    def by_id(self, element_id):
        return self.driver.find_element(By.ID, element_id)

    def wait_visible(self, element_id):
        return self.wait(EC.visibility_of_element_located((By.ID, element_id)))

    def wait_hidden(self, element_id):
        return self.wait(EC.invisibility_of_element_located((By.ID, element_id)))

    def select(self, css):
        return self.driver.find_element(By.CSS_SELECTOR, css)

    def all(self, css):
        return self.driver.find_elements(By.CSS_SELECTOR, css)

    def click(self, css):
        node = self.wait(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))
        node.click()
        return node

    def fill(self, css, value):
        node = self.wait(EC.visibility_of_element_located((By.CSS_SELECTOR, css)))
        node.clear()
        node.send_keys(value)
        return node

    def navigate(self, name):
        self.click(f'.site-nav [data-view="{name}"]')
        self.wait_visible(f"{name}-view")

    def notice(self):
        node = self.by_id("toast")
        return node.text if node.is_displayed() else ""

    def wait_notice(self, fragment=None):
        def check(_):
            text = self.notice()
            return text if text and (fragment is None or fragment.lower() in text.lower()) else False
        return self.wait(check, f"Expected toast containing: {fragment!r}")

    def requests(self):
        return self.driver.execute_script(
            "return window.__marketplaceE2ERequests || [];"
        )

    def request_count(self):
        return len(self.requests())

    def find_request(self, method, path, after=0, query=None, completed=False):
        """Return matching request(s); exact paths or path prefix with trailing '*' accepted."""
        prefix = path.endswith("*")
        clean_path = path[:-1] if prefix else path
        for item in self.requests()[after:]:
            if item.get("method") != method.upper():
                continue
            parts = urlsplit(item.get("url", ""))
            if not (parts.path.startswith(clean_path) if prefix else parts.path == clean_path):
                continue
            if query:
                parsed_query = parse_qs(parts.query)
                if not all(parsed_query.get(key) == [str(value)] for key, value in query.items()):
                    continue
            if completed and "status" not in item and "error" not in item:
                continue
            return item
        return None

    def wait_request(self, method, path, after=0, query=None, completed=True):
        return self.wait(
            lambda _: self.find_request(method, path, after, query, completed),
            f"Expected {method} {path} request (after={after})"
        )

    def wait_products_loaded(self):
        self.wait_request("GET", "/products", completed=True)
        self.wait(lambda _: "Loading products" not in self.by_id("products-summary").text)

    def product_cards(self):
        return self.all("#product-grid .product-card")

    def require_products(self):
        import pytest
        self.wait_products_loaded()
        cards = self.product_cards()
        if cards:
            return cards
        message = self.by_id("products-message").text.lower()
        if "no products" in message or "no products are available" in message:
            pytest.skip("Product catalog is empty or Prism returned 404")
        pytest.fail(f"Products were not rendered: {message}")

    def open_detail(self, index=0):
        cards = self.require_products()
        before = self.request_count()
        cards[index].find_element(By.CSS_SELECTOR, ".product-card-button").click()
        self.wait_visible("product-dialog")
        request = self.wait_request("GET", "/products/*", after=before)
        self.wait(lambda _: self.all("#product-detail-content .detail-name") or
                  self.all("#product-detail-content .error-text"))
        return request

    def close_detail(self):
        self.click("#close-dialog")
        self.wait_hidden("product-dialog")

    def is_signed_in(self):
        return self.by_id("signed-in-panel").is_displayed()

    def ensure_signed_out(self):
        """Make the signed-out form visible, even if Prism supplied a mock cart owner."""
        self.navigate("account")
        if self.is_signed_in():
            before = self.request_count()
            self.click("#logout-button")
            self.wait_request("GET", "/user/logout", after=before)
            self.wait(
                lambda _: not self.is_signed_in(),
                "Logout did not switch the Account panel to signed-out",
            )
        self.wait(
            EC.visibility_of_element_located((By.ID, "auth-username")),
            "The Account form is still hidden. Check whether a cart response "
            "has re-established a mocked session.",
        )

    def login(self, username, password):
        self.ensure_signed_out()
        self.navigate("account")
        self.click("#login-tab")
        self.fill("#auth-username", username)
        self.fill("#auth-password", password)
        self.click("#auth-submit")
        self.wait(lambda _: self.is_signed_in() or bool(self.notice()),
                  "Login neither succeeded nor showed an error")

    def register(self, username, password):
        self.ensure_signed_out()
        self.navigate("account")
        self.click("#register-tab")
        self.fill("#auth-username", username)
        self.fill("#auth-password", password)
        self.click("#auth-submit")
        self.wait(lambda _: bool(self.notice()) or self.by_id("login-tab").get_attribute("aria-selected") == "true")

    def open_cart(self):
        before = self.request_count()
        self.navigate("cart")
        request = self.wait_request("GET", "/cart", after=before)
        self.wait(lambda _: "Loading cart" not in self.by_id("cart-message").text)
        return request

    def cart_rows(self):
        return self.all("#cart-items .cart-item")

    def require_cart_rows(self):
        import pytest
        self.open_cart()
        rows = self.cart_rows()
        if rows:
            return rows
        message = self.by_id("cart-message").text.lower()
        if "cart is empty" in message:
            pytest.skip("Cart is empty; Prism does not preserve add-to-cart mutations")
        pytest.fail(f"Cart has no items and did not report empty: {message}")

    def accept_confirm(self, button_css):
        self.click(button_css)
        alert = self.wait(EC.alert_is_present(), "Expected JavaScript confirmation dialog")
        alert.accept()

    def reject_confirm(self, button_css):
        self.click(button_css)
        alert = self.wait(EC.alert_is_present(), "Expected JavaScript confirmation dialog")
        alert.dismiss()

    def ensure_mutation_succeeded(self, request, mode, message=None):
        """Fail for real backend errors; Prism can return documented mock errors."""
        status = request.get("status")
        if mode == "real":
            assert status is not None and 200 <= status < 300, (
                f"Backend mutation failed: HTTP {status}, {request.get('error')}"
            )
            if message:
                self.wait_notice(message)
        else:
            # Prism may not know whether a fake product/user exists, but the frontend
            # should still surface a usable success/error message, never silently fail.
            assert status is not None or request.get("error"), "Mutation request did not complete"
            self.wait_notice()

"""Selenium cart flows. Prism assertions verify the POST/PATCH/DELETE requests.

Prism doesn't promise to persist mutations: see README for strict-real mode.
"""

from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from selenium.webdriver.common.by import By


def _ensure_cart_with_item(page, settings, seed_real=True):
    """Seed by clicking the website if real backend has an empty cart.

    Prism is stateless and can return an empty cart after success; skip if it
    has no seeded cart example (not an E2E failure of the frontend).
    """
    page.open_cart()
    if page.cart_rows():
        return page.cart_rows()
    if not settings.strict or not seed_real:
        pytest.skip("No seeded cart row to interact with")
    page.navigate("shop")
    page.require_products()
    before = page.request_count()
    page.product_cards()[0].find_element(By.CSS_SELECTOR, ".add-to-cart-button").click()
    request = page.wait_request("POST", "/cart", after=before)
    page.ensure_mutation_succeeded(request, settings.backend, "added to cart")
    page.open_cart()
    rows = page.cart_rows()
    assert rows, "Real backend did not retain the product added through UI"
    return rows


@pytest.mark.cart
@pytest.mark.mutating
def test_product_card_adds_one_unit(authenticated, settings):
    page = authenticated
    page.navigate("shop")
    detail_request = page.open_detail()
    expected_id = urlsplit(detail_request["url"]).path.rsplit("/", 1)[-1]
    page.close_detail()
    before = page.request_count()
    page.product_cards()[0].find_element(By.CSS_SELECTOR, ".add-to-cart-button").click()
    request = page.wait_request("POST", "/cart", after=before)
    assert request["body"] == {"product": expected_id, "quantity": 1}
    page.ensure_mutation_succeeded(request, settings.backend, "added to cart")
    if settings.strict:
        page.open_cart()
        assert page.cart_rows(), "Added product should appear in real backend cart"


@pytest.mark.cart
@pytest.mark.mutating
def test_detail_dialog_adds_selected_quantity(authenticated, settings):
    page = authenticated
    page.navigate("shop")
    detail_request = page.open_detail()
    expected_id = urlsplit(detail_request["url"]).path.rsplit("/", 1)[-1]
    before = page.request_count()
    page.fill("#product-dialog .detail-add-form .quantity-input", "3")
    page.click('#product-dialog .detail-add-form button[type="submit"]')
    request = page.wait_request("POST", "/cart", after=before)
    assert request["body"] == {"product": expected_id, "quantity": 3}
    page.ensure_mutation_succeeded(request, settings.backend, "added to cart")


@pytest.mark.cart
@pytest.mark.parametrize("quantity", ["0", "1001", "1.5"])
def test_invalid_add_quantity_never_reaches_api(page, quantity):
    page.open_detail()
    page.fill("#product-dialog .detail-add-form .quantity-input", quantity)
    assert page.driver.execute_script(
        "return document.querySelector('.detail-add-form').checkValidity();"
    ) is False
    before = page.request_count()
    page.click('#product-dialog .detail-add-form button[type="submit"]')
    assert page.find_request("POST", "/cart", after=before) is None


@pytest.mark.cart
@pytest.mark.mutating
def test_cart_quantity_edit_sends_index_and_body(authenticated, settings):
    page = authenticated
    rows = _ensure_cart_with_item(page, settings)
    quantity = rows[0].find_element(By.CSS_SELECTOR, '.cart-quantity-form input')
    current = int(quantity.get_attribute("value"))
    new_quantity = (current + 1) if current < 1000 else (current - 1)
    before = page.request_count()
    page.fill("#cart-items .cart-item:first-child .cart-quantity-form input", str(new_quantity))
    page.click('#cart-items .cart-item:first-child .cart-quantity-form button[type="submit"]')
    request = page.wait_request("PATCH", "/cart", after=before, query={"index": 0})
    assert request["body"] == {"quantity": new_quantity}
    page.ensure_mutation_succeeded(request, settings.backend, "Quantity updated")
    if settings.strict:
        page.wait(lambda _: page.cart_rows() and
                  page.cart_rows()[0].find_element(By.CSS_SELECTOR, ".quantity-input").get_attribute("value")
                  == str(new_quantity))


@pytest.mark.cart
@pytest.mark.parametrize("quantity", ["0", "1001"])
def test_cart_edit_rejects_invalid_quantity(authenticated, settings, quantity):
    page = authenticated
    _ensure_cart_with_item(page, settings, seed_real=False)
    page.fill("#cart-items .cart-item:first-child .cart-quantity-form input", quantity)
    assert page.driver.execute_script(
        "return document.querySelector('.cart-quantity-form').checkValidity();"
    ) is False
    before = page.request_count()
    page.click('#cart-items .cart-item:first-child .cart-quantity-form button[type="submit"]')
    assert page.find_request("PATCH", "/cart", after=before) is None


@pytest.mark.cart
@pytest.mark.mutating
def test_remove_item_sends_index_zero(authenticated, settings):
    page = authenticated
    _ensure_cart_with_item(page, settings)
    before = page.request_count()
    page.accept_confirm("#cart-items .cart-item:first-child .remove-item")
    request = page.wait_request("DELETE", "/cart", after=before, query={"index": 0})
    page.ensure_mutation_succeeded(request, settings.backend, "Item removed")
    if settings.strict:
        # A real cart might still have other items; only verify it reloaded.
        page.wait_request("GET", "/cart", after=before)


@pytest.mark.cart
def test_cancel_remove_makes_no_delete_request(authenticated, settings):
    page = authenticated
    _ensure_cart_with_item(page, settings, seed_real=False)
    before = page.request_count()
    page.reject_confirm("#cart-items .cart-item:first-child .remove-item")
    assert page.find_request("DELETE", "/cart", after=before) is None


@pytest.mark.cart
@pytest.mark.mutating
def test_clear_cart(authenticated, settings):
    page = authenticated
    _ensure_cart_with_item(page, settings)
    before = page.request_count()
    page.accept_confirm("#clear-cart")
    request = page.wait_request("DELETE", "/cart/clear", after=before)
    page.ensure_mutation_succeeded(request, settings.backend, "Cart cleared")
    if settings.strict:
        page.wait(lambda _: not page.cart_rows() and "empty" in page.by_id("cart-message").text.lower())


@pytest.mark.cart
def test_cart_badge_and_subtotal_match_visible_rows(authenticated):
    page = authenticated
    page.open_cart()
    rows = page.cart_rows()
    if not rows:
        pytest.skip("Cart has no visible items (normal with a stateless Prism mock)")
    quantities = [int(row.find_element(By.CSS_SELECTOR, ".quantity-input").get_attribute("value"))
                  for row in rows]
    prices = [Decimal(row.find_element(By.CSS_SELECTOR, ".cart-item-price").text.split()[0])
              for row in rows]
    assert int(page.by_id("cart-count").text) == sum(quantities)
    subtotal = sum((price * q for price, q in zip(prices, quantities)), Decimal("0"))
    summary = page.by_id("cart-summary").text
    assert f"Subtotal: {subtotal:.2f}" in summary
    assert f"{sum(quantities)} unit" in summary

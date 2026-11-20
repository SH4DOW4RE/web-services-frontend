"""Browser integration tests for frontend ↔ api.js ↔ fake API.

Unlike the Prism E2E suite, these use a deterministic fake backend injected
before the app scripts start. They need Chrome + Selenium but NOT a running API.
"""
import contextlib
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.webdriver import WebDriver

from conftest import Settings
from pages import MarketplacePage

MOCK_SOURCE = (Path(__file__).with_name('mock_api.js')).read_text(encoding='utf-8')
UUID_HOODIE = '4b95dd13-708d-4419-b2e2-c7520a11d1a1'
PASSWORD = 'abcdAB123!@'


@pytest.fixture
def mock_page(driver: WebDriver, settings: Settings):
    """One Chrome session, one clean document per integration test.

    Register the fake fetch before navigating, then always remove its CDP
    preload hook. This prevents leaking the mock into ordinary E2E tests.
    """
    script_id = driver.execute_cdp_cmd(
        'Page.addScriptToEvaluateOnNewDocument', {'source': MOCK_SOURCE}
    )['identifier']
    try:
        # A new page is necessary to reinitialize the in-page API simulator.
        driver.get(settings.frontend_url)
        driver.execute_script(
            "localStorage.clear(); sessionStorage.clear();"
            "localStorage.setItem('mymarketplace.apiUrl', arguments[0]);",
            settings.api_url,
        )
        driver.refresh()
        page = MarketplacePage(driver, settings.timeout)
        page.wait_visible('shop-view')
        page.wait(lambda d: d.execute_script(
            "return !!window.__mockMarket && "
            "document.getElementById('products-summary').textContent.includes('3 products') && "
            "document.getElementById('cart-message').textContent.trim() !== 'Loading cart...';"
        ))
        yield page
    finally:
        with contextlib.suppress(Exception):
            driver.execute_cdp_cmd(
                'Page.removeScriptToEvaluateOnNewDocument', {'identifier': script_id}
            )


def calls(page: MarketplacePage, method: str, path: str):
    return page.driver.execute_script(
        'return window.__mockMarket.requests.filter(r => r.method === arguments[0] && r.path === arguments[1]);',
        method, path,
    )


def last(page: MarketplacePage, method: str, path: str):
    records = calls(page, method, path)
    assert records, f'No mock request: {method} {path}'
    return records[-1]


def mock_login(page: MarketplacePage) -> MarketplacePage:
    page.navigate('account')
    page.fill('#auth-username', 'bob_123')
    page.fill('#auth-password', PASSWORD)
    page.click('#auth-submit')
    page.wait(lambda _: page.is_signed_in(), 'Mock login did not finish')
    return page


def mock_add(page: MarketplacePage, quantity: int = 2) -> MarketplacePage:
    mock_login(page)
    page.navigate('shop')
    page.product_cards()[0].find_element(By.CSS_SELECTOR, '.add-to-cart-button').click()
    page.wait(lambda _: bool(calls(page, 'POST', '/cart')), 'POST /cart never happened')
    page.wait(lambda _: page.by_id('cart-count').text == '1', 'Cart badge did not refresh')
    if quantity != 1:
        # Set the in-memory fake backend; no real network request required.
        page.driver.execute_script('window.__mockMarket.cart[0].quantity = arguments[0]', quantity)
        page.navigate('cart')
        page.wait(lambda _: page.by_id('cart-count').text == str(quantity), 'Cart not updated')
    return page


@pytest.mark.integration
def test_catalog_renders_three_mocked_products(mock_page: MarketplacePage) -> None:
    page = mock_page
    assert len(page.product_cards()) == 3
    assert [n.text for n in page.all('.product-name')] == ['Hoodie', 'T-Shirt', 'Jeans']
    assert last(page, 'GET', '/products')['status'] == 200
    assert page.by_id('connection-text').text == 'API online'


@pytest.mark.integration
def test_price_sort_uses_numeric_prices(mock_page: MarketplacePage) -> None:
    page = mock_page
    Select(page.by_id('sort-products')).select_by_value('price-low')
    assert [n.text for n in page.all('.product-name')] == ['T-Shirt', 'Hoodie', 'Jeans']
    Select(page.by_id('sort-products')).select_by_value('price-high')
    assert [n.text for n in page.all('.product-name')] == ['Jeans', 'Hoodie', 'T-Shirt']


@pytest.mark.integration
def test_search_uses_correct_query_and_clear_restores_catalog(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.fill('#product-search', 'T-Shirt')
    page.click('#search-form button[type="submit"]')
    page.wait(lambda _: len(page.product_cards()) == 1)
    assert page.product_cards()[0].find_element(By.CSS_SELECTOR, '.product-name').text == 'T-Shirt'
    assert last(page, 'GET', '/products/search')['query'] == '?q=T-Shirt'
    page.click('#clear-search')
    page.wait(lambda _: len(page.product_cards()) == 3)


@pytest.mark.integration
def test_search_without_results_shows_empty_state(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.fill('#product-search', 'no-match-xyz')
    page.click('#search-form button[type="submit"]')
    page.wait(lambda _: 'No products found' in page.by_id('products-message').text)
    assert not page.product_cards()
    assert last(page, 'GET', '/products/search')['status'] == 404


@pytest.mark.integration
def test_details_dialog_displays_product_fields(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.click('.product-card:first-child .product-card-button')
    page.wait(lambda _: bool(page.all('.detail-name')))
    assert page.select('.detail-name').text == 'Hoodie'
    assert page.select('.detail-price').text == '39.95'
    assert last(page, 'GET', f'/products/{UUID_HOODIE}')['status'] == 200
    page.click('#close-dialog')
    page.wait_hidden('product-dialog')


@pytest.mark.integration
def test_login_and_logout_update_account_panels(mock_page: MarketplacePage) -> None:
    page = mock_login(mock_page)
    assert page.by_id('profile-username').text == 'bob_123'
    assert last(page, 'POST', '/user/login')['credentials'] == 'include'
    assert last(page, 'POST', '/user/login')['body'] == {'username': 'bob_123', 'password': PASSWORD}
    page.click('#logout-button')
    page.wait(lambda _: not page.is_signed_in())
    assert last(page, 'GET', '/user/logout')['status'] == 200
    assert page.by_id('user-badge').text == 'Guest'


@pytest.mark.integration
def test_register_post_and_switch_back_to_login(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.navigate('account')
    page.click('#register-tab')
    page.fill('#auth-username', 'alice_123')
    page.fill('#auth-password', PASSWORD)
    page.click('#auth-submit')
    page.wait(lambda _: page.by_id('login-tab').get_attribute('aria-selected') == 'true')
    assert last(page, 'POST', '/user/register')['body'] == {'username': 'alice_123', 'password': PASSWORD}
    assert not page.is_signed_in()


@pytest.mark.integration
def test_wrong_login_shows_api_error_without_signing_in(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.navigate('account')
    page.fill('#auth-username', 'bob_123')
    page.fill('#auth-password', 'abcdAB456!@')
    page.click('#auth-submit')
    page.wait_notice('You are not signed in')
    assert not page.is_signed_in()
    assert last(page, 'POST', '/user/login')['status'] == 401


@pytest.mark.integration
def test_card_add_sends_uuid_and_refreshes_cart(mock_page: MarketplacePage) -> None:
    page = mock_login(mock_page)
    page.navigate('shop')
    page.click('.product-card:first-child .add-to-cart-button')
    page.wait(lambda _: page.by_id('cart-count').text == '1')
    assert last(page, 'POST', '/cart')['body'] == {'product': UUID_HOODIE, 'quantity': 1}
    page.navigate('cart')
    page.wait(lambda _: len(page.cart_rows()) == 1)
    assert 'Subtotal: 39.95' in page.by_id('cart-summary').text


@pytest.mark.integration
def test_dialog_adds_requested_quantity(mock_page: MarketplacePage) -> None:
    page = mock_login(mock_page)
    page.navigate('shop')
    page.click('.product-card:first-child .product-card-button')
    page.wait(lambda _: bool(page.all('.detail-add-form .quantity-input')))
    page.fill('.detail-add-form .quantity-input', '3')
    page.click('.detail-add-form button[type="submit"]')
    page.wait(lambda _: page.by_id('cart-count').text == '3')
    assert last(page, 'POST', '/cart')['body'] == {'product': UUID_HOODIE, 'quantity': 3}
    page.click('#close-dialog')
    page.wait(lambda _: not page.by_id('product-dialog').get_attribute('open'))
    page.navigate('cart')
    page.wait(lambda _: 'Subtotal: 119.85' in page.by_id('cart-summary').text)


@pytest.mark.integration
def test_cart_update_recalculates_totals(mock_page: MarketplacePage) -> None:
    page = mock_add(mock_page, quantity=2)
    assert 'Subtotal: 79.90' in page.by_id('cart-summary').text
    page.fill('.cart-item:first-child .cart-quantity-form input', '4')
    page.click('.cart-item:first-child .cart-quantity-form button[type="submit"]')
    page.wait(lambda _: 'Subtotal: 159.80' in page.by_id('cart-summary').text)
    assert last(page, 'PATCH', '/cart')['body'] == {'quantity': 4}
    assert last(page, 'PATCH', '/cart')['query'] == '?index=0'
    assert page.by_id('cart-count').text == '4'


@pytest.mark.integration
def test_remove_cancel_makes_no_request(mock_page: MarketplacePage) -> None:
    page = mock_add(mock_page)
    page.navigate('cart')
    page.click('.cart-item:first-child .remove-item')
    page.driver.switch_to.alert.dismiss()
    assert not calls(page, 'DELETE', '/cart')
    assert len(page.cart_rows()) == 1


@pytest.mark.integration
def test_remove_confirm_deletes_cart_row(mock_page: MarketplacePage) -> None:
    page = mock_add(mock_page)
    page.navigate('cart')
    page.click('.cart-item:first-child .remove-item')
    page.driver.switch_to.alert.accept()
    page.wait(lambda _: not page.cart_rows())
    assert last(page, 'DELETE', '/cart')['query'] == '?index=0'
    assert page.by_id('cart-count').get_attribute('hidden') is not None


@pytest.mark.integration
def test_clear_cart_calls_documented_endpoint(mock_page: MarketplacePage) -> None:
    page = mock_add(mock_page)
    page.navigate('cart')
    page.click('#clear-cart')
    page.driver.switch_to.alert.accept()
    page.wait(lambda _: not page.cart_rows())
    assert last(page, 'DELETE', '/cart/clear')['status'] == 200


@pytest.mark.integration
def test_profile_edit_sends_uuid_and_updates_view(mock_page: MarketplacePage) -> None:
    page = mock_login(mock_page)
    page.fill('#new-username', 'new_bob_12')
    page.click('#username-form button[type="submit"]')
    page.wait(lambda _: page.by_id('profile-username').text == 'new_bob_12')
    sent = last(page, 'PATCH', '/user')['body']
    assert sent == {'uuid': '27463fb9-feaf-4a30-a942-35b37ea541d4', 'username': 'new_bob_12'}


@pytest.mark.integration
def test_add_while_guest_shows_unauthorized_error_and_account(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.click('.product-card:first-child .add-to-cart-button')
    page.wait_notice('You are not signed in')
    assert last(page, 'POST', '/cart')['status'] == 401
    assert not page.by_id('account-view').get_attribute('hidden')


@pytest.mark.integration
def test_api_failure_renders_message_without_fake_products(mock_page: MarketplacePage) -> None:
    page = mock_page
    page.driver.execute_script(
        "window.__mockMarket.failNext = {method:'GET', path:'/products', status:503, message:'Catalog unavailable'}"
    )
    page.click('#refresh-products')
    page.wait(lambda _: 'Catalog unavailable' in page.by_id('products-message').text)
    assert not page.product_cards()
    assert last(page, 'GET', '/products')['status'] == 503

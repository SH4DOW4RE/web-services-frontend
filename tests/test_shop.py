"""Read-only browser E2E checks for the shop and product catalog."""

from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


@pytest.mark.smoke
def test_homepage_renders_and_navigation_works(page):
    assert page.driver.title == "MyMarketplace"
    assert page.by_id("shop-view").is_displayed()
    assert page.by_id("user-badge").text  # Prism may set a user from CartModel.owner
    assert page.by_id("api-url").get_attribute("value")
    page.navigate("account")
    assert page.by_id("signed-out-panel").is_displayed() or page.by_id("signed-in-panel").is_displayed()
    page.navigate("cart")
    assert page.by_id("cart-view").is_displayed()
    page.navigate("shop")
    assert page.by_id("shop-view").is_displayed()


@pytest.mark.smoke
def test_health_request_is_made(page, settings):
    request = page.wait_request("GET", "/health")
    assert urlsplit(request["url"]).netloc == urlsplit(settings.api_url).netloc
    # A mock may return an error. Either way, the status indicator must finish.
    page.wait(lambda _: page.by_id("connection-text").text != "Checking...")
    if settings.strict:
        assert page.by_id("connection-text").text == "API online"


@pytest.mark.products
def test_product_list_and_details(page, settings):
    page.require_products()
    request = page.open_detail()
    assert request["method"] == "GET"
    assert page.by_id("product-dialog").is_displayed()
    assert page.all("#product-detail-content .detail-name") or page.all("#product-detail-content .error-text")
    if settings.strict:
        assert page.all("#product-detail-content .detail-name"), "Real backend failed to return product"
    page.close_detail()
    assert not page.by_id("product-dialog").is_displayed()


@pytest.mark.products
def test_search_sends_encoded_query_and_can_clear(page):
    search_term = "T-Shirt"  # main(5).tsp enum
    before = page.request_count()
    page.fill("#product-search", search_term)
    page.click('#search-form button[type="submit"]')
    request = page.wait_request("GET", "/products/search", after=before, query={"q": search_term})
    assert parse_qs(urlsplit(request["url"]).query)["q"] == [search_term]
    page.wait(lambda _: "Loading products" not in page.by_id("products-summary").text)
    assert page.by_id("clear-search").is_displayed()
    before = page.request_count()
    page.click("#clear-search")
    page.wait_request("GET", "/products", after=before)
    assert page.by_id("product-search").get_attribute("value") == ""


@pytest.mark.products
@pytest.mark.parametrize("sorting,reverse", [("price-low", False), ("price-high", True)])
def test_price_sorting_uses_displayed_prices(page, sorting, reverse):
    page.require_products()
    if len(page.product_cards()) < 2:
        pytest.skip("Need at least two products to test sorting")
    Select(page.by_id("sort-products")).select_by_value(sorting)
    values = [float(card.find_element(By.CSS_SELECTOR, ".product-price").text)
              for card in page.product_cards()]
    assert values == sorted(values, reverse=reverse)


@pytest.mark.products
def test_refresh_reloads_catalog(page):
    before = page.request_count()
    page.click("#refresh-products")
    page.wait_request("GET", "/products", after=before)
    page.wait(lambda _: "Loading products" not in page.by_id("products-summary").text)

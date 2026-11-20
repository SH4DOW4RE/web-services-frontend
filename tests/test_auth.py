"""Auth and profile flows. Account writes are opt-in on a real backend."""

import uuid

import pytest

VALID_PASSWORD = "abcdAB123!@"  # main(5).tsp Password scalar


@pytest.mark.auth
@pytest.mark.parametrize(
    "username,password",
    [
        ("Abcde", VALID_PASSWORD),  # uppercase username
        ("abc", VALID_PASSWORD),  # too short
        ("abcde", "abcdAB12!@"),  # too few digits
        ("abcde", "abcdAB123"),  # no suffix symbols
        ("abcde", "ABCDabcd123!@"),  # groups out of order
    ],
)
def test_invalid_auth_input_is_blocked_by_html_validation(page, username, password):
    page.ensure_signed_out()
    page.navigate("account")
    page.fill("#auth-username", username)
    page.fill("#auth-password", password)
    valid = page.driver.execute_script(
        "return document.getElementById('auth-form').checkValidity();"
    )
    assert valid is False
    before = page.request_count()
    page.click("#auth-submit")
    # Invalid HTML forms must not reach the API.
    assert not any(entry["url"].endswith(("/user/login", "/user/register"))
                   for entry in page.requests()[before:])


@pytest.mark.auth
@pytest.mark.account_changes
def test_register_submits_form_and_returns_to_login(page, settings):
    # Valid (starts with letter, 5–16 total), unique for real backends.
    username = f"e2e_{uuid.uuid4().hex[:8]}"
    before = page.request_count()
    page.register(username, VALID_PASSWORD)
    request = page.wait_request("POST", "/user/register", after=before)
    page.ensure_mutation_succeeded(request, settings.backend, "Account created")
    if request.get("status", 0) in range(200, 300):
        assert page.by_id("login-tab").get_attribute("aria-selected") == "true"
        assert not page.is_signed_in()  # Frontend requires explicit login after registering.


@pytest.mark.auth
def test_login_displays_account_and_logout(authenticated, settings):
    page = authenticated
    assert page.by_id("profile-username").text
    assert page.by_id("profile-uuid").text.startswith("User ID:")
    assert page.by_id("user-badge").text == page.by_id("profile-username").text
    before = page.request_count()
    page.click("#logout-button")
    request = page.wait_request("GET", "/user/logout", after=before)
    page.ensure_mutation_succeeded(request, settings.backend, "Logged out")
    if request.get("status", 0) in range(200, 300):
        page.wait(lambda _: not page.is_signed_in())
        assert page.by_id("user-badge").text == "Guest"


@pytest.mark.auth
def test_session_restores_on_refresh(authenticated, settings):
    page = authenticated
    before = page.by_id("profile-username").text
    # Check sessionStorage too: Prism's cart owner can independently repopulate the UI.
    key = f"mymarketplace.user.{settings.api_url}"
    saved_before = page.driver.execute_script("return sessionStorage.getItem(arguments[0]);", key)
    assert saved_before and before in saved_before
    page.driver.refresh()
    page.navigate("account")
    assert page.is_signed_in()
    assert page.by_id("profile-username").text == before
    saved_after = page.driver.execute_script("return sessionStorage.getItem(arguments[0]);", key)
    assert saved_after == saved_before


@pytest.mark.auth
@pytest.mark.account_changes
def test_change_username_sends_required_uuid(authenticated, settings):
    page = authenticated
    old_id = page.by_id("profile-uuid").text.removeprefix("User ID: ")
    new_username = f"test_{uuid.uuid4().hex[:8]}"  # Valid Username
    old_username = page.by_id("profile-username").text
    before = page.request_count()
    page.fill("#new-username", new_username)
    page.click('#username-form button[type="submit"]')
    request = page.wait_request("PATCH", "/user", after=before)
    assert set(request["keys"]) == {"uuid", "username"}
    assert request["body"]["uuid"] == old_id
    try:
        page.ensure_mutation_succeeded(request, settings.backend, "Username updated")
        if settings.strict:
            page.wait(lambda _: page.by_id("profile-username").text == new_username)
    finally:
        if settings.strict and request.get("status", 0) in range(200, 300):
            # Leave the dedicated real test account in its original state.
            before_restore = page.request_count()
            page.fill("#new-username", old_username)
            page.click('#username-form button[type="submit"]')
            restored = page.wait_request("PATCH", "/user", after=before_restore)
            assert restored.get("status") in range(200, 300), "Could not restore original username"


@pytest.mark.auth
@pytest.mark.account_changes
def test_change_password_sends_required_uuid(authenticated, settings):
    page = authenticated
    old_id = page.by_id("profile-uuid").text.removeprefix("User ID: ")
    before = page.request_count()
    page.fill("#new-password", "alphaAB123!@")
    page.click('#password-form button[type="submit"]')
    request = page.wait_request("PATCH", "/user", after=before)
    assert set(request["keys"]) == {"uuid", "password"}
    assert request["body"]["uuid"] == old_id
    # Observer never records or prints password values.
    try:
        page.ensure_mutation_succeeded(request, settings.backend, "Password updated")
        if settings.strict:
            assert page.by_id("new-password").get_attribute("value") == ""
    finally:
        if settings.strict and request.get("status", 0) in range(200, 300):
            # Restore the configured test password so subsequent tests can log in.
            before_restore = page.request_count()
            page.fill("#new-password", settings.password)
            page.click('#password-form button[type="submit"]')
            restored = page.wait_request("PATCH", "/user", after=before_restore)
            assert restored.get("status") in range(200, 300), "Could not restore original password"


@pytest.mark.auth
def test_delete_account_requires_confirmation(authenticated):
    page = authenticated
    before = page.request_count()
    page.reject_confirm("#delete-account")
    assert page.find_request("DELETE", "/user", after=before) is None
    assert page.is_signed_in()


@pytest.mark.auth
@pytest.mark.deletion
def test_delete_account(authenticated, settings):
    page = authenticated
    before = page.request_count()
    page.accept_confirm("#delete-account")
    request = page.wait_request("DELETE", "/user", after=before)
    page.ensure_mutation_succeeded(request, settings.backend, "Account deleted")
    if request.get("status", 0) in range(200, 300):
        page.wait(lambda _: not page.is_signed_in())
        assert page.by_id("user-badge").text == "Guest"

"""
Playwright End-to-End Tests for TIN4
=====================================
Requires the full Docker Compose stack to be running.
Run with:
    playwright install chromium
    pytest tests/playwright/test_e2e.py --base-url http://localhost -v
"""
import json
import re
import time

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8081"
API_URL = "http://localhost:8081/api"

# Test users (seeded by scripts/seed.py or created in tests)
USER_A = {"email": "alice_e2e@tin4example.com", "password": "pass123", "name": "Alice E2E", "age": 25}
USER_B = {"email": "bob_e2e@tin4example.com", "password": "pass123", "name": "Bob E2E", "age": 28}


# ── Helpers ────────────────────────────────────────────────────────────────

def api_register(page: Page, user: dict) -> str:
    """Register a user via the REST API and return the token."""
    res = page.request.post(f"{API_URL}/auth/register", data=json.dumps({
        "email": user["email"],
        "name": user["name"],
        "password": user["password"],
        "age": user["age"],
    }), headers={"Content-Type": "application/json"})
    if res.status == 400:
        # Already exists, login instead
        res = page.request.post(f"{API_URL}/auth/login", data=json.dumps({
            "email": user["email"],
            "password": user["password"],
        }), headers={"Content-Type": "application/json"})
    assert res.status in (200, 201), f"Auth failed: {res.text()}"
    return res.json()["access_token"]


# ── Tests ──────────────────────────────────────────────────────────────────

def test_homepage_loads(page: Page):
    """The app loads and shows the auth screen."""
    page.goto(BASE_URL)
    expect(page.locator("h1")).to_contain_text("TIN4")
    expect(page.locator("#auth-screen")).to_be_visible()
    expect(page.locator("#tech-bar")).to_be_visible()


def test_tech_badges_visible(page: Page):
    """All technology badges are shown in the tech bar."""
    page.goto(BASE_URL)
    for badge_id in ["badge-rest", "badge-ws", "badge-gql", "badge-rmq", "badge-rp", "badge-tcp"]:
        expect(page.locator(f"#{badge_id}")).to_be_visible()


def test_register_new_user(page: Page):
    """A new user can register successfully."""
    page.goto(BASE_URL)

    # Switch to register tab
    page.click("button.tab:has-text('Register')")
    expect(page.locator("#register-form")).to_be_visible()

    unique_email = f"playwright_{int(time.time())}@tin4example.com"
    page.fill("#reg-name", "Playwright User")
    page.fill("#reg-email", unique_email)
    page.fill("#reg-password", "testpass123")
    page.fill("#reg-age", "24")
    page.fill("#reg-bio", "I was created by a Playwright test")
    page.click("button:has-text('Register via REST API')")

    # Should land on the swipe screen
    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)
    expect(page.locator("#auth-screen")).not_to_be_visible()


def test_login(page: Page):
    """A registered user can log in."""
    page.goto(BASE_URL)

    # Register first (ignore errors if already exists)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)


def test_swipe_screen_has_profiles(page: Page):
    """After login, the swipe screen shows profile cards."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)
    # Should have swipe buttons
    expect(page.locator("#btn-like")).to_be_visible()
    expect(page.locator("#btn-pass")).to_be_visible()
    # Either profile cards or "no more" message
    expect(
        page.locator(".profile-card, #no-more")
    ).not_to_have_count(0, timeout=5000)


def test_swipe_buttons_work(page: Page):
    """Swipe buttons are functional and trigger REST + tech badges."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    # If there are profiles, try clicking like
    cards = page.locator(".profile-card")
    if cards.count() > 0:
        page.click("#btn-like")
        # Tech log should update
        expect(page.locator("#tech-log-entries")).not_to_be_empty()


def test_graphql_section(page: Page):
    """GraphQL section is accessible and queries work."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    # Navigate to GraphQL section
    page.click("#nav-gql")
    expect(page.locator("#gql-section")).to_be_visible()

    # Run stats query
    page.click("button:has-text('stats')")
    # Wait for response
    page.wait_for_timeout(2000)
    gql_result = page.locator("#gql-result").inner_text()
    # Should contain JSON response
    assert "data" in gql_result or "stats" in gql_result


def test_matches_section_loads(page: Page):
    """Matches section loads without error."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    page.click("#nav-matches")
    expect(page.locator("#matches-section")).to_be_visible()
    # Either shows matches or "No matches yet"
    page.wait_for_timeout(2000)
    expect(
        page.locator("#matches-list")
    ).to_be_visible()


def test_websocket_connects(page: Page):
    """WebSocket badge becomes active after login (WS connection established)."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    # WS badge should become green within 5 seconds
    expect(page.locator("#badge-ws.ws-connected")).to_be_visible(timeout=8000)


def test_tech_log_updates(page: Page):
    """The tech log at the bottom shows activity messages."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    # Tech log should have entries
    page.wait_for_timeout(2000)
    log_entries = page.locator(".log-entry")
    assert log_entries.count() > 0


def test_logout(page: Page):
    """User can log out and is returned to the auth screen."""
    page.goto(BASE_URL)
    api_register(page, USER_A)

    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)

    page.click("button.btn-logout")
    expect(page.locator("#auth-screen")).to_be_visible(timeout=5000)
    expect(page.locator("#swipe-screen")).not_to_be_visible()


def test_invalid_login_shows_error(page: Page):
    """Wrong credentials shows an error message."""
    page.goto(BASE_URL)

    page.fill("#login-email", "nonexistent@tin4.test")
    page.fill("#login-password", "wrongpassword")
    page.click("button:has-text('Login via REST API')")

    expect(page.locator("#auth-error")).to_be_visible(timeout=5000)
    expect(page.locator("#auth-screen")).to_be_visible()

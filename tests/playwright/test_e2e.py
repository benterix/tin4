"""
Playwright End-to-End Tests for TIN4 — Comprehensive Scenarios
===============================================================
Requires the full Docker Compose stack to be running.
Run with:
    playwright install chromium
    pytest tests/playwright/test_e2e.py --base-url http://localhost:8081 -v
"""
import json
import re
import time
import urllib.request
import urllib.error

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8081"
API_URL  = "http://localhost:8081/api"

USER_A = {"email": "alice_e2e@tin4example.com", "password": "pass123", "name": "Alice E2E", "age": 25, "bio": "Hiking enthusiast"}
USER_B = {"email": "bob_e2e@tin4example.com",   "password": "pass123", "name": "Bob E2E",   "age": 28, "bio": "Coffee lover"}


# ── Pure-HTTP helpers (no browser needed) ─────────────────────────────────

def _api(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{API_URL}{path}", body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _ensure_user(user):
    """Register (or login if exists). Returns (token, user_id)."""
    status, body = _api("POST", "/auth/register", {
        "email": user["email"], "name": user["name"],
        "password": user["password"], "age": user["age"],
        "bio": user.get("bio", ""),
    })
    if status not in (200, 201):
        status, body = _api("POST", "/auth/login", {
            "email": user["email"], "password": user["password"],
        })
    assert status in (200, 201), f"Setup auth failed for {user['email']}: {body}"
    _, me = _api("GET", "/auth/me", token=body["access_token"])
    return body["access_token"], me["id"]


# ── Session fixture: ensure a mutual match exists ─────────────────────────

@pytest.fixture(scope="session")
def match_setup():
    """Create USER_A + USER_B, make them mutually like each other once."""
    token_a, uid_a = _ensure_user(USER_A)
    token_b, uid_b = _ensure_user(USER_B)

    # Mutual like — 409 means already swiped, that's fine
    _api("POST", "/swipe", {"target_id": uid_b, "direction": "like"}, token=token_a)
    _api("POST", "/swipe", {"target_id": uid_a, "direction": "like"}, token=token_b)

    time.sleep(3)  # wait for match-processor

    _, matches = _api("GET", "/matches", token=token_a)
    match_id = matches[0]["id"] if matches else None

    return {
        "uid_a": uid_a, "uid_b": uid_b,
        "token_a": token_a, "token_b": token_b,
        "match_id": match_id,
    }


# ── Browser helpers ────────────────────────────────────────────────────────

def api_register(page: Page, user: dict) -> str:
    """Register via Playwright request context; login if already exists. Returns token."""
    res = page.request.post(f"{API_URL}/auth/register", data=json.dumps({
        "email": user["email"], "name": user["name"],
        "password": user["password"], "age": user["age"],
        "bio": user.get("bio", ""),
    }), headers={"Content-Type": "application/json"})
    if res.status in (400, 409):
        res = page.request.post(f"{API_URL}/auth/login", data=json.dumps({
            "email": user["email"], "password": user["password"],
        }), headers={"Content-Type": "application/json"})
    assert res.status in (200, 201), f"Auth failed ({res.status}): {res.text()}"
    return res.json()["access_token"]


def login_ui(page: Page, user: dict):
    """Navigate to the app and log in via the UI login form."""
    page.goto(BASE_URL)
    api_register(page, user)  # ensure user exists first
    page.fill("#login-email", user["email"])
    page.fill("#login-password", user["password"])
    page.click("button:has-text('Login via REST API')")
    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)


# ══ 1. AUTH TESTS ═════════════════════════════════════════════════════════

def test_homepage_loads(page: Page):
    """App loads and shows the auth screen with TIN4 heading."""
    page.goto(BASE_URL)
    expect(page.locator("h1")).to_contain_text("TIN4")
    expect(page.locator("#auth-screen")).to_be_visible()
    expect(page.locator("#tech-bar")).to_be_visible()


def test_tech_badges_visible(page: Page):
    """All six technology badges are shown in the tech bar on load."""
    page.goto(BASE_URL)
    for badge_id in ["badge-rest", "badge-ws", "badge-gql", "badge-rmq", "badge-rp", "badge-tcp"]:
        expect(page.locator(f"#{badge_id}")).to_be_visible()


def test_register_tab_switching(page: Page):
    """Login/Register tabs swap the visible form."""
    page.goto(BASE_URL)
    # Default: login visible, register hidden
    expect(page.locator("#login-form")).to_be_visible()
    expect(page.locator("#register-form")).not_to_be_visible()

    page.click("button.tab:has-text('Register')")
    expect(page.locator("#register-form")).to_be_visible()
    expect(page.locator("#login-form")).not_to_be_visible()

    page.click("button.tab:has-text('Login')")
    expect(page.locator("#login-form")).to_be_visible()
    expect(page.locator("#register-form")).not_to_be_visible()


def test_register_new_user(page: Page):
    """A brand-new user can register and is taken to the swipe screen."""
    page.goto(BASE_URL)
    page.click("button.tab:has-text('Register')")

    unique = f"pw_{int(time.time())}@tin4example.com"
    page.fill("#reg-name", "Playwright User")
    page.fill("#reg-email", unique)
    page.fill("#reg-password", "testpass123")
    page.fill("#reg-age", "24")
    page.fill("#reg-bio", "Created by a Playwright test")
    page.click("button:has-text('Register via REST API')")

    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)
    expect(page.locator("#auth-screen")).not_to_be_visible()


def test_register_duplicate_email_shows_error(page: Page):
    """Registering with an already-taken email shows an error message."""
    api_register(page, USER_A)  # ensure USER_A exists
    page.goto(BASE_URL)
    page.click("button.tab:has-text('Register')")
    page.fill("#reg-name", USER_A["name"])
    page.fill("#reg-email", USER_A["email"])
    page.fill("#reg-password", USER_A["password"])
    page.fill("#reg-age", str(USER_A["age"]))
    page.click("button:has-text('Register via REST API')")

    expect(page.locator("#auth-error")).to_be_visible(timeout=5000)
    expect(page.locator("#auth-screen")).to_be_visible()


def test_login(page: Page):
    """Registered user can log in and reaches the swipe screen."""
    page.goto(BASE_URL)
    api_register(page, USER_A)
    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", USER_A["password"])
    page.click("button:has-text('Login via REST API')")
    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)


def test_login_wrong_password_shows_error(page: Page):
    """Wrong password shows an error and stays on the auth screen."""
    page.goto(BASE_URL)
    api_register(page, USER_A)
    page.fill("#login-email", USER_A["email"])
    page.fill("#login-password", "definitelywrong999")
    page.click("button:has-text('Login via REST API')")
    expect(page.locator("#auth-error")).to_be_visible(timeout=5000)
    expect(page.locator("#auth-screen")).to_be_visible()


def test_login_unknown_email_shows_error(page: Page):
    """Completely unknown email shows an error."""
    page.goto(BASE_URL)
    page.fill("#login-email", "ghost_nobody@tin4example.com")
    page.fill("#login-password", "somepass")
    page.click("button:has-text('Login via REST API')")
    expect(page.locator("#auth-error")).to_be_visible(timeout=5000)
    expect(page.locator("#auth-screen")).to_be_visible()


def test_username_shown_in_top_bar(page: Page):
    """The logged-in user's name appears in the top bar after login."""
    login_ui(page, USER_A)
    expect(page.locator("#top-user-name")).to_contain_text(USER_A["name"])


def test_persistent_auth_after_reload(page: Page):
    """Token stored in localStorage keeps the user logged in after a page reload."""
    login_ui(page, USER_A)
    page.reload()
    expect(page.locator("#swipe-screen")).to_be_visible(timeout=10000)
    expect(page.locator("#auth-screen")).not_to_be_visible()


def test_logout(page: Page):
    """Clicking Logout returns the user to the auth screen."""
    login_ui(page, USER_A)
    page.click("button.btn-logout")
    expect(page.locator("#auth-screen")).to_be_visible(timeout=5000)
    expect(page.locator("#swipe-screen")).not_to_be_visible()


def test_logout_clears_localstorage(page: Page):
    """After logout, reloading the page shows the auth screen (token wiped)."""
    login_ui(page, USER_A)
    page.click("button.btn-logout")
    expect(page.locator("#auth-screen")).to_be_visible(timeout=5000)
    page.reload()
    expect(page.locator("#auth-screen")).to_be_visible(timeout=5000)
    expect(page.locator("#swipe-screen")).not_to_be_visible()


# ══ 2. SWIPE TESTS ════════════════════════════════════════════════════════

def test_swipe_screen_has_profiles(page: Page):
    """After login, profile cards or the 'no more' placeholder is visible."""
    login_ui(page, USER_A)
    expect(page.locator(".profile-card, #no-more")).not_to_have_count(0, timeout=5000)


def test_swipe_like_button(page: Page):
    """Clicking Like fires a REST call and adds to the tech log."""
    login_ui(page, USER_A)
    if page.locator(".profile-card").count() > 0:
        page.click("#btn-like")
        page.wait_for_timeout(500)
        log = page.locator("#tech-log-entries").inner_text()
        assert "swipe" in log.lower()


def test_swipe_pass_button(page: Page):
    """Clicking Pass fires a REST call and adds to the tech log."""
    login_ui(page, USER_A)
    if page.locator(".profile-card").count() > 0:
        page.click("#btn-pass")
        page.wait_for_timeout(500)
        log = page.locator("#tech-log-entries").inner_text()
        assert "swipe" in log.lower()


def test_swipe_triggers_broker_badges(page: Page):
    """A swipe briefly activates the RabbitMQ and Redpanda badges."""
    login_ui(page, USER_A)
    if page.locator(".profile-card").count() > 0:
        with page.expect_request(re.compile(r"/api/swipe")):
            page.click("#btn-like")
        # Verify tech log mentions both brokers
        page.wait_for_timeout(600)
        log = page.locator("#tech-log-entries").inner_text()
        assert "RabbitMQ" in log or "Redpanda" in log


def test_no_more_profiles_shows_placeholder(page: Page):
    """Swiping through all profiles reveals the 'no more' state with disabled buttons."""
    login_ui(page, USER_A)
    # Exhaust remaining profiles
    for _ in range(30):
        if page.locator(".profile-card").count() == 0:
            break
        page.click("#btn-pass")
        page.wait_for_timeout(300)

    expect(page.locator("#no-more")).to_be_visible(timeout=3000)
    expect(page.locator("#btn-like")).to_be_disabled()
    expect(page.locator("#btn-pass")).to_be_disabled()


def test_refresh_reloads_profiles(page: Page):
    """The 'Refresh' button in the no-more state calls the profiles API."""
    login_ui(page, USER_A)
    # Navigate to no-more state
    for _ in range(30):
        if page.locator(".profile-card").count() == 0:
            break
        page.click("#btn-pass")
        page.wait_for_timeout(200)

    if page.locator("#no-more").is_visible():
        with page.expect_request(re.compile(r"/api/profiles")):
            page.click("button:has-text('Refresh (REST)')")


# ══ 3. NAVIGATION TESTS ═══════════════════════════════════════════════════

def test_navigate_to_matches_section(page: Page):
    """Clicking the Matches nav hides swipe section and shows matches."""
    login_ui(page, USER_A)
    page.click("#nav-matches")
    expect(page.locator("#matches-section")).to_be_visible()
    expect(page.locator("#swipe-section")).not_to_be_visible()


def test_navigate_to_graphql_section(page: Page):
    """Clicking the GraphQL nav shows the GQL explorer."""
    login_ui(page, USER_A)
    page.click("#nav-gql")
    expect(page.locator("#gql-section")).to_be_visible()
    expect(page.locator("#swipe-section")).not_to_be_visible()


def test_navigate_back_to_swipe(page: Page):
    """Navigating to Matches then back to Discover restores the swipe section."""
    login_ui(page, USER_A)
    page.click("#nav-matches")
    expect(page.locator("#matches-section")).to_be_visible()
    page.click("#nav-swipe")
    expect(page.locator("#swipe-section")).to_be_visible()
    expect(page.locator("#matches-section")).not_to_be_visible()


def test_nav_active_class_tracks_section(page: Page):
    """The active nav button has the 'active' CSS class; others do not."""
    login_ui(page, USER_A)
    expect(page.locator("#nav-swipe")).to_have_class(re.compile(r"\bactive\b"))

    page.click("#nav-matches")
    expect(page.locator("#nav-matches")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#nav-swipe")).not_to_have_class(re.compile(r"\bactive\b"))

    page.click("#nav-gql")
    expect(page.locator("#nav-gql")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#nav-matches")).not_to_have_class(re.compile(r"\bactive\b"))


# ══ 4. MATCHES & CHAT TESTS ═══════════════════════════════════════════════

def test_matches_section_renders(page: Page):
    """Matches section loads the matches list container."""
    login_ui(page, USER_A)
    page.click("#nav-matches")
    expect(page.locator("#matches-section")).to_be_visible()
    page.wait_for_timeout(2000)
    expect(page.locator("#matches-list")).to_be_visible()


def test_match_appears_in_list(page: Page, match_setup):
    """A pre-created mutual match appears by name in the matches list."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    expect(page.locator("#matches-list")).to_contain_text(USER_B["name"])


def test_click_match_opens_chat_panel(page: Page, match_setup):
    """Clicking a match item opens the chat panel with the correct header."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    page.locator(".match-item").first.click()
    expect(page.locator("#chat-panel")).to_be_visible()
    expect(page.locator("#chat-header")).to_contain_text(USER_B["name"])


def test_send_message_via_button(page: Page, match_setup):
    """A message sent via the Send button appears in the chat bubbles."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    page.locator(".match-item").first.click()
    expect(page.locator("#chat-panel")).to_be_visible()

    msg = f"Hello via button {int(time.time())}"
    page.fill("#chat-input", msg)
    page.click("button:has-text('Send (REST)')")
    page.wait_for_timeout(500)
    expect(page.locator("#chat-messages")).to_contain_text(msg)


def test_send_message_via_enter_key(page: Page, match_setup):
    """Pressing Enter in the chat input sends the message."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    page.locator(".match-item").first.click()
    expect(page.locator("#chat-panel")).to_be_visible()

    msg = f"Hello via Enter {int(time.time())}"
    page.fill("#chat-input", msg)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    expect(page.locator("#chat-messages")).to_contain_text(msg)


def test_chat_history_loads_on_open(page: Page, match_setup):
    """Opening a chat loads previous messages from the REST API."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    # Pre-seed a message via API
    _api("POST", f"/matches/{match_setup['match_id']}/messages",
         {"body": "History seed message"}, token=match_setup["token_a"])

    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    page.locator(".match-item").first.click()
    page.wait_for_timeout(1000)
    # Should render at least the seeded bubble
    assert page.locator(".msg-bubble").count() > 0


def test_sent_messages_appear_as_mine(page: Page, match_setup):
    """Messages sent by the current user have the 'mine' CSS class."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-matches")
    page.wait_for_timeout(2000)
    page.locator(".match-item").first.click()
    expect(page.locator("#chat-panel")).to_be_visible()

    msg = f"Mine check {int(time.time())}"
    page.fill("#chat-input", msg)
    page.click("button:has-text('Send (REST)')")
    page.wait_for_timeout(500)
    # The bubble should have class 'mine'
    expect(page.locator(".msg-bubble.mine").last).to_contain_text(msg)


# ══ 5. GRAPHQL TESTS ══════════════════════════════════════════════════════

def test_graphql_stats_query(page: Page):
    """GraphQL stats query returns a valid JSON response with expected fields."""
    login_ui(page, USER_A)
    page.click("#nav-gql")
    page.click("button:has-text('stats')")
    page.wait_for_timeout(2000)
    result = page.locator("#gql-result").inner_text()
    assert "totalSwipes" in result
    assert "matchRate" in result
    assert "data" in result


def test_graphql_profiles_query(page: Page):
    """GraphQL profiles(limit:5) returns profile objects with name and age."""
    login_ui(page, USER_A)
    page.click("#nav-gql")
    page.click("button:has-text('profiles')")
    page.wait_for_timeout(2000)
    result = page.locator("#gql-result").inner_text()
    assert "name" in result
    assert "age" in result


def test_graphql_matches_query(page: Page, match_setup):
    """GraphQL myMatches query returns match data for a user with a mutual match."""
    if not match_setup["match_id"]:
        pytest.skip("Match setup failed — no match_id")
    login_ui(page, USER_A)
    page.click("#nav-gql")
    page.click("button:has-text('myMatches')")
    page.wait_for_timeout(2000)
    result = page.locator("#gql-result").inner_text()
    assert "myMatches" in result or "otherUserName" in result


def test_graphql_result_updates_on_each_query(page: Page):
    """Running two different GQL queries updates the result pane each time."""
    login_ui(page, USER_A)
    page.click("#nav-gql")

    page.click("button:has-text('stats')")
    page.wait_for_timeout(2000)
    result_after_stats = page.locator("#gql-result").inner_text()
    assert "totalSwipes" in result_after_stats

    page.click("button:has-text('profiles')")
    page.wait_for_timeout(2000)
    result_after_profiles = page.locator("#gql-result").inner_text()
    assert "name" in result_after_profiles
    # Result pane changed
    assert result_after_profiles != result_after_stats


def test_graphql_fires_request_to_graphql_endpoint(page: Page):
    """Clicking a GQL button actually sends a POST to /graphql."""
    login_ui(page, USER_A)
    page.click("#nav-gql")
    with page.expect_request(re.compile(r"/graphql")):
        page.click("button:has-text('stats')")


# ══ 6. WEBSOCKET TESTS ════════════════════════════════════════════════════

def test_websocket_badge_turns_green(page: Page):
    """WS badge gets the 'ws-connected' class within seconds of login."""
    login_ui(page, USER_A)
    expect(page.locator("#badge-ws.ws-connected")).to_be_visible(timeout=8000)


def test_websocket_log_entry_appears(page: Page):
    """Tech log shows a WS connected entry after login."""
    login_ui(page, USER_A)
    expect(page.locator("#badge-ws.ws-connected")).to_be_visible(timeout=8000)
    log = page.locator("#tech-log-entries").inner_text()
    assert "WS" in log


# ══ 7. TECH LOG TESTS ═════════════════════════════════════════════════════

def test_tech_log_has_entries_after_login(page: Page):
    """Tech log accumulates entries after login."""
    login_ui(page, USER_A)
    page.wait_for_timeout(2000)
    assert page.locator(".log-entry").count() > 0


def test_tech_log_shows_rest_entries(page: Page):
    """Tech log contains REST API entries from login and profile load."""
    login_ui(page, USER_A)
    page.wait_for_timeout(2000)
    log = page.locator("#tech-log-entries").inner_text()
    assert "REST" in log


def test_tech_log_shows_tcp_entry(page: Page):
    """Tech log contains a TCP presence polling entry."""
    login_ui(page, USER_A)
    page.wait_for_timeout(3000)
    log = page.locator("#tech-log-entries").inner_text()
    assert "TCP" in log

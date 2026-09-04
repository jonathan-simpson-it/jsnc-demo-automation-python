"""Playwright E2E tests for the Next.js frontend."""

import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3000"
SCREENSHOTS = "/tmp/webapp_screenshots"


def test_homepage(page):
    """Test homepage loads with correct content."""
    page.goto(BASE)
    page.wait_for_load_state("networkidle")

    # Check title
    title = page.title()
    assert "JonathanSimpson" in title or "AI Platform" in title, f"Bad title: {title}"

    # Check branding
    assert page.locator("text=JonathanSimpson").first.is_visible(), "Branding missing"

    # Check nav links
    nav = page.locator("nav")
    for label in ["Chat", "Documents", "Eval", "Summary", "Config"]:
        assert nav.locator(f"text={label}").is_visible(), f"Nav link '{label}' missing"

    # Check hero
    assert page.locator("text=AI Engineering Platform").first.is_visible(), "Hero missing"

    # Screenshot
    page.screenshot(path=f"{SCREENSHOTS}/01_homepage.png", full_page=True)
    print("  PASS  homepage")


def test_navigation(page):
    """Test nav links go to correct pages."""
    pages_to_test = [
        ("/chat", "PE AI assistant", "chat"),
        ("/documents", "Document Manager", "documents"),
        ("/eval", "Eval Dashboard", "eval"),
        ("/config", "Configuration", "config"),
        ("/summary", "Email Summary", "summary"),
    ]

    for href, heading, name in pages_to_test:
        page.goto(BASE + href)
        page.wait_for_load_state("networkidle")
        assert page.locator(f"text={heading}").first.is_visible(), \
            f"Page {href} missing heading '{heading}'"
        page.screenshot(path=f"{SCREENSHOTS}/02_{name}.png", full_page=True)
        print(f"  PASS  {href}")


def test_chat_page(page):
    """Test chat page has input, agent selector, send button."""
    page.goto(f"{BASE}/chat")
    page.wait_for_load_state("networkidle")

    # Welcome message
    assert page.locator("text=PE AI assistant").first.is_visible(), "Welcome msg missing"

    # Agent selector
    select = page.locator("select")
    assert select.is_visible(), "Agent selector missing"
    options = select.locator("option").all_text_contents()
    assert "Auto-route" in options, f"Auto-route not in options: {options}"
    assert "Due Diligence" in options, "Due Diligence not in options"

    # Input
    inp = page.locator('input[placeholder*="PE deals"]')
    assert inp.is_visible(), "Chat input missing"

    # Send button
    btn = page.locator("button:text('Send')")
    assert btn.is_visible(), "Send button missing"
    assert btn.is_disabled(), "Send should be disabled when empty"

    # Type something enables send
    inp.fill("What is the ARR?")
    assert not btn.is_disabled(), "Send should be enabled after typing"

    # Status badge
    assert page.locator("text=Agent:").first.is_visible(), "Agent status missing"

    page.screenshot(path=f"{SCREENSHOTS}/03_chat.png", full_page=True)
    print("  PASS  chat page")


def test_documents_page(page):
    """Test documents page has upload area."""
    page.goto(f"{BASE}/documents")
    page.wait_for_load_state("networkidle")

    # Upload area
    assert page.locator("text=Drop files here").first.is_visible(), "Upload area missing"

    # File input (hidden)
    file_input = page.locator('input[type="file"]')
    assert file_input.count() > 0, "File input missing"

    # Knowledge base section
    assert page.locator("text=Knowledge Base").first.is_visible(), "KB section missing"

    page.screenshot(path=f"{SCREENSHOTS}/04_documents.png", full_page=True)
    print("  PASS  documents page")


def test_eval_page(page):
    """Test eval page displays metrics."""
    page.goto(f"{BASE}/eval")
    page.wait_for_load_state("networkidle")

    # Check for eval content (either data or loading state)
    has_data = page.locator("text=Accuracy").first.is_visible()
    has_loading = page.locator("text=Loading eval results").first.is_visible()
    has_error = page.locator("text=No eval results found").first.is_visible()
    assert has_data or has_loading or has_error, "Eval page has no content"

    # If data loaded, check filters
    if has_data:
        assert page.locator("text=Questions").first.is_visible(), "Questions metric missing"
        selects = page.locator("select").all()
        assert len(selects) >= 2, f"Expected 2+ filter selects, got {len(selects)}"

    page.screenshot(path=f"{SCREENSHOTS}/05_eval.png", full_page=True)
    print("  PASS  eval page")


def test_config_page(page):
    """Test config page displays system info."""
    page.goto(f"{BASE}/config")
    page.wait_for_load_state("networkidle")

    # System status
    assert page.locator("text=System Status").first.is_visible(), "System Status missing"
    assert page.locator("text=API Version").first.is_visible(), "API Version missing"
    assert page.locator("text=Features").first.is_visible(), "Features missing"
    assert page.locator("text=Agent Types").first.is_visible(), "Agent Types missing"

    # Feature list
    assert page.locator("text=BM25 Hybrid Search").first.is_visible(), "BM25 feature missing"

    # Agent list
    assert page.locator("text=Due Diligence").first.is_visible(), "DD agent missing"

    page.screenshot(path=f"{SCREENSHOTS}/06_config.png", full_page=True)
    print("  PASS  config page")


def test_summary_page(page):
    """Test summary page has period buttons."""
    page.goto(f"{BASE}/summary")
    page.wait_for_load_state("networkidle")

    # Period buttons
    assert page.locator("button:text('Last 7 Days')").first.is_visible(), "7-day btn missing"
    assert page.locator("button:text('Last 30 Days')").first.is_visible(), "30-day btn missing"

    # Click 7-day button
    page.locator("button:text('Last 7 Days')").click()
    page.wait_for_timeout(2000)

    # Should show either data or no-data message
    has_data = page.locator("text=Total Queries").first.is_visible()
    has_no_data = page.locator("text=No data yet").first.is_visible()
    has_error = page.locator("text=Failed").first.is_visible()
    assert has_data or has_no_data or has_error, "Summary has no content after click"

    page.screenshot(path=f"{SCREENSHOTS}/07_summary.png", full_page=True)
    print("  PASS  summary page")


def test_footer(page):
    """Test footer renders on all pages."""
    page.goto(BASE)
    page.wait_for_load_state("networkidle")

    assert page.locator("text=Jonathan Simpson & Co.").first.is_visible(), "Footer brand missing"
    assert page.locator("text=LinkedIn").first.is_visible(), "LinkedIn link missing"

    # Check footer appears on other pages too
    page.goto(f"{BASE}/chat")
    page.wait_for_load_state("networkidle")
    assert page.locator("text=Jonathan Simpson & Co.").first.is_visible(), "Footer missing on chat"

    page.screenshot(path=f"{SCREENSHOTS}/08_footer.png", full_page=True)
    print("  PASS  footer")


def test_responsive_nav(page):
    """Test nav collapses gracefully on mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(BASE)
    page.wait_for_load_state("networkidle")

    # Branding should still be visible
    assert page.locator("text=JonathanSimpson").first.is_visible(), "Branding hidden on mobile"

    page.screenshot(path=f"{SCREENSHOTS}/09_mobile.png", full_page=True)
    print("  PASS  mobile responsive")


def main():
    import os
    os.makedirs(SCREENSHOTS, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Collect console errors
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        tests = [
            test_homepage,
            test_navigation,
            test_chat_page,
            test_documents_page,
            test_eval_page,
            test_config_page,
            test_summary_page,
            test_footer,
            test_responsive_nav,
        ]

        passed = 0
        failed = 0
        for test in tests:
            try:
                test(page)
                passed += 1
            except Exception as e:
                print(f"  FAIL  {test.__name__}: {e}")
                failed += 1

        # Report console errors
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        if real_errors:
            print(f"\n  Console errors: {len(real_errors)}")
            for e in real_errors[:5]:
                print(f"    {e[:200]}")

        browser.close()

        print(f"\n{'='*50}")
        print(f"Results: {passed}/{passed+failed} passed, {failed} failed")
        if real_errors:
            print(f"Console errors: {len(real_errors)}")
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

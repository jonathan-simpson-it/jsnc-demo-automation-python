"""Real-user playtest of the Next.js frontend.

Drives the app like a first-time visitor: clicks around, types things,
tries edge cases, checks for broken states.
"""

import sys
import os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3000"
缺陷 = []  # defects found


def defect(description, severity="medium"):
    缺陷.append({"desc": description, "severity": severity})
    sev = {"high": "HIGH", "medium": "MED", "low": "LOW"}[severity]
    print(f"  [{sev}] {description}")


def ok(description):
    print(f"  [OK]  {description}")


def playtest():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})

        # =========================================
        # 1. HOMEPAGE
        # =========================================
        print("\n=== HOMEPAGE ===")
        page = ctx.new_page()
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(BASE)
        page.wait_for_load_state("networkidle")

        # Check basic rendering
        title = page.title()
        if "JonathanSimpson" in title or "AI Platform" in title:
            ok(f"Title: {title}")
        else:
            defect(f"Title wrong: {title}", "high")

        # Check hero
        hero = page.locator("h1").first
        hero_text = hero.text_content() if hero.is_visible() else ""
        if "AI Engineering Platform" in hero_text:
            ok("Hero heading visible")
        else:
            defect(f"Hero heading missing or wrong: '{hero_text}'", "high")

        # Check nav links - click each one
        nav_links = page.locator("nav a").all()
        link_texts = [a.text_content().strip() for a in nav_links]
        expected = ["Chat", "Documents", "Eval", "Summary", "Config"]
        for exp in expected:
            if exp in link_texts:
                ok(f"Nav link '{exp}' present")
            else:
                defect(f"Nav link '{exp}' missing from nav", "high")

        # Check health status indicator
        health_text = page.locator("text=System Ready").or_(page.locator("text=Offline")).first
        if health_text.is_visible():
            ok(f"Health status: {health_text.text_content()}")
        else:
            defect("No health status indicator visible", "medium")

        # Check tool cards
        tool_cards = page.locator(".panel-card").all()
        if len(tool_cards) >= 5:
            ok(f"Tool cards: {len(tool_cards)} cards rendered")
        else:
            defect(f"Expected 5+ tool cards, got {len(tool_cards)}", "medium")

        # Click a tool card to navigate
        chat_card = page.locator("text=AI Chat").first
        if chat_card.is_visible():
            chat_card.click()
            page.wait_for_load_state("networkidle")
            if "/chat" in page.url:
                ok("Tool card 'AI Chat' navigates to /chat")
            else:
                defect(f"Clicking AI Chat card went to {page.url} instead of /chat", "high")
        else:
            defect("AI Chat tool card not found on homepage", "medium")

        # =========================================
        # 2. CHAT PAGE
        # =========================================
        print("\n=== CHAT PAGE ===")
        page.goto(f"{BASE}/chat")
        page.wait_for_load_state("networkidle")

        # Welcome message
        welcome = page.locator("text=PE AI assistant").first
        if welcome.is_visible():
            ok("Welcome message displayed")
        else:
            defect("Chat welcome message missing", "high")

        # Agent selector
        select = page.locator("select").first
        if select.is_visible():
            options = select.locator("option").all_text_contents()
            ok(f"Agent selector: {options}")
        else:
            defect("Agent selector missing", "high")

        # Input field
        inp = page.locator('input[type="text"]').first
        if inp.is_visible():
            ok("Chat input visible")
        else:
            defect("Chat input missing", "high")
            inp = None

        # Send button
        send_btn = page.locator("button:text('Send')").first
        if send_btn.is_visible():
            ok("Send button visible")
        else:
            defect("Send button missing", "high")
            send_btn = None

        # Button should be disabled when empty
        if send_btn and inp:
            if send_btn.is_disabled():
                ok("Send disabled when input empty")
            else:
                defect("Send button not disabled when input is empty", "medium")

            # Type something
            inp.fill("What is the ARR of Acme Corp?")
            page.wait_for_timeout(200)

            if not send_btn.is_disabled():
                ok("Send enabled after typing")
            else:
                defect("Send still disabled after typing", "high")

            # Press Enter to send (should trigger streaming)
            inp.press("Enter")
            page.wait_for_timeout(1000)

            # Check that user message appeared
            user_msgs = page.locator("text=What is the ARR of Acme Corp?").all()
            if len(user_msgs) > 0:
                ok("User message rendered after Enter")
            else:
                defect("User message not rendered after pressing Enter", "high")

            # Check for streaming indicator or response
            page.wait_for_timeout(3000)
            processing = page.locator("text=Processing...").first
            has_response = page.locator(".bg-surface.border").count() > 1
            has_error = page.locator("text=Error:").first.is_visible() if page.locator("text=Error:").count() > 0 else False

            if has_response:
                ok("Assistant response received")
            elif has_error:
                # This is expected when backend can't actually process (no API key)
                ok("Error response (expected without API key)")
            elif processing.is_visible():
                ok("Still processing (streaming in progress)")
            else:
                defect("No response or error after sending message", "medium")

        # Type and rapidly press Enter multiple times
        if inp:
            inp.fill("")
            inp.fill("Test rapid input")
            for _ in range(3):
                inp.press("Enter")
                page.wait_for_timeout(100)
            page.wait_for_timeout(500)
            # Should not crash
            if page.url and "/chat" in page.url:
                ok("Rapid Enter presses didn't crash")
            else:
                defect("Page crashed on rapid Enter presses", "high")

        # =========================================
        # 3. DOCUMENTS PAGE
        # =========================================
        print("\n=== DOCUMENTS PAGE ===")
        page.goto(f"{BASE}/documents")
        page.wait_for_load_state("networkidle")

        # Upload area
        drop_zone = page.locator("text=Drop files here").first
        if drop_zone.is_visible():
            ok("Drop zone visible")
        else:
            defect("Drop zone not visible", "high")

        # File input exists
        file_input = page.locator('input[type="file"]')
        if file_input.count() > 0:
            ok("File input present")
        else:
            defect("File input missing", "high")

        # Knowledge base section
        kb = page.locator("text=Knowledge Base").first
        if kb.is_visible():
            ok("Knowledge Base section visible")
        else:
            defect("Knowledge Base section missing", "medium")

        # Check for empty state or document list
        empty = page.locator("text=No documents yet").first
        docs = page.locator(".panel-card").all()
        if empty.is_visible():
            ok("Empty state shown (no documents)")
        elif len(docs) > 0:
            ok(f"Document cards visible: {len(docs)}")
        else:
            defect("Neither empty state nor document cards shown", "medium")

        # Try uploading a non-supported file type
        # Create a temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, mode="w") as f:
            f.write("test content")
            tmpfile = f.name
        try:
            file_input.set_input_files(tmpfile)
            page.wait_for_timeout(1000)
            # Check what happened - should show error or ignore
            error_shown = page.locator("text=Error:").count() > 0
            success_shown = page.locator("text=Uploaded:").count() > 0
            if error_shown:
                ok("Unsupported file type shows error")
            elif success_shown:
                defect("Unsupported file type was accepted (should reject)", "medium")
            else:
                ok("Unsupported file type handled gracefully")
        finally:
            os.unlink(tmpfile)

        # =========================================
        # 4. EVAL PAGE
        # =========================================
        print("\n=== EVAL PAGE ===")
        page.goto(f"{BASE}/eval")
        page.wait_for_load_state("networkidle")

        # Check for data or loading
        has_accuracy = page.locator("text=Accuracy").first.is_visible()
        has_loading = page.locator("text=Loading eval results").first.is_visible()
        has_error = page.locator("text=No eval results found").first.is_visible()

        if has_accuracy:
            ok("Eval data loaded with accuracy metric")

            # Check per-document breakdown
            breakdown = page.locator("text=Per-Document Breakdown").first
            if breakdown.is_visible():
                ok("Per-Document Breakdown section visible")
            else:
                defect("Per-Document Breakdown section missing", "medium")

            # Check filter dropdowns
            selects = page.locator("select").all()
            if len(selects) >= 2:
                ok(f"Filter dropdowns: {len(selects)}")

                # Try filtering by document
                doc_select = selects[0]
                doc_select.select_option(index=1)
                page.wait_for_timeout(500)
                showing = page.locator("text=Showing").first
                if showing.is_visible():
                    ok(f"Document filter works: {showing.text_content()}")
                else:
                    defect("Document filter didn't update results count", "medium")

                # Reset filter
                doc_select.select_option(index=0)
            else:
                defect(f"Expected 2+ filter selects, got {len(selects)}", "medium")

            # Check question results
            questions = page.locator("details").all()
            if len(questions) > 0:
                ok(f"Question results: {len(questions)} expandable")

                # Click first question to expand
                first_q = questions[0]
                first_q.locator("summary").click()
                page.wait_for_timeout(300)
                detail_content = first_q.locator(".text-xs.text-muted").first
                if detail_content.is_visible():
                    ok("Question details expand on click")
                else:
                    defect("Question details didn't expand", "medium")
            else:
                defect("No question results found", "medium")

        elif has_loading:
            ok("Eval loading state shown")
        elif has_error:
            ok("Eval shows no-results message")
        else:
            defect("Eval page has no content at all", "high")

        # =========================================
        # 5. CONFIG PAGE
        # =========================================
        print("\n=== CONFIG PAGE ===")
        page.goto(f"{BASE}/config")
        page.wait_for_load_state("networkidle")

        sections = ["System Status", "API Version", "Features", "Agent Types"]
        for section in sections:
            el = page.locator(f"text={section}").first
            if el.is_visible():
                ok(f"Config section: {section}")
            else:
                defect(f"Config section '{section}' missing", "medium")

        # Check system status shows actual value
        status_area = page.locator("text=Healthy").or_(page.locator("text=Degraded")).or_(page.locator("text=Checking..."))
        if status_area.first.is_visible():
            ok(f"System status value: {status_area.first.text_content()}")
        else:
            defect("No system status value shown", "medium")

        # =========================================
        # 6. SUMMARY PAGE
        # =========================================
        print("\n=== SUMMARY PAGE ===")
        page.goto(f"{BASE}/summary")
        page.wait_for_load_state("networkidle")

        # Period buttons
        week_btn = page.locator("button:text('Last 7 Days')").first
        month_btn = page.locator("button:text('Last 30 Days')").first

        if week_btn.is_visible() and month_btn.is_visible():
            ok("Period buttons visible")
        else:
            defect("Period buttons missing", "high")

        # Click 7-day
        week_btn.click()
        page.wait_for_timeout(2000)

        # Should show either data, no-data, or error
        has_data = page.locator("text=Total Queries").first.is_visible()
        has_no_data = page.locator("text=No data yet").first.is_visible()
        has_generating = page.locator("text=Generating summary").first.is_visible()

        if has_data:
            ok("Summary data loaded")

            # Check stats cards
            stats = page.locator(".panel-card.text-center").all()
            if len(stats) >= 4:
                ok(f"Stats cards: {len(stats)}")
            else:
                defect(f"Expected 4+ stats cards, got {len(stats)}", "medium")

            # Check email preview
            email_preview = page.locator("text=Email Preview").first
            if email_preview.is_visible():
                ok("Email Preview section visible")
            else:
                defect("Email Preview section missing", "medium")

        elif has_no_data:
            ok("No-data message shown (expected)")
        elif has_generating:
            ok("Generating summary...")
        else:
            defect("Summary page has no content after clicking", "medium")

        # Click 30-day
        month_btn.click()
        page.wait_for_timeout(2000)
        ok("30-day button clickable")

        # =========================================
        # 7. EDGE CASES
        # =========================================
        print("\n=== EDGE CASES ===")

        # Navigate to non-existent page
        page.goto(f"{BASE}/nonexistent")
        page.wait_for_load_state("networkidle")
        # Should show 404 or redirect
        status_text = page.locator("text=404").or_(page.locator("text=This page could not be found"))
        if status_text.count() > 0:
            ok("Non-existent page shows 404")
        else:
            content = page.text_content("body")[:100]
            defect(f"Non-existent page shows: {content}", "low")

        # Reload mid-action on chat
        page.goto(f"{BASE}/chat")
        page.wait_for_load_state("networkidle")
        inp = page.locator('input[type="text"]').first
        if inp.is_visible():
            inp.fill("Test reload")
            page.reload()
            page.wait_for_load_state("networkidle")
            # After reload, input should be cleared
            val = inp.input_value()
            if val == "":
                ok("Chat input cleared after reload")
            else:
                defect(f"Chat input not cleared after reload: '{val}'", "low")

        # Check footer on every page
        for pg in ["", "chat", "documents", "eval", "config", "summary"]:
            page.goto(f"{BASE}/{pg}")
            page.wait_for_load_state("networkidle")
            footer = page.locator("footer").first
            if footer.is_visible():
                ok(f"Footer visible on /{pg}")
            else:
                defect(f"Footer missing on /{pg}", "low")

        # =========================================
        # 8. CONSOLE ERRORS
        # =========================================
        print("\n=== CONSOLE ERRORS ===")
        real_errors = [e for e in console_errors if "favicon" not in e.lower() and "DEP0" not in e]
        if real_errors:
            for e in real_errors[:10]:
                defect(f"Console error: {e[:200]}", "medium")
        else:
            ok("No console errors")

        browser.close()

    # =========================================
    # REPORT
    # =========================================
    print(f"\n{'='*60}")
    print(f"PLAYTEST COMPLETE")
    print(f"{'='*60}")
    print(f"Defects found: {len(缺陷)}")
    high = [d for d in 缺陷 if d["severity"] == "high"]
    med = [d for d in 缺陷 if d["severity"] == "medium"]
    low = [d for d in 缺陷 if d["severity"] == "low"]
    print(f"  HIGH: {len(high)}")
    print(f"  MED:  {len(med)}")
    print(f"  LOW:  {len(low)}")
    if 缺陷:
        print("\nDefect details:")
        for i, d in enumerate(缺陷, 1):
            print(f"  {i}. [{d['severity'].upper()}] {d['desc']}")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(playtest())

"""Diagnostic: test what happens when clicking run-btn in the browser."""
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    # Capture console errors
    errors = []
    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
    page.on("requestfailed", lambda req: errors.append(f"REQUEST FAILED: {req.url} - {req.failure}"))

    # Capture fetch responses
    responses = []
    page.on("response", lambda resp: responses.append(f"{resp.status} {resp.url[:60]}"))

    # 1. Sign up
    page.goto(BASE + "/signup", wait_until="networkidle")
    page.fill("#su-institute", "Debug Institute")
    page.fill("#su-email", f"debug_{int(time.time())}@test.com")
    page.fill("#su-password", "debug123")
    page.fill("#su-confirm", "debug123")
    page.click("#signup-btn")
    page.wait_for_url("**/planner", timeout=10000)
    print("Signed up OK")

    # 2. Apply Pragyan preset
    page.wait_for_selector(".preset-btn", timeout=8000)
    page.click(".preset-btn[data-preset='pragyan']")
    page.wait_for_timeout(500)

    # 3. Override key fields
    page.fill("input[name='max_slope_deg']", "12")
    page.fill("input[name='battery_wh']", "500")
    # Don't change n_results — use preset default
    page.select_option("select[name='dem_region']", "south_pole_80_90")
    page.wait_for_timeout(300)

    # 4. Check form-status before click
    print("Before click:")
    form_status = page.locator("#form-status")
    print(f"  form-status class: {form_status.get_attribute('class')}")
    print(f"  form-status text: '{form_status.inner_text()}'")
    print(f"  form-status visible: {form_status.is_visible()}")

    # Check abs_max_slope_deg field
    try:
        abs_slope = page.locator("input[name='abs_max_slope_deg']")
        if abs_slope.count() > 0:
            print(f"  abs_max_slope_deg value: {abs_slope.first.input_value()}")
        else:
            print("  abs_max_slope_deg: field not found")
    except Exception as e:
        print(f"  abs_max_slope_deg error: {e}")

    # Check if run-btn is visible and enabled
    print(f"  run-btn visible: {page.locator('#run-btn').is_visible()}")
    print(f"  run-btn enabled: {page.locator('#run-btn').is_enabled()}")

    # Try to check button's bounding box
    try:
        bbox = page.locator('#run-btn').bounding_box()
        print(f"  run-btn bounding box: {bbox}")
    except Exception as e:
        print(f"  bbox error: {e}")

    # Scroll run-btn into view first
    page.evaluate("document.getElementById('run-btn').scrollIntoView()")
    page.wait_for_timeout(500)

    # 5. Click run using evaluate to trigger directly
    print("\nTriggering form submit via JS...")
    page.evaluate("document.getElementById('mission-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")
    page.wait_for_timeout(3000)

    # 6. Check status after click
    print("After 3s:")
    print(f"  form-status class: {form_status.get_attribute('class')}")
    print(f"  form-status text: '{form_status.inner_text()}'")
    print(f"  form-status visible: {form_status.is_visible()}")

    # Also try page.click
    print("\nNow trying page.click('#run-btn')...")
    page.click("#run-btn")
    page.wait_for_timeout(2000)
    print("After click:")
    print(f"  form-status text: '{form_status.inner_text()}'")
    print(f"  form-status visible: {form_status.is_visible()}")

    # Console errors
    print(f"\nConsole errors ({len(errors)}):")
    for e in errors[:10]:
        print(f"  {e}")

    # Network responses
    print(f"\nNetwork responses ({len(responses)}):")
    for r in responses[-15:]:
        print(f"  {r}")

    browser.close()

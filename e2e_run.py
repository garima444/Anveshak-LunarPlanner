import os, time, sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT  = "Z:/Anveshak/screenshots"
os.makedirs(OUT, exist_ok=True)

# Use a unique test email per run so re-running never hits "already exists"
TEST_EMAIL = f"demo_{int(time.time()) % 100000}@iitb.ac.in"
TEST_PASS  = "lunar123"
print(f"Using test email: {TEST_EMAIL}")

def ss(page, name, full=True):
    p = f"{OUT}/{name}.png"
    page.screenshot(path=p, full_page=full)
    sz = os.path.getsize(p) // 1024
    print(f"  [screenshot] {name}.png  ({sz} KB)")
    return p

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx     = browser.new_context(viewport={"width": 1400, "height": 900})
    page    = ctx.new_page()

    # 1. Landing page hero
    print("\n=== 1. Landing page ===")
    page.goto(BASE + "/", wait_until="networkidle")
    ss(page, "01_landing_hero", full=False)
    ss(page, "01_landing_full", full=True)

    # 2. Features
    print("\n=== 2. Features section ===")
    page.evaluate("document.querySelector('#features').scrollIntoView()")
    page.wait_for_timeout(700)
    ss(page, "02_features", full=False)

    # 3. How It Works
    print("\n=== 3. How It Works ===")
    page.evaluate("document.querySelector('#how-it-works').scrollIntoView()")
    page.wait_for_timeout(700)
    ss(page, "03_how_it_works", full=False)

    # 4. About
    print("\n=== 4. About section ===")
    page.evaluate("document.querySelector('#about').scrollIntoView()")
    page.wait_for_timeout(700)
    ss(page, "04_about", full=False)

    # 5. Contact
    print("\n=== 5. Contact section ===")
    page.evaluate("document.querySelector('#contact').scrollIntoView()")
    page.wait_for_timeout(700)
    ss(page, "05_contact", full=False)

    # 6. Footer
    print("\n=== 6. Footer ===")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    ss(page, "06_footer", full=False)

    # 7. Signup
    print("\n=== 7. Signup page ===")
    page.goto(BASE + "/signup", wait_until="networkidle")
    ss(page, "07_signup_empty")
    page.fill("#su-institute", "IIT Bombay")
    page.fill("#su-email",     TEST_EMAIL)
    page.fill("#su-password",  TEST_PASS)
    page.fill("#su-confirm",   TEST_PASS)
    page.wait_for_timeout(400)
    ss(page, "07b_signup_filled")
    page.click("#signup-btn")
    page.wait_for_url("**/planner", timeout=10000)
    print("  Signup -> /planner OK")

    # 8. Planner top
    print("\n=== 8. Planner page ===")
    page.wait_for_timeout(1200)
    ss(page, "08_planner_top", full=False)
    ss(page, "08_planner_full", full=True)

    # 9. Presets
    print("\n=== 9. Preset buttons ===")
    page.wait_for_selector(".preset-btn", timeout=8000)
    page.evaluate("document.querySelector('.preset-btn').scrollIntoView()")
    page.wait_for_timeout(600)
    ss(page, "09_presets", full=False)
    page.click(".preset-btn[data-preset='pragyan']")
    page.wait_for_timeout(700)
    ss(page, "09b_pragyan_applied", full=False)

    # 10. Traverse card
    print("\n=== 10. Traverse card ===")
    page.evaluate("document.querySelector('.form-card--coral').scrollIntoView()")
    page.wait_for_timeout(400)
    ss(page, "10_traverse_card", full=False)

    # 11. Science card
    print("\n=== 11. Science card ===")
    page.evaluate("document.querySelector('.form-card--mint').scrollIntoView()")
    page.wait_for_timeout(400)
    ss(page, "11_science_card", full=False)

    # 12. Configure Pragyan mission
    print("\n=== 12. Configure mission ===")
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(300)
    page.click(".preset-btn[data-preset='pragyan']")
    page.wait_for_timeout(500)
    page.fill("input[name='rover_name']",   "Pragyan-2")
    page.fill("input[name='mission_name']", "Chandrayaan-4")
    page.fill("input[name='agency']",       "ISRO")
    page.select_option("select[name='mission_type']", "water_ice")
    page.select_option("select[name='power_source']", "rtg")
    page.fill("input[name='max_slope_deg']",  "12")
    page.fill("input[name='battery_wh']",     "500")
    page.select_option("select[name='n_results']", "3")
    page.select_option("select[name='dem_region']", "south_pole_80_90")
    page.locator("#science-experiments-select").select_option(["volatile_detection", "geomorphology"])
    page.fill("input[name='priority']", "0.4")
    page.evaluate("document.querySelector('.planner-submit-bar').scrollIntoView()")
    page.wait_for_timeout(400)
    ss(page, "12_mission_configured", full=False)

    # 13. Run mission — submit via JS to bypass HTML5 form validation and Unicode issues
    print("\n=== 13. Running mission (may take 30-300s on first run) ===")
    # Dispatch form submit directly so emoji-containing status text won't cause issues
    page.evaluate("""
        document.getElementById('mission-form').dispatchEvent(
            new Event('submit', {bubbles: true, cancelable: true})
        )
    """)
    page.wait_for_timeout(1500)
    ss(page, "13_analysis_running", full=False)
    print("  Waiting for results (up to 7 min)...")
    import time as _time
    t_start = _time.time()
    result_shown = False
    for _check in range(30):  # 30 × 15s = 450s max
        try:
            page.wait_for_selector("#results-area:not(.hidden)", timeout=15000)
            result_shown = True
            break
        except Exception:
            elapsed = int(_time.time() - t_start)
            print(f"  [{elapsed}s] Still waiting...")
            if _check % 3 == 0:
                ss(page, f"13_wait_{elapsed:04d}s", full=False)
    if not result_shown:
        raise TimeoutError("Results never appeared after 7.5 minutes")
    page.wait_for_timeout(2500)
    print(f"  Results ready! (took {int(_time.time()-t_start)}s)")

    # 14. Mission Summary
    print("\n=== 14. Mission Summary ===")
    page.evaluate("document.querySelector('#results-area').scrollIntoView()")
    page.wait_for_timeout(700)
    ss(page, "14_mission_summary", full=False)

    # 15. Path Stats
    print("\n=== 15. Path Statistics ===")
    page.evaluate("document.querySelector('#path-stats-grid').scrollIntoView()")
    page.wait_for_timeout(500)
    ss(page, "15_path_stats", full=False)

    # 16. Landing sites table
    print("\n=== 16. Landing sites table ===")
    page.evaluate("document.querySelector('#sites-table').scrollIntoView()")
    page.wait_for_timeout(500)
    ss(page, "16_landing_sites", full=False)

    # 17. Mission Map
    print("\n=== 17. Mission map ===")
    page.evaluate("document.querySelector('#map-container').scrollIntoView()")
    page.wait_for_timeout(2500)
    ss(page, "17_mission_map", full=False)

    # 18. Score Chart
    print("\n=== 18. Score chart ===")
    page.evaluate("document.querySelector('#chart-container').scrollIntoView()")
    page.wait_for_timeout(2000)
    ss(page, "18_score_chart", full=False)

    # 19. Full results
    print("\n=== 19. Full results page ===")
    ss(page, "19_full_results", full=True)

    # 20. Login — must log out first (user is logged in from step 7 signup)
    print("\n=== 20. Login page ===")
    page.goto(BASE + "/logout", wait_until="load")  # clears anveshak_user cookie
    page.wait_for_timeout(500)
    page.goto(BASE + "/login", wait_until="load")
    page.wait_for_timeout(800)
    ss(page, "20_login_empty")
    print(f"  Login page URL: {page.url}")
    page.wait_for_selector("#login-email", timeout=10000)
    page.fill("#login-email",    TEST_EMAIL)
    page.fill("#login-password", TEST_PASS)
    ss(page, "20b_login_filled")
    page.click("button[type='submit']")
    page.wait_for_url("**/planner", timeout=8000)
    print("  Login OK -> /planner")

    # 21. Planner logged in with user chip
    print("\n=== 21. Planner with user chip ===")
    page.wait_for_timeout(800)
    ss(page, "21_planner_logged_in", full=False)

    # 22. Solar toggle
    print("\n=== 22. Solar fieldset toggle ===")
    page.select_option("select[name='power_source']", "solar")
    page.wait_for_timeout(400)
    page.evaluate("document.querySelector('#solar-fieldset').scrollIntoView()")
    page.wait_for_timeout(400)
    ss(page, "22_solar_fieldset", full=False)
    page.select_option("select[name='power_source']", "rtg")

    # 23. Login error — logout first, then test wrong credentials
    print("\n=== 23. Login error state ===")
    page.goto(BASE + "/logout", wait_until="load")
    page.wait_for_timeout(300)
    page.goto(BASE + "/login", wait_until="load")
    page.wait_for_selector("#login-email", timeout=8000)
    page.fill("#login-email",    "wrong@email.com")
    page.fill("#login-password", "badpass")
    page.click("button[type='submit']")
    page.wait_for_timeout(1500)
    ss(page, "23_login_error")

    # 24. Demo run — snapshot only (full analysis same as step 13, skip heavy wait)
    print("\n=== 24. Demo run snapshot ===")
    page.goto(BASE + "/planner", wait_until="networkidle")
    page.wait_for_timeout(800)
    ss(page, "24_planner_fresh", full=False)
    # Show demo button
    page.evaluate("document.getElementById('demo-btn').scrollIntoView()")
    page.wait_for_timeout(400)
    ss(page, "24b_demo_btn", full=False)
    print("  Demo UI captured (skipping heavy analysis re-run)")

    browser.close()

print(f"\nDone! All screenshots saved to Z:/Anveshak/screenshots/")
files = sorted(os.listdir("Z:/Anveshak/screenshots"))
for f in files:
    size = os.path.getsize(f"Z:/Anveshak/screenshots/{f}") // 1024
    print(f"  {f}  ({size} KB)")

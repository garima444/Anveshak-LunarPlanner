/**
 * e2e.js — Anveshak full end-to-end walkthrough with screenshots
 *
 * Scenario: VIPER (NASA) rover — Water Ice mission, PSR-rim strategy,
 *           full south-pole 80–90°S DEM, 5 landing sites.
 *
 * Captures:
 *   01 — Home page (blank form, presets loaded)
 *   02 — VIPER preset applied (form auto-filled)
 *   03 — Form scrolled to show PSR + Science sections
 *   04 — "Analysis running" spinner / status message
 *   05 — Results: Mission Summary + Path Stats
 *   06 — Results: Top Landing Sites table
 *   07 — Results: Mission Map (Plotly terrain heatmap)
 *   08 — Results: Score Chart (bar chart)
 *   09 — Full-page results snapshot
 */

const { chromium } = require('playwright');
const path  = require('path');
const fs    = require('fs');

const BASE_URL = 'http://127.0.0.1:8765';
const OUT_DIR  = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

const shot     = (name, page) => page.screenshot({ path: path.join(OUT_DIR, name), fullPage: false });
const shotFull = (name, page) => page.screenshot({ path: path.join(OUT_DIR, name), fullPage: true });
const wait     = (ms) => new Promise(r => setTimeout(r, ms));
const log      = (msg) => console.log(msg);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx     = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page    = await ctx.newPage();

  // Capture fetch responses for logging
  page.on('response', resp => {
    if (resp.url().endsWith('/analyze') || resp.url().endsWith('/demo')) {
      log(`   [${resp.status()}] ${resp.url()}`);
    }
  });

  // ── 1. Home page — blank form ──────────────────────────────────────────
  log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  log('1. Loading home page…');
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
  await wait(800);
  await shotFull('01_home_blank_form.png', page);
  log('   ✓ 01_home_blank_form.png  (blank form, preset buttons loaded)');

  // ── 2. Apply VIPER preset ──────────────────────────────────────────────
  log('2. Applying VIPER (NASA) preset…');
  await page.waitForFunction(() => {
    const g = document.getElementById('preset-group');
    return g && g.querySelectorAll('button').length > 0;
  }, null, { timeout: 10000 });

  const viperBtn = page.locator('button[data-preset="viper"]');
  if (await viperBtn.count() > 0) {
    await viperBtn.click();
  } else {
    const btns = page.locator('#preset-group button');
    const n = await btns.count();
    for (let i = 0; i < n; i++) {
      const txt = await btns.nth(i).textContent();
      if (txt.toLowerCase().includes('viper')) { await btns.nth(i).click(); break; }
    }
  }
  await wait(600);

  // Show solar fieldset (VIPER = solar)
  const solarFs = page.locator('#solar-fieldset');
  if (await solarFs.count() > 0) await solarFs.scrollIntoViewIfNeeded();

  await shotFull('02_viper_preset.png', page);
  log('   ✓ 02_viper_preset.png  (VIPER preset: solar, 20° slope, 450 Wh, 430 kg)');

  // ── 3. Tweak mission settings ──────────────────────────────────────────
  log('3. Setting mission details…');
  await page.locator('[name="mission_name"]').fill('VIPER Mission — Shackleton Rim');
  await page.locator('[name="agency"]').fill('NASA / Ames Research Center');
  await page.locator('[name="psr_intent"]').selectOption('rim');
  await page.locator('[name="n_results"]').selectOption('5');
  // Science experiments: select volatile detection + mineralogy
  const sciSel = page.locator('#science-experiments-select');
  await sciSel.selectOption({ value: 'volatile_detection' });
  // Ctrl+click to add mineralogy
  await page.keyboard.down('Control');
  await sciSel.selectOption({ value: 'mineralogy' });
  await page.keyboard.up('Control');

  // Scroll to show PSR + science fieldsets
  await page.locator('#science-fieldset').scrollIntoViewIfNeeded();
  await wait(400);
  await shot('03_form_psr_science.png', page);
  log('   ✓ 03_form_psr_science.png  (PSR=rim, science experiments selected)');

  // Scroll back to top for the full form view
  await page.keyboard.press('Home');
  await wait(300);

  // ── 4. Submit form ─────────────────────────────────────────────────────
  log('4. Submitting "Run Mission Planner"…');
  const t0 = Date.now();
  await page.locator('#run-btn').click();
  await wait(700);

  // Screenshot while spinner is visible
  await shot('04_analysis_running.png', page);
  log('   ✓ 04_analysis_running.png  (status: "Analysing terrain…")');

  // ── 5. Wait for results (up to 4 minutes) ─────────────────────────────
  log('   Waiting for /analyze to complete (terrain is cached ≈ 90–120 s)…');
  await page.waitForFunction(
    () => {
      const el = document.getElementById('results-area');
      return el && !el.classList.contains('hidden');
    },
    null,
    { timeout: 240000, polling: 2000 }
  );
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  log(`   ✓ Results ready — total time ${elapsed} s`);

  // Let Plotly iframes render
  await wait(3000);

  // ── 6. Mission Summary + Path Stats ───────────────────────────────────
  log('5. Screenshot: Mission Summary + Path Stats…');
  await page.keyboard.press('Home');
  await wait(500);
  await page.locator('#results-area').scrollIntoViewIfNeeded();
  await wait(400);
  await shot('05_mission_summary.png', page);
  log('   ✓ 05_mission_summary.png');

  // ── 7. Soft terrain section (if visible) ──────────────────────────────
  const softSec = page.locator('#soft-terrain-section');
  const softVis = await softSec.evaluate(el => !el.classList.contains('hidden')).catch(() => false);
  if (softVis) {
    await softSec.scrollIntoViewIfNeeded();
    await wait(300);
    await shot('05b_soft_terrain.png', page);
    log('   ✓ 05b_soft_terrain.png  (Bekker-Wong bearing assessment)');
  }

  // ── 8. Landing Sites Table ─────────────────────────────────────────────
  log('6. Screenshot: Top Landing Sites table…');
  await page.locator('#sites-table').scrollIntoViewIfNeeded();
  await wait(400);
  await shot('06_landing_sites_table.png', page);
  log('   ✓ 06_landing_sites_table.png');

  // ── 9. Mission Map ─────────────────────────────────────────────────────
  log('7. Screenshot: Mission Map (terrain heatmap)…');
  await page.locator('#map-container').scrollIntoViewIfNeeded();
  await wait(2000);  // let Plotly iframe settle
  await shot('07_mission_map.png', page);
  log('   ✓ 07_mission_map.png');

  // ── 10. Score Chart ────────────────────────────────────────────────────
  log('8. Screenshot: Score Chart…');
  await page.locator('#chart-container').scrollIntoViewIfNeeded();
  await wait(1500);
  await shot('08_score_chart.png', page);
  log('   ✓ 08_score_chart.png');

  // ── 11. Full-page results snapshot ────────────────────────────────────
  log('9. Full-page results (scroll reset)…');
  await page.keyboard.press('Home');
  await wait(600);
  await shotFull('09_full_page_results.png', page);
  log('   ✓ 09_full_page_results.png  (complete results page)');

  // ── 12. Extract text data ──────────────────────────────────────────────
  log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  log('EXTRACTED ANALYSIS RESULTS:');

  const summary = await page.locator('#mission-summary').textContent().catch(() => '—');
  log('\n📋 MISSION SUMMARY:\n' + summary.trim());

  const statsHTML = await page.locator('#path-stats-grid').innerHTML().catch(() => '');
  const statLabels = [...statsHTML.matchAll(/stat-label[^>]*>([^<]+)</g)].map(m => m[1].trim());
  const statValues = [...statsHTML.matchAll(/stat-value[^>]*>([^<]+)</g)].map(m => m[1].trim());
  log('\n📊 PATH STATISTICS:');
  statLabels.forEach((l, i) => log(`   ${l.padEnd(18)} ${statValues[i] || '—'}`));

  const tableRows = await page.locator('#sites-tbody tr').allTextContents().catch(() => []);
  log('\n🌑 TOP LANDING SITES:');
  tableRows.forEach((row, i) => {
    const cols = row.split(/\s{2,}/).filter(c => c.trim());
    log(`   Site ${i+1}: ${cols.join(' | ')}`);
  });

  const battWarnTxt = await page.locator('#battery-warning').textContent().catch(() => '');
  if (battWarnTxt.trim()) log('\n⚠  BATTERY: ' + battWarnTxt.trim());

  const softMsg = await page.locator('#soft-terrain-msg').textContent().catch(() => '');
  if (softMsg.trim()) log('\n🪨 SOFT TERRAIN: ' + softMsg.trim());

  const aoiChip = await page.locator('#aoi-active-chip').textContent().catch(() => '');
  if (aoiChip.trim()) log('\n📍 AOI: ' + aoiChip.trim());

  await browser.close();

  // ── 13. File summary ──────────────────────────────────────────────────
  log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  log('SCREENSHOTS SAVED TO ./screenshots/');
  fs.readdirSync(OUT_DIR).sort().forEach(f => {
    if (!f.endsWith('.png') && !f.endsWith('.json')) return;
    const sz = Math.round(fs.statSync(path.join(OUT_DIR, f)).size / 1024);
    log(`  ${f.padEnd(42)} ${sz} KB`);
  });
  log('\nAll done ✓');
})().catch(err => {
  console.error('\nFATAL:', err.message);
  process.exit(1);
});

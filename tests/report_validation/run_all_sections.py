"""
tests/report_validation/run_all_sections.py
───────────────────────────────────────────
Master runner for the Anveshak Report Validation Suite.

Runs all 8 thematic validation sections, saves logs and PNG images,
then compiles everything into a single self-contained HTML report.

Usage:
    cd Z:\\Anveshak
    python -m tests.report_validation.run_all_sections

    # Run with a flag to skip slow real-DEM sections:
    python -m tests.report_validation.run_all_sections --synthetic-only
"""

from __future__ import annotations

import argparse
import base64
import gc
import io
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# ── Force UTF-8 stdout on Windows (prevents cp1252 UnicodeEncodeError for
#    box-drawing characters used in section headers) ─────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.report_validation.utils import (
    IMAGES_DIR,
    LOGS_DIR,
    OUTPUT_ROOT,
    TeeOutput,
    build_lat_grid_safe,
    ensure_dirs,
    load_real_terrain_safe,
    safe_run_section,
)

import tests.report_validation.section_01_module_verification  as sec01
import tests.report_validation.section_02_classifier_accuracy  as sec02
import tests.report_validation.section_03_historical_validation as sec03
import tests.report_validation.section_04_lcross_validation    as sec04
import tests.report_validation.section_05_combination_matrix   as sec05
import tests.report_validation.section_06_science_routing      as sec06
import tests.report_validation.section_07_performance          as sec07
import tests.report_validation.section_08_limitations          as sec08


# ── Section registry ──────────────────────────────────────────────────────────
SECTIONS = [
    ("Section 1: Module Verification",        sec01),
    ("Section 2: Classifier Accuracy",        sec02),
    ("Section 3: Historical Mission Validation", sec03),
    ("Section 4: LCROSS Ice Site Validation", sec04),
    ("Section 5: Mission Combination Matrix", sec05),
    ("Section 6: Science Routing",            sec06),
    ("Section 7: Performance Benchmarks",     sec07),
    ("Section 8: Known Limitations",          sec08),
]


# ─────────────────────────────────────────────────────────────────────────────
# HTML generation
# ─────────────────────────────────────────────────────────────────────────────

_RESULT_COLORS = {
    "PASS": "#22c55e",
    "WARN": "#f59e0b",
    "FAIL": "#ef4444",
    "SKIP": "#6b7280",
}

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0a0a1a;
  color: #e2e8f0;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  padding: 24px;
}
h1 { font-size: 2rem; color: #c4b5fd; margin-bottom: 6px; }
h2 { font-size: 1.3rem; color: #a5b4fc; margin: 0; }
h3 { font-size: 1.1rem; color: #94a3b8; margin-bottom: 10px; }
.subtitle { color: #64748b; margin-bottom: 24px; font-size: 0.9rem; }
.banner {
  background: #1e1b4b;
  border: 1px solid #4338ca;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.banner .icon { font-size: 1.5rem; }
.banner .text { font-size: 0.95rem; color: #a5b4fc; }
.banner .dem-source { font-weight: 700; color: #818cf8; }
.exec-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 32px;
  background: #111827;
  border-radius: 8px;
  overflow: hidden;
}
.exec-table th {
  background: #1e293b;
  color: #94a3b8;
  font-weight: 600;
  text-align: left;
  padding: 10px 14px;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.exec-table td {
  padding: 10px 14px;
  border-top: 1px solid #1e293b;
}
.exec-table tr:hover td { background: #1a2235; }
.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 9999px;
  font-weight: 700;
  font-size: 0.8rem;
  letter-spacing: 0.05em;
}
.badge-PASS { background: #14532d; color: #22c55e; }
.badge-WARN { background: #451a03; color: #f59e0b; }
.badge-FAIL { background: #450a0a; color: #ef4444; }
.badge-SKIP { background: #1e293b; color: #94a3b8; }
details {
  background: #111827;
  border: 1px solid #1e293b;
  border-radius: 8px;
  margin-bottom: 16px;
  overflow: hidden;
}
summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
  background: #0f172a;
  list-style: none;
}
summary::-webkit-details-marker { display: none; }
summary:hover { background: #1e293b; }
.chevron { transition: transform 0.2s; font-style: normal; }
details[open] .chevron { transform: rotate(90deg); }
.section-body { padding: 18px; }
.section-meta {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  color: #64748b;
  font-size: 0.88rem;
}
.section-meta span { display: flex; align-items: center; gap: 5px; }
.notes-box {
  background: #0f172a;
  border-left: 3px solid #4338ca;
  border-radius: 0 6px 6px 0;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 0.9rem;
  color: #94a3b8;
  font-family: 'Consolas', monospace;
}
.images-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.images-grid img {
  border-radius: 6px;
  border: 1px solid #1e293b;
  max-width: 100%;
  cursor: zoom-in;
}
.log-block {
  background: #020617;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 12px 14px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 0.78rem;
  color: #64748b;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}
.checks-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
}
.check-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 0.88rem;
}
.check-pass { color: #22c55e; }
.check-warn { color: #f59e0b; }
.check-fail { color: #ef4444; }
.check-name { color: #94a3b8; }
.check-detail { color: #475569; font-size: 0.82rem; }
.footer {
  margin-top: 40px;
  padding-top: 16px;
  border-top: 1px solid #1e293b;
  color: #475569;
  font-size: 0.82rem;
  text-align: center;
}
.overall-bar {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 28px;
}
.stat-card {
  background: #111827;
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 14px 20px;
  min-width: 130px;
  text-align: center;
}
.stat-card .stat-value { font-size: 1.8rem; font-weight: 700; }
.stat-card .stat-label { font-size: 0.78rem; color: #64748b; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.05em; }
"""

_JS = """
document.querySelectorAll('.images-grid img').forEach(img => {
  img.addEventListener('click', () => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.92);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:zoom-out;';
    const big = img.cloneNode();
    big.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:8px;object-fit:contain;';
    overlay.appendChild(big);
    overlay.addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);
  });
});
"""


def _img_b64(path: Path) -> str | None:
    """Return a base64 data URI for a PNG, or None if file doesn't exist."""
    if not path.exists():
        return None
    raw = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _badge(result: str) -> str:
    cls = f"badge-{result}" if result in _RESULT_COLORS else "badge-SKIP"
    return f'<span class="badge {cls}">{result}</span>'


def _check_icon(result: str) -> str:
    return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "—"}.get(result, "·")


def _render_checks(checks: list[dict]) -> str:
    if not checks:
        return ""
    items = []
    for c in checks:
        res   = c.get("result", "SKIP")
        name  = c.get("check", "?")
        val   = c.get("value", "")
        exp   = c.get("expected", "")
        icon  = _check_icon(res)
        cls   = {"PASS": "check-pass", "WARN": "check-warn",
                 "FAIL": "check-fail"}.get(res, "")
        detail = ""
        if val or exp:
            detail = f'<span class="check-detail">({val}{"→" + str(exp) if exp else ""})</span>'
        items.append(
            f'<div class="check-item"><span class="{cls}">{icon}</span>'
            f'<span class="check-name">{name}</span>{detail}</div>'
        )
    return '<div class="checks-list">' + "".join(items) + "</div>"


def _render_section(idx: int, result: dict) -> str:
    name     = result.get("test_name", f"Section {idx + 1}")
    res      = result.get("result", "SKIP")
    notes    = result.get("notes", "")
    passed   = result.get("passed", 0)
    total    = result.get("total", 0)
    elapsed  = result.get("_elapsed_s", 0.0)
    images   = result.get("images", [])
    checks   = result.get("checks", [])
    log_file = result.get("log", "")

    # progress bar text
    frac_str = f"{passed}/{total}" if total > 0 else "—"

    # images (embed base64)
    imgs_html = ""
    if images:
        imgs_parts = []
        for p in images:
            uri = _img_b64(Path(p))
            if uri:
                fname = Path(p).name
                imgs_parts.append(
                    f'<img src="{uri}" alt="{fname}" style="max-height:340px;" title="{fname}">'
                )
        if imgs_parts:
            imgs_html = '<div class="images-grid">' + "".join(imgs_parts) + "</div>"

    # log content (first 200 lines to keep HTML size manageable)
    log_html = ""
    if log_file and Path(log_file).exists():
        lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
        shown = lines[:200]
        tail  = f"\n\n… ({len(lines) - 200} more lines, see {log_file})" if len(lines) > 200 else ""
        log_html = (
            '<details style="margin-top:12px;">'
            f'<summary style="font-size:0.85rem;color:#64748b;cursor:pointer;">📄 Raw log ({len(lines)} lines)</summary>'
            f'<div class="log-block">{chr(10).join(shown)}{tail}</div>'
            "</details>"
        )

    checks_html = _render_checks(checks)

    return f"""
<details {'open' if res == 'FAIL' else ''}>
  <summary>
    <i class="chevron">›</i>
    <h2>§{idx + 1} {name}</h2>
    <span style="margin-left:auto;display:flex;align-items:center;gap:10px;">
      <span style="color:#64748b;font-size:0.85rem;">{frac_str} checks · {elapsed:.1f}s</span>
      {_badge(res)}
    </span>
  </summary>
  <div class="section-body">
    <div class="section-meta">
      <span>⏱️ {elapsed:.2f}s</span>
      <span>✔️ {passed}/{total} checks</span>
    </div>
    <div class="notes-box">{notes}</div>
    {imgs_html}
    {checks_html}
    {log_html}
  </div>
</details>
"""


def _build_html_report(all_results: list[dict], is_real: bool, run_ts: str) -> str:
    ensure_dirs()

    # Overall stats
    totals = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for r in all_results:
        k = r.get("result", "SKIP")
        totals[k] = totals.get(k, 0) + 1

    dem_source = "NASA DEM (real)" if is_real else "Synthetic terrain (no DEM file)"
    dem_color  = "#22c55e" if is_real else "#f59e0b"
    dem_icon   = "🛰️" if is_real else "⚙️"

    # Executive summary table rows
    exec_rows = ""
    for i, r in enumerate(all_results):
        name    = r.get("test_name", f"Section {i+1}")
        res     = r.get("result", "SKIP")
        passed  = r.get("passed", 0)
        total   = r.get("total", 0)
        elapsed = r.get("_elapsed_s", 0.0)
        notes   = r.get("notes", "")[:120]
        exec_rows += (
            f"<tr>"
            f"<td>{i+1}</td>"
            f"<td style='font-weight:600'>{name}</td>"
            f"<td>{_badge(res)}</td>"
            f"<td style='color:#64748b'>{passed}/{total}</td>"
            f"<td style='color:#64748b'>{elapsed:.1f}s</td>"
            f"<td style='color:#94a3b8;font-size:0.82rem'>{notes}</td>"
            f"</tr>"
        )

    # Overall stats cards
    stat_cards = ""
    for label, key, color in [
        ("Sections", "PASS", "#22c55e"),
        ("Warnings", "WARN", "#f59e0b"),
        ("Failures", "FAIL", "#ef4444"),
        ("Skipped",  "SKIP", "#6b7280"),
    ]:
        cnt = totals.get(key, 0)
        stat_cards += (
            f'<div class="stat-card">'
            f'<div class="stat-value" style="color:{color}">{cnt}</div>'
            f'<div class="stat-label">{label} {key}</div>'
            f"</div>"
        )

    # Total checks across all sections
    total_checks  = sum(r.get("total", 0) for r in all_results)
    passed_checks = sum(r.get("passed", 0) for r in all_results)
    total_elapsed = sum(r.get("_elapsed_s", 0.0) for r in all_results)

    stat_cards += (
        f'<div class="stat-card">'
        f'<div class="stat-value" style="color:#818cf8">{passed_checks}/{total_checks}</div>'
        f'<div class="stat-label">Total Checks</div>'
        f"</div>"
        f'<div class="stat-card">'
        f'<div class="stat-value" style="color:#64748b">{total_elapsed:.0f}s</div>'
        f'<div class="stat-label">Total Time</div>'
        f"</div>"
    )

    # Section blocks
    section_blocks = "\n".join(_render_section(i, r) for i, r in enumerate(all_results))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anveshak — Report Validation Suite</title>
  <style>{_CSS}</style>
</head>
<body>

<h1>🌙 Anveshak Lunar Mission Planner</h1>
<p class="subtitle">Report Validation Suite · Generated {run_ts}</p>

<div class="banner">
  <span class="icon">{dem_icon}</span>
  <span class="text">
    DEM Source: <span class="dem-source" style="color:{dem_color}">{dem_source}</span>
    &nbsp;·&nbsp; Sections with real-DEM dependency fall back to synthetic when data is absent.
  </span>
</div>

<div class="overall-bar">
  {stat_cards}
</div>

<h3>Executive Summary</h3>
<table class="exec-table">
  <thead>
    <tr>
      <th>#</th><th>Section</th><th>Result</th>
      <th>Checks</th><th>Time</th><th>Notes</th>
    </tr>
  </thead>
  <tbody>
    {exec_rows}
  </tbody>
</table>

<h3>Section Details</h3>
{section_blocks}

<div class="footer">
  Anveshak Lunar Mission Planner · Report Validation Package<br>
  Generated {run_ts} · Python {sys.version.split()[0]}<br>
  <em>All images are base64-embedded — this HTML is self-contained.</em>
</div>

<script>{_JS}</script>
</body>
</html>
"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────

def main(synthetic_only: bool = False) -> None:
    ensure_dirs()

    run_ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    master_log_path = LOGS_DIR / "MASTER_LOG.txt"
    html_path       = OUTPUT_ROOT / "REPORT_VALIDATION.html"
    all_json_path   = OUTPUT_ROOT / "all_results.json"

    tee = TeeOutput(master_log_path)
    old_stdout = sys.stdout
    sys.stdout = tee

    try:
        print("═" * 70)
        print("  ANVESHAK — REPORT VALIDATION SUITE")
        print(f"  Started: {run_ts}")
        print("═" * 70)
        print()

        # ── Load terrain once ────────────────────────────────────────────────
        print("  Loading terrain …")
        t_load = time.perf_counter()
        if synthetic_only:
            print("  --synthetic-only flag: skipping real DEM load")
            from core.landing_scorer import _synthetic_terrain
            elev, slope, rough, profile = _synthetic_terrain(shape=(300, 300))
            is_real = False
        else:
            elev, slope, rough, profile, is_real = load_real_terrain_safe()

        print(f"  Terrain loaded in {time.perf_counter() - t_load:.2f}s — "
              f"{'REAL NASA DEM' if is_real else 'SYNTHETIC FALLBACK'}")
        print(f"  Shape: {elev.shape}")
        print()

        # Pre-cache lat grid once so sections don't recompute it 8 times
        print("  Building lat grid (caching) …")
        t_lat = time.perf_counter()
        profile["_lat_grid_cache"] = build_lat_grid_safe(profile)
        print(f"  Lat grid ready in {time.perf_counter() - t_lat:.2f}s")
        print()
        gc.collect()

        # ── Run each section ─────────────────────────────────────────────────
        all_results: list[dict] = []
        for i, (label, mod) in enumerate(SECTIONS):
            sec_num = i + 1
            print("─" * 70)
            print(f"  RUNNING §{sec_num}: {label}")
            print("─" * 70)

            result = safe_run_section(mod, elev, slope, rough, profile, str(OUTPUT_ROOT))
            result.setdefault("test_name", label)
            all_results.append(result)

            # Crash-safety: write per-section JSON immediately
            sec_json = OUTPUT_ROOT / f"section_{sec_num:02d}_result.json"
            try:
                sec_json.write_text(
                    json.dumps(result, indent=2, default=str), encoding="utf-8"
                )
            except Exception as exc:
                print(f"  [warn] Could not write section JSON: {exc}")

            res_str = result.get("result", "SKIP")
            passed  = result.get("passed", 0)
            total   = result.get("total", 0)
            elapsed = result.get("_elapsed_s", 0.0)
            print()
            print(f"  §{sec_num} Result: {res_str}  ({passed}/{total} checks in {elapsed:.1f}s)")
            print()
            gc.collect()

        # ── Write combined JSON ───────────────────────────────────────────────
        print("─" * 70)
        print("  Writing combined results JSON …")
        try:
            all_json_path.write_text(
                json.dumps(all_results, indent=2, default=str), encoding="utf-8"
            )
            print(f"  → {all_json_path}")
        except Exception as exc:
            print(f"  [warn] JSON write failed: {exc}")

        # ── Build HTML report ─────────────────────────────────────────────────
        print()
        print("  Building HTML report …")
        try:
            html = _build_html_report(all_results, is_real, run_ts)
            html_path.write_text(html, encoding="utf-8")
            size_kb = html_path.stat().st_size // 1024
            print(f"  → {html_path}  ({size_kb} KB)")
        except Exception as exc:
            print(f"  [ERROR] HTML generation failed: {exc}")
            traceback.print_exc()

        # ── Final summary ─────────────────────────────────────────────────────
        print()
        print("═" * 70)
        print("  FINAL SUMMARY")
        print("═" * 70)
        totals = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for r in all_results:
            k = r.get("result", "SKIP")
            totals[k] = totals.get(k, 0) + 1

        total_checks  = sum(r.get("total",  0) for r in all_results)
        passed_checks = sum(r.get("passed", 0) for r in all_results)
        total_elapsed = sum(r.get("_elapsed_s", 0.0) for r in all_results)

        print(f"  PASS sections:  {totals['PASS']}/8")
        print(f"  WARN sections:  {totals['WARN']}/8")
        print(f"  FAIL sections:  {totals['FAIL']}/8")
        print(f"  Total checks:   {passed_checks}/{total_checks} passed")
        print(f"  Total time:     {total_elapsed:.1f}s")
        print()
        print(f"  HTML report:  {html_path}")
        print(f"  Master log:   {master_log_path}")
        print(f"  JSON data:    {all_json_path}")
        print()
        print("  Open REPORT_VALIDATION.html in any browser.")
        print("═" * 70)

    finally:
        sys.stdout = old_stdout
        tee.close()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Anveshak Report Validation Suite — runs all 8 sections and generates HTML report"
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        help="Skip real DEM loading and use synthetic terrain throughout",
    )
    args = parser.parse_args()
    main(synthetic_only=args.synthetic_only)

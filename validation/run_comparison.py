"""
validation/run_comparison.py — Validation Suite Comparison Runner.

Runs all 14 validation tests in two modes:
  Mode 1 (with ancillary):    standard load — all ancillary files used when present
  Mode 2 (without ancillary): same terrain, ancillary keys stripped from profile

Reveals which tests depend on PSR mask, solar illumination, Diviner temperature,
crater density, etc. and quantifies the impact of missing ancillary data.

Usage
-----
  python validation/run_comparison.py                # full run (~90–120 min)
  python validation/run_comparison.py --affected-only  # only re-run affected tests (~45 min)
  python validation/run_comparison.py --help

Outputs
-------
  validation/COMPARISON_REPORT.md
  validation/results/comparison_with_ancillary.json
  validation/results/comparison_without_ancillary.json
  validation/results/comparison_delta.json
  validation/results/with_anc/   (individual test JSONs, mode 1)
  validation/results/no_anc/     (individual test JSONs, mode 2)
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VALIDATION_DIR = Path(__file__).parent
RESULTS_BASE   = VALIDATION_DIR / "results"
REPORT_PATH    = VALIDATION_DIR / "COMPARISON_REPORT.md"


# ---------------------------------------------------------------------------
# Ancillary stripping helpers
# ---------------------------------------------------------------------------

_STRIP_KEYS = [
    "psr_mask",
    "illumination_map",
    "earth_visibility",
    "sky_visibility",
    "diviner_coltemp",
    "m3_oh_band",
    "crater_density",
]

# test_chandrayaan3 self-loads its own terrain region and ignores the runner's
# profile; stripping ancillary from the runner profile has no effect on it.
_SELF_LOADING_TESTS = {"test_chandrayaan3"}

# Tests where ancillary data is expected to change results meaningfully.
_AFFECTED_TESTS = {
    "test_artemis3",
    "test_sensitivity",
    "test_historical_missions",
    "test_ancillary_layers",
    "test_real_dem_sanity",
}


def _make_no_anc_profile(elevation, profile: dict) -> dict:
    """Return a shallow copy of profile with all ancillary layers set to None.

    sunlight_map is replaced with the synthetic estimate so energy / recharge
    calculations still run (they just use a lower-fidelity illumination model).
    """
    prof = copy.copy(profile)
    for key in _STRIP_KEYS:
        prof[key] = None
    # Synthetic fallback for sunlight (latitude-based estimate, no file needed)
    try:
        from core.energy_model import estimate_sunlight  # noqa: PLC0415
        prof["sunlight_map"] = estimate_sunlight(elevation, prof)
    except Exception:
        prof["sunlight_map"] = None
    return prof


# ---------------------------------------------------------------------------
# Delta detection
# ---------------------------------------------------------------------------

_DELTA_KEYS = [
    "result",
    "average_overlap",
    "n_missions_validated",
    "n_predictions_validated",
    "lcross_validated",
    "n_pass",
    "spearman_diagnosis",
    # ancillary-layer test sub-results
    "12a_illumination", "12b_psr_mask", "12c_earth_visibility",
    "12d_psr_safety",   "12e_solar_rtg",
]


def _extract_key_metrics(r: dict) -> dict:
    """Pull the most informative scalar metrics from a result dict."""
    metrics = {}
    for key in _DELTA_KEYS:
        val = r.get(key)
        if val is not None:
            metrics[key] = val
    # Nested checks dict (from test_ancillary_layers etc.)
    checks = r.get("checks", {})
    for k in ["12a_illumination","12b_psr_mask","12c_earth_visibility",
              "12d_psr_safety","12e_solar_rtg"]:
        if k in checks:
            metrics[k] = checks[k]
    return metrics


def _has_changed(r_with: dict, r_no: dict) -> bool:
    """Return True if the result meaningfully changed between the two modes."""
    if r_with.get("result") != r_no.get("result"):
        return True
    m1 = _extract_key_metrics(r_with)
    m2 = _extract_key_metrics(r_no)
    for key in m1:
        if key in m2 and m1[key] != m2[key]:
            return True
    return False


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_ALL_TESTS = [
    "test_chandrayaan3",
    "test_artemis3",
    "test_sensitivity",
    "test_dbscan_params",
    "test_classifier_cv",
    "test_pathfinder",
    "test_energy_model",
    "test_slope_accuracy",
    "test_roughness_accuracy",
    "test_pipeline_e2e",
    "test_historical_missions",
    "test_ancillary_layers",
    "test_real_dem_sanity",
    "test_mobility",
]


def _run_one(
    short_name: str,
    elevation, slope, roughness, profile,
    results_dir: Path,
) -> dict:
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    try:
        mod = importlib.import_module(f"validation.{short_name}")
    except Exception as exc:
        return {
            "test_name": short_name, "result": "FAIL",
            "notes": f"Import failed: {exc}",
        }
    t0 = time.perf_counter()
    try:
        r = mod.run(elevation, slope, roughness, profile, str(results_dir), str(plots_dir))
    except Exception as exc:
        r = {
            "test_name": short_name, "result": "FAIL",
            "notes": f"Unhandled exception: {exc}\n{traceback.format_exc()}",
        }
    r["_runtime_s"] = round(time.perf_counter() - t0, 2)
    return r


def _run_suite(
    tests: list[str],
    elevation, slope, roughness, profile,
    results_dir: Path,
    label: str,
) -> list[dict]:
    results_dir.mkdir(parents=True, exist_ok=True)
    all_results = []
    print(f"\n{'='*70}")
    print(f"  Running {len(tests)} tests ({label})")
    print(f"{'='*70}")
    for name in tests:
        print(f"\n[{label}] {name} ...")
        r = _run_one(name, elevation, slope, roughness, profile, results_dir)
        v = r.get("result", "?")
        print(f"  → {v}  ({r.get('_runtime_s', '?')}s)")
        all_results.append(r)
    return all_results


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

_EMOJI = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}
_SELF_NOTE = "self-loading (65–80°S region) — runner-profile stripping has no effect"


def _verdict_line(v: str) -> str:
    return f"{_EMOJI.get(v, '?')} {v}"


def generate_comparison_report(
    results_with: list[dict],
    results_no:   list[dict] | None,
    deltas:       list[dict],
    affected_only: bool,
) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    lines: list[str] = []

    def _counts(results):
        n_p = sum(1 for r in results if r.get("result") == "PASS")
        n_w = sum(1 for r in results if r.get("result") == "WARN")
        n_f = sum(1 for r in results if r.get("result") == "FAIL")
        n_s = sum(1 for r in results if r.get("result") == "SKIP")
        return n_p, n_w, n_f, n_s

    p1, w1, f1, s1 = _counts(results_with)
    total = len(results_with)

    lines += [
        "# Anveshak Validation — Ancillary Data Comparison Report\n\n",
        f"**Generated**: {ts}\n\n",
        f"**Mode 1 (With Ancillary)**:    {p1}/{total} PASS · {w1} WARN · {f1} FAIL · {s1} SKIP\n",
    ]

    if results_no:
        p2, w2, f2, s2 = _counts(results_no)
        lines.append(f"**Mode 2 (Without Ancillary)**: {p2}/{total} PASS · {w2} WARN · {f2} FAIL · {s2} SKIP\n")
    else:
        n_aff = len(_AFFECTED_TESTS)
        lines.append(f"**Mode 2 (Without Ancillary)**: affected-only mode — {n_aff} tests re-run\n")

    lines.append("\n---\n\n")

    # ---- Executive comparison table -------------------------------------------
    lines.append("## Executive Comparison Table\n\n")
    lines.append("| # | Test | With Ancillary | Without Ancillary | Changed? |\n")
    lines.append("|---|------|----------------|-------------------|----------|\n")

    # Build lookup maps
    with_by_name = {r.get("test_name", r.get("_short", "?")): r for r in results_with}
    no_by_name   = {r.get("test_name", r.get("_short", "?")): r for r in (results_no or [])}
    delta_by_name = {d["test_name"]: d for d in deltas}

    for i, name in enumerate(_ALL_TESTS, 1):
        # Find result by short name (test_name may differ from module name)
        r_w = next((r for r in results_with if r.get("_short") == name), None)
        if r_w is None:
            # Fall back to test_name field match
            for r in results_with:
                if name.replace("test_", "").replace("_", " ").lower() in r.get("test_name", "").lower():
                    r_w = r
                    break
        if r_w is None and i - 1 < len(results_with):
            r_w = results_with[i - 1]

        v_w = _verdict_line(r_w.get("result", "?")) if r_w else "—"

        if name in _SELF_LOADING_TESTS:
            v_no = f"n/a ({_SELF_NOTE[:40]}…)"
            changed = "—"
        elif results_no:
            r_no = next((r for r in results_no if r.get("_short") == name), None)
            if r_no is None and i - 1 < len(results_no):
                r_no = results_no[i - 1]
            v_no = _verdict_line(r_no.get("result", "?")) if r_no else "—"
            changed = "**⚡ YES**" if delta_by_name.get(name, {}).get("changed") else "no"
        elif affected_only and name in _AFFECTED_TESTS:
            r_no = next((r for r in results_no or [] if r.get("_short") == name), None)
            v_no = _verdict_line(r_no.get("result", "?")) if r_no else "not run"
            changed = "**⚡ YES**" if delta_by_name.get(name, {}).get("changed") else "no"
        else:
            v_no = "not run" if affected_only else "—"
            changed = "—"

        lines.append(f"| {i} | {name} | {v_w} | {v_no} | {changed} |\n")

    lines.append("\n---\n\n")

    # ---- Changed tests detail -------------------------------------------------
    changed_deltas = [d for d in deltas if d.get("changed")]
    if changed_deltas:
        lines.append("## Tests Where Ancillary Data Made a Difference\n\n")
        for d in changed_deltas:
            tname = d["test_name"]
            lines.append(f"### {tname}\n\n")
            v_w = d.get("result_with_anc", "?")
            v_n = d.get("result_no_anc", "?")
            lines.append(f"- **With ancillary**: {_EMOJI.get(v_w,'')} {v_w}\n")
            lines.append(f"- **Without ancillary**: {_EMOJI.get(v_n,'')} {v_n}\n")
            m_w = d.get("metrics_with_anc", {})
            m_n = d.get("metrics_no_anc", {})
            if m_w or m_n:
                all_keys = set(m_w) | set(m_n)
                for k in sorted(all_keys):
                    vw = m_w.get(k, "—")
                    vn = m_n.get(k, "—")
                    marker = " ← **CHANGED**" if vw != vn else ""
                    lines.append(f"  - `{k}`: with={vw}, without={vn}{marker}\n")
            lines.append("\n")
        lines.append("---\n\n")

    # ---- Full results: With Ancillary -----------------------------------------
    lines.append("## Full Results: With Ancillary Data\n\n")
    lines.append("| # | Test | Result | Runtime | Notes |\n")
    lines.append("|---|------|--------|---------|-------|\n")
    for i, r in enumerate(results_with, 1):
        v   = r.get("result", "?")
        nm  = r.get("test_name", f"Test {i}")
        rt  = r.get("_runtime_s", "?")
        nt  = (r.get("notes", "") or "")[:120]
        lines.append(f"| {i} | {nm} | {_EMOJI.get(v,'')} {v} | {rt}s | {nt} |\n")
    lines.append("\n---\n\n")

    # ---- Full results: Without Ancillary (if available) -----------------------
    if results_no:
        lines.append("## Full Results: Without Ancillary Data\n\n")
        lines.append("| # | Test | Result | Runtime | Notes |\n")
        lines.append("|---|------|--------|---------|-------|\n")
        for i, r in enumerate(results_no, 1):
            v   = r.get("result", "?")
            nm  = r.get("test_name", f"Test {i}")
            rt  = r.get("_runtime_s", "?")
            nt  = (r.get("notes", "") or "")[:120]
            lines.append(f"| {i} | {nm} | {_EMOJI.get(v,'')} {v} | {rt}s | {nt} |\n")
        lines.append("\n---\n\n")

    # ---- Interpretation -------------------------------------------------------
    lines.append("## Interpretation\n\n")
    if not changed_deltas:
        lines.append(
            "No tests changed between ancillary and no-ancillary modes. "
            "This means either: (a) the ancillary files were not loaded in mode 1 "
            "(check data/PSR/, data/SolarIllumination/ for expected files), or "
            "(b) the tests do not use ancillary data in their current configuration.\n\n"
        )
    else:
        n_changed = len(changed_deltas)
        lines.append(f"{n_changed} test(s) produced different results with ancillary data enabled:\n\n")
        for d in changed_deltas:
            vw = d.get("result_with_anc", "?")
            vn = d.get("result_no_anc", "?")
            if vw == "PASS" and vn != "PASS":
                lines.append(
                    f"- **{d['test_name']}**: Ancillary data is REQUIRED to pass this test. "
                    f"Without it the test degrades from {vw} to {vn}. "
                    f"Ensure the relevant ancillary files are present in data/.\n"
                )
            elif vw != "PASS" and vn == "PASS":
                lines.append(
                    f"- **{d['test_name']}**: Unexpectedly, this test passes WITHOUT ancillary "
                    f"but fails WITH ancillary — likely indicates a data quality issue with "
                    f"a loaded ancillary file.\n"
                )
            else:
                lines.append(
                    f"- **{d['test_name']}**: Result changed ({vw} → {vn}). "
                    f"Review key metrics above for details.\n"
                )
        lines.append(
            "\n**Conclusion**: For production mission planning, the ancillary files "
            "(PSR mask, solar illumination) are important for correct water-ice mission scoring "
            "and PSR-proximity hazard assessment. The system is functional without them "
            "(proxy fallbacks activate automatically), but quantitative scores will differ.\n"
        )

    return "".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Anveshak Validation Comparison Runner")
    parser.add_argument(
        "--affected-only", action="store_true",
        help="Only re-run the 5 ancillary-affected tests in no-anc mode (faster)"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  ANVESHAK VALIDATION — ANCILLARY DATA COMPARISON")
    print("=" * 70)

    # ---- Setup result directories ------------------------------------------
    with_anc_dir = RESULTS_BASE / "with_anc"
    no_anc_dir   = RESULTS_BASE / "no_anc"
    with_anc_dir.mkdir(parents=True, exist_ok=True)
    no_anc_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load terrain ONCE --------------------------------------------------
    print("\n[comparison] Loading terrain with ancillary data …")
    try:
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain()
        print(f"[comparison] Terrain loaded: {elevation.shape}, "
              f"res={profile.get('resolution_m','?')}m/px")
        anc_loaded = {k: (profile.get(k) is not None)
                      for k in _STRIP_KEYS + ["sunlight_map"]}
        print("[comparison] Ancillary layers loaded:")
        for k, ok in anc_loaded.items():
            print(f"  {'OK' if ok else '--'}  {k}")
    except Exception as exc:
        print(f"[comparison] load_terrain failed ({exc}), falling back to synthetic 500×500")
        from core.landing_scorer import _synthetic_terrain
        elevation, slope, roughness, profile = _synthetic_terrain(shape=(500, 500))

    # ---- Mode 1: With ancillary ---------------------------------------------
    mode1_results = _run_suite(
        _ALL_TESTS, elevation, slope, roughness, profile,
        with_anc_dir, label="WITH-ANCILLARY",
    )
    # Tag each result with the test's short name for delta detection
    for r, name in zip(mode1_results, _ALL_TESTS):
        r["_short"] = name
        r["ancillary_mode"] = "enabled"

    # ---- Mode 2: Without ancillary ------------------------------------------
    profile_no = _make_no_anc_profile(elevation, profile)
    print(f"\n[comparison] Ancillary keys stripped for mode 2.")

    if args.affected_only:
        tests_to_rerun = [t for t in _ALL_TESTS if t in _AFFECTED_TESTS]
        print(f"[comparison] --affected-only: re-running {len(tests_to_rerun)} tests in no-anc mode")
    else:
        tests_to_rerun = _ALL_TESTS

    mode2_results = _run_suite(
        tests_to_rerun, elevation, slope, roughness, profile_no,
        no_anc_dir, label="NO-ANCILLARY",
    )
    for r, name in zip(mode2_results, tests_to_rerun):
        r["_short"] = name
        r["ancillary_mode"] = "disabled"

    # For self-loading tests in mode 2 list, mark them appropriately
    if not args.affected_only:
        for r in mode2_results:
            if r.get("_short") in _SELF_LOADING_TESTS:
                r["_comparison_note"] = _SELF_NOTE

    # ---- Build delta list ---------------------------------------------------
    deltas: list[dict] = []
    mode2_by_short = {r.get("_short", ""): r for r in mode2_results}

    for r_w in mode1_results:
        name = r_w.get("_short", "")
        if name in _SELF_LOADING_TESTS:
            deltas.append({
                "test_name":      r_w.get("test_name", name),
                "changed":        False,
                "note":           _SELF_NOTE,
            })
            continue

        r_n = mode2_by_short.get(name)
        if r_n is None:
            deltas.append({
                "test_name":      r_w.get("test_name", name),
                "result_with_anc": r_w.get("result"),
                "result_no_anc":  "not run",
                "changed":        False,
            })
            continue

        changed = _has_changed(r_w, r_n)
        deltas.append({
            "test_name":        r_w.get("test_name", name),
            "result_with_anc":  r_w.get("result"),
            "result_no_anc":    r_n.get("result"),
            "changed":          changed,
            "metrics_with_anc": _extract_key_metrics(r_w),
            "metrics_no_anc":   _extract_key_metrics(r_n),
            "_runtime_with_s":  r_w.get("_runtime_s"),
            "_runtime_no_s":    r_n.get("_runtime_s"),
        })

    # ---- Summary printout ---------------------------------------------------
    print("\n" + "=" * 70)
    print("  COMPARISON SUMMARY")
    print("=" * 70)
    for d in deltas:
        marker = "  ⚡ CHANGED" if d.get("changed") else ""
        vw = d.get("result_with_anc", "—")
        vn = d.get("result_no_anc",   "—")
        name = d.get("test_name", "?")
        print(f"  {vw:4s} → {vn:4s}  {name}{marker}")

    n_changed = sum(1 for d in deltas if d.get("changed"))
    print(f"\n  {n_changed} test(s) changed between modes.")

    # ---- Write JSON outputs -------------------------------------------------
    def _strip_internal(result_list):
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in result_list]

    with open(RESULTS_BASE / "comparison_with_ancillary.json", "w", encoding="utf-8") as f:
        json.dump(_strip_internal(mode1_results), f, indent=2, default=str)
    print(f"\n[comparison] → {RESULTS_BASE / 'comparison_with_ancillary.json'}")

    with open(RESULTS_BASE / "comparison_without_ancillary.json", "w", encoding="utf-8") as f:
        json.dump(_strip_internal(mode2_results), f, indent=2, default=str)
    print(f"[comparison] → {RESULTS_BASE / 'comparison_without_ancillary.json'}")

    with open(RESULTS_BASE / "comparison_delta.json", "w", encoding="utf-8") as f:
        json.dump(deltas, f, indent=2, default=str)
    print(f"[comparison] → {RESULTS_BASE / 'comparison_delta.json'}")

    # ---- Generate markdown report -------------------------------------------
    report_md = generate_comparison_report(
        results_with=mode1_results,
        results_no=mode2_results,
        deltas=deltas,
        affected_only=args.affected_only,
    )
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print(f"[comparison] → {REPORT_PATH}")
    print("\n[comparison] Done.")


if __name__ == "__main__":
    main()

"""
validation/validation_runner.py — Anveshak Validation Suite Orchestrator.

Loads terrain once, runs all 10 tests, writes results/*.json, generates
VALIDATION_REPORT.md.

Usage:
    python validation/validation_runner.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RESULTS_DIR = Path(__file__).parent / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
REPORT_PATH = Path(__file__).parent / "VALIDATION_REPORT.md"


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def _verdict_emoji(v: str) -> str:
    return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(v, "❓")


def generate_report(all_results: list[dict]) -> None:
    n_pass = sum(1 for r in all_results if r.get("result") == "PASS")
    n_warn = sum(1 for r in all_results if r.get("result") == "WARN")
    n_fail = sum(1 for r in all_results if r.get("result") == "FAIL")
    n_skip = sum(1 for r in all_results if r.get("result") == "SKIP")
    total = len(all_results)

    lines: list[str] = []
    lines.append("# Anveshak Validation Report\n")
    lines.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n")
    lines.append(f"**Overall**: {n_pass}/{total} PASS · {n_warn} WARN · {n_fail} FAIL · {n_skip} SKIP\n")

    if n_fail == 0 and n_warn == 0:
        status = f"ALL TESTS PASSED" + (f" ({n_skip} SKIPPED — awaiting data download)" if n_skip else "")
    elif n_fail == 0 and n_warn > 0:
        # WARNs indicate real algorithmic issues that require attention.
        status = f"WARNINGS PRESENT: {n_warn} test(s) have known issues requiring review"
    else:
        status = f"{n_fail} FAILURE(S)"

    lines.append(f"**Status**: {status}\n")
    lines.append("\n---\n")

    # Executive summary table
    lines.append("## Executive Summary\n")
    lines.append("| # | Test | Result | Key Metric |\n")
    lines.append("|---|------|--------|------------|\n")
    for i, r in enumerate(all_results, start=1):
        v = r.get("result", "?")
        name = r.get("test_name", f"Test {i}")
        note = r.get("notes", "")
        if len(note) > 120:
            note = note[:117] + "..."
        lines.append(f"| {i} | {name} | {_verdict_emoji(v)} {v} | {note} |\n")
    lines.append("\n")

    # Per-test sections
    lines.append("---\n\n## Per-Test Details\n")
    for i, r in enumerate(all_results, start=1):
        v = r.get("result", "?")
        name = r.get("test_name", f"Test {i}")
        lines.append(f"\n### Test {i}: {name} — {_verdict_emoji(v)} {v}\n\n")

        skip_keys = {"test_name", "result", "notes"}

        def fmt(val, depth=0):
            indent = "  " * depth
            if isinstance(val, dict):
                rows = []
                for k, v2 in val.items():
                    rows.append(f"{indent}- **{k}**: {fmt(v2, depth+1)}")
                return "\n" + "\n".join(rows)
            elif isinstance(val, list) and len(val) <= 10 and all(not isinstance(x, (dict, list)) for x in val):
                return str(val)
            elif isinstance(val, list):
                return f"[{len(val)} items]"
            else:
                return str(val)

        for k, val in r.items():
            if k in skip_keys:
                continue
            if isinstance(val, dict) and len(val) <= 15:
                lines.append(f"**{k}**:\n")
                for kk, vv in val.items():
                    lines.append(f"- `{kk}`: {vv}\n")
                lines.append("\n")
            elif isinstance(val, list) and len(val) <= 5:
                lines.append(f"**{k}**: {val}\n\n")
            else:
                lines.append(f"**{k}**: {val}\n\n")

        notes = r.get("notes", "")
        if notes:
            lines.append(f"> **Notes**: {notes}\n\n")

    # Limitations
    lines.append("---\n\n## Limitations\n\n")
    limits = [
        "Test 1 (Chandrayaan-3 at 69.373°S) loads the 65–80°S DEM region independently. It will SKIP if LDEM_75S_30MPP_ADJ.tiff is missing from data/dem/.",
        "Classifier CV (Test 5) uses synthetic terrain (300×300) rather than the full NASA DEM to keep runtime under 2 minutes.",
        "Sensitivity analysis (Test 3) Spearman ≥ 0.999 is diagnosed as terrain-driven (all top sites are flat) vs slope dominance (varied slopes). See spearman_diagnosis field.",
        "Historical mission Test 11 uses 30% distance tolerance and 70% PSR confidence threshold. LCROSS Cabeus landmark check requires score_terrain to succeed (may be skipped on OOM).",
        "Energy model (Test 7) has no sensor-noise model — all slopes and elevations are exact synthetic values. BASE_POWER_W=100W (compare: VIPER ~100-130W, Artemis rover ~200W).",
        "No multi-session repeatability testing; all tests run once with deterministic seeds.",
        "Roughness-slope correlation (Test 9d) uses linear gradient patches; real crater terrain has non-linear roughness profiles not covered by this synthetic test.",
        "Diviner cold-trap temperature layer is a coarse RGB display image (~8 km/px). Science proxy (PSR+elevation) remains the primary ice-stability indicator at 60m scale.",
        "M3 OH-band not loaded (near-zero coverage below 80°S). DEM elevation-gradient proxy is used for mineralogy science maps.",
        "Crater density not loaded. Run scripts/generate_crater_density.py after downloading Robbins 2019 catalog from https://zenodo.org/record/3528686.",
        "Combination coverage (Test 15) uses synthetic terrain — PSR/illumination-dependent physics checks are skipped when those ancillary maps are absent. Run test_combinations.py for the full 25–35 min real-DEM integration test.",
    ]
    for lim in limits:
        lines.append(f"- {lim}\n")
    lines.append("\n")

    REPORT_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"\n[runner] VALIDATION_REPORT.md written -> {REPORT_PATH}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse as _argparse
    parser = _argparse.ArgumentParser(description="Anveshak Validation Runner")
    parser.add_argument("--report-only", action="store_true",
                        help="Regenerate VALIDATION_REPORT.md from existing JSON results")
    parser.add_argument("--strip-ancillary", action="store_true",
                        help="Strip all ancillary layers after loading — tests proxy/baseline behaviour")
    args = parser.parse_args()

    if args.report_only:
        report_from_existing()
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    mode_label = "NO-ANCILLARY (proxy fallback)" if args.strip_ancillary else "WITH ANCILLARY"
    print("=" * 70)
    print(f"  ANVESHAK VALIDATION SUITE  [{mode_label}]")
    print("=" * 70)

    # ---- Load terrain ONCE -----------------------------------------------
    print("\n[runner] Loading terrain ...")
    try:
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain()
        print(f"[runner] Real terrain loaded: {elevation.shape}, res={profile.get('resolution_m', '?')}m/px")
        anc_status = {k: (profile.get(k) is not None)
                      for k in ["psr_mask","illumination_map","earth_visibility","diviner_coltemp"]}
        print(f"[runner] Ancillaries: {anc_status}")
    except Exception as exc:
        print(f"[runner] load_terrain failed ({exc}), falling back to synthetic 500x500")
        from core.landing_scorer import _synthetic_terrain
        elevation, slope, roughness, profile = _synthetic_terrain(shape=(500, 500))
        print(f"[runner] Synthetic terrain: {elevation.shape}")

    # ---- Optionally strip ancillary layers (no-ancillary mode) ----------
    if args.strip_ancillary:
        import copy as _copy
        import gc as _gc
        from core.energy_model import estimate_sunlight as _est_sun
        _STRIP = ["psr_mask","illumination_map","earth_visibility","sky_visibility",
                  "diviner_coltemp","m3_oh_band","crater_density"]
        profile = _copy.copy(profile)
        for _k in _STRIP:
            profile[_k] = None
        profile["sunlight_map"] = _est_sun(elevation, profile)
        _gc.collect()
        print("[runner] Ancillary layers stripped — proxy fallback mode active.")

    # ---- Import all tests ------------------------------------------------
    test_modules = []
    test_names_order = [
        ("test_chandrayaan3",        "validation.test_chandrayaan3"),        # loads 65–80°S independently
        ("test_artemis3",            "validation.test_artemis3"),
        ("test_sensitivity",         "validation.test_sensitivity"),
        ("test_dbscan_params",       "validation.test_dbscan_params"),
        ("test_classifier_cv",       "validation.test_classifier_cv"),
        ("test_pathfinder",          "validation.test_pathfinder"),
        ("test_energy_model",        "validation.test_energy_model"),
        ("test_slope_accuracy",      "validation.test_slope_accuracy"),
        ("test_roughness_accuracy",  "validation.test_roughness_accuracy"),
        ("test_pipeline_e2e",        "validation.test_pipeline_e2e"),
        ("test_historical_missions", "validation.test_historical_missions"),
        ("test_ancillary_layers",    "validation.test_ancillary_layers"),    # new: PSR/illumination integrity
        ("test_real_dem_sanity",     "validation.test_real_dem_sanity"),     # new: DEM physical plausibility
        ("test_mobility",            "validation.test_mobility"),             # new: Bekker-Wong terramechanics
        ("test_combinations_fast",   "validation.test_combinations_fast"),   # new: all 8 combos fast/synthetic
    ]

    for short_name, module_path in test_names_order:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            test_modules.append((short_name, mod))
        except Exception as exc:
            print(f"[runner] IMPORT FAILED for {module_path}: {exc}")
            test_modules.append((short_name, None))

    # ---- Run each test ---------------------------------------------------
    all_results: list[dict] = []

    for short_name, mod in test_modules:
        if mod is None:
            r = {
                "test_name": short_name,
                "result": "FAIL",
                "notes": f"Module import failed",
            }
            all_results.append(r)
            continue

        print(f"\n{'='*70}")
        t_start = time.perf_counter()
        try:
            r = mod.run(elevation, slope, roughness, profile,
                        str(RESULTS_DIR), str(PLOTS_DIR))
        except Exception as exc:
            r = {
                "test_name": short_name,
                "result": "FAIL",
                "notes": f"Unhandled exception: {exc}\n{traceback.format_exc()}",
            }
            print(f"  UNHANDLED EXCEPTION in {short_name}: {exc}")
        t_end = time.perf_counter()
        r["_runtime_s"] = round(t_end - t_start, 2)
        all_results.append(r)
        print(f"  [{short_name}] -> {r.get('result','?')} ({r['_runtime_s']}s)")
        # Force GC between tests — Chandrayaan-3 loads a large secondary DEM
        # that must be freed before score_terrain allocates on the full 80S grid.
        import gc as _gc
        _gc.collect()

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    n_pass = sum(1 for r in all_results if r.get("result") == "PASS")
    n_warn = sum(1 for r in all_results if r.get("result") == "WARN")
    n_fail = sum(1 for r in all_results if r.get("result") == "FAIL")
    n_skip = sum(1 for r in all_results if r.get("result") == "SKIP")
    for i, r in enumerate(all_results, start=1):
        v = r.get("result", "?")
        name = r.get("test_name", f"Test {i}")
        print(f"  [{i:2d}] {v:4s}  {name}")
    print(f"\n  TOTAL: {n_pass} PASS · {n_warn} WARN · {n_fail} FAIL · {n_skip} SKIP / {len(all_results)}")

    # ---- Write combined JSON ---------------------------------------------
    combined_path = RESULTS_DIR / "all_results.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n[runner] Combined JSON -> {combined_path}")

    # ---- Generate markdown report ----------------------------------------
    generate_report(all_results)


def report_from_existing() -> None:
    """Read all result JSON files in RESULTS_DIR and regenerate VALIDATION_REPORT.md."""
    json_files = sorted(RESULTS_DIR.glob("*.json"))
    json_files = [f for f in json_files if f.name != "all_results.json"]

    _ORDER = [
        "chandrayaan3_validation", "artemis3_validation", "sensitivity_analysis",
        "dbscan_validation", "classifier_cv", "pathfinder_validation",
        "energy_model_validation", "slope_accuracy", "roughness_accuracy",
        "pipeline_e2e",
        "historical_missions",
        "ancillary_layers", "real_dem_sanity", "mobility_validation",
        "combinations_fast",
    ]

    results_by_stem = {}
    for f in json_files:
        try:
            with open(f, encoding="utf-8") as fp:
                results_by_stem[f.stem] = json.load(fp)
        except Exception as exc:
            print(f"[runner] Could not read {f}: {exc}")

    all_results = []
    for stem in _ORDER:
        if stem in results_by_stem:
            all_results.append(results_by_stem[stem])
        else:
            all_results.append({
                "test_name": stem,
                "result": "FAIL",
                "notes": "Result file not found",
            })

    combined_path = RESULTS_DIR / "all_results.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"[runner] Combined JSON -> {combined_path}")

    generate_report(all_results)

    n_pass = sum(1 for r in all_results if r.get("result") == "PASS")
    n_warn = sum(1 for r in all_results if r.get("result") == "WARN")
    n_fail = sum(1 for r in all_results if r.get("result") == "FAIL")
    n_skip = sum(1 for r in all_results if r.get("result") == "SKIP")
    print(f"[runner] Summary: {n_pass} PASS / {n_warn} WARN / {n_fail} FAIL / {n_skip} SKIP of {len(all_results)}")


if __name__ == "__main__":
    main()

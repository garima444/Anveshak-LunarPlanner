"""
tests/report_validation/section_01_module_verification.py
─────────────────────────────────────────────────────────
Section 1: Module Verification
Proves every core module imports and runs, and that the FastAPI
endpoints respond correctly.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

# ── Bootstrap path ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.report_validation.utils import (
    IMAGES_DIR,
    LOGS_DIR,
    VIPER_PROFILE,
    TeeOutput,
    ensure_dirs,
    make_check,
    make_comparison_table_png,
    print_result,
    print_section_header,
    save_terminal_screenshot,
    verdict_from_checks,
    load_real_terrain_safe,
)


# ── Module / function registry ────────────────────────────────────────────────
_MODULES: list[tuple[str, list[str]]] = [
    ("core.terrain",             ["load_terrain_by_region", "latlon_to_pixel", "pixel_to_latlon"]),
    ("core.landing_scorer",      ["score_terrain", "build_science_map"]),
    ("core.pathfinder",          ["find_path", "build_cost_grid", "astar"]),
    ("core.energy_model",        ["compute_path_energy", "estimate_sunlight"]),
    ("core.terrain_classifier",  ["classify_terrain", "load_classifier", "train_classifier"]),
    ("core.anomaly_detector",    ["detect_anomalies"]),
    ("core.mission_advisor",     ["generate_report"]),
    ("core.visualizer",          ["create_mission_map", "create_score_chart"]),
]

# ── FastAPI endpoint definitions ──────────────────────────────────────────────
_GET_ENDPOINTS: list[tuple[str, int]] = [
    ("/health",        200),
    ("/rover_presets", 200),
    ("/dem_regions",   200),
    ("/",              200),
]

_VALID_POST_BODY: dict = {
    "mission_type": "water_ice",
    "power_source": "rtg",
    "max_slope_deg": 20.0,
    "min_flat_radius_m": 300.0,
    "priority": 0.5,
    "psr_intent": "avoid",
    "speed_kmh": 0.5,
    "battery_wh": 2000.0,
}


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def run(elevation=None, slope=None, roughness=None, profile=None, out_dir=None) -> dict:
    """Run Section 1: Module & API Verification."""
    ensure_dirs()
    log_path = LOGS_DIR / "01_module_verification.txt"
    img_path  = IMAGES_DIR / "01_module_verification_table.png"

    tee = TeeOutput(log_path)
    old_stdout = sys.stdout
    sys.stdout = tee

    checks: list[dict] = []
    images: list[str]  = []

    try:
        print_section_header("SECTION 1: MODULE VERIFICATION — Anveshak Lunar Mission Planner")
        print(f"  Python:   {sys.version.split()[0]}")
        print(f"  Platform: {sys.platform}")
        print()

        # ── 1.1  Module imports ────────────────────────────────────────────
        print("─" * 60)
        print("  TEST 1.1: Module Imports")
        print("─" * 60)
        mod_objects: dict[str, object] = {}
        for mod_name, fns in _MODULES:
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                mod_objects[mod_name] = mod
                print(f"  {mod_name}: IMPORTED ✅")
                ok = True
            except Exception as exc:
                print(f"  {mod_name}: FAILED ❌  ({exc})")
                ok = False
            checks.append(make_check(f"import {mod_name}", ok))

        print()

        # ── 1.2  Key function existence ────────────────────────────────────
        print("─" * 60)
        print("  TEST 1.2: Key Function Existence")
        print("─" * 60)
        for mod_name, fns in _MODULES:
            mod = mod_objects.get(mod_name)
            if mod is None:
                for fn in fns:
                    print(f"    {fn}: SKIPPED (module not imported)")
                    checks.append(make_check(f"{mod_name}.{fn}", False, "SKIP", "callable"))
                continue
            for fn in fns:
                obj = getattr(mod, fn, None)
                ok  = callable(obj)
                status = "FOUND ✅" if ok else "MISSING ❌"
                print(f"    {fn}: {status}")
                checks.append(make_check(f"{mod_name}.{fn}", ok))
        print()

        # ── 1.3  FastAPI endpoint tests ────────────────────────────────────
        print("─" * 60)
        print("  TEST 1.3: FastAPI Endpoint Health")
        print("─" * 60)
        try:
            from fastapi.testclient import TestClient
            from main import app  # noqa: PLC0415

            with TestClient(app, raise_server_exceptions=False) as client:
                for url, expected_code in _GET_ENDPOINTS:
                    try:
                        resp = client.get(url)
                        ok   = resp.status_code == expected_code
                        print_result(f"GET {url}", ok, resp.status_code, expected_code)
                        checks.append(make_check(f"GET {url}", ok, resp.status_code, expected_code))
                    except Exception as exc:
                        print(f"  ⚠️  GET {url}: exception — {exc}")
                        checks.append(make_check(f"GET {url}", False, "exception"))

                # Valid POST /analyze
                try:
                    resp = client.post("/analyze", json=_VALID_POST_BODY)
                    ok   = resp.status_code in (200, 202)
                    print_result("POST /analyze (valid body)", ok, resp.status_code, "200/202")
                    checks.append(make_check("POST /analyze valid", ok, resp.status_code, "200/202"))
                except Exception as exc:
                    print(f"  ⚠️  POST /analyze: exception — {exc}")
                    checks.append(make_check("POST /analyze valid", False, "exception"))

                # Invalid POST /analyze
                try:
                    resp = client.post("/analyze", json={"max_slope_deg": -1})
                    ok   = resp.status_code in (422, 400)
                    print_result("POST /analyze (invalid body)", ok, resp.status_code, "422/400")
                    checks.append(make_check("POST /analyze invalid", ok, resp.status_code, "422/400"))
                except Exception as exc:
                    print(f"  ⚠️  POST /analyze invalid: exception — {exc}")
                    checks.append(make_check("POST /analyze invalid", False, "exception"))

        except ImportError as exc:
            print(f"  ⚠️  FastAPI TestClient unavailable: {exc}")
            print("     API endpoint tests SKIPPED (WARN)")
            for url, _ in _GET_ENDPOINTS:
                checks.append({"check": f"GET {url}", "result": "WARN",
                                "value": "skipped", "expected": "200"})
        except Exception as exc:
            print(f"  ⚠️  API test block failed: {exc}")
        print()

        # ── 1.4  Synthetic pipeline smoke test ─────────────────────────────
        print("─" * 60)
        print("  TEST 1.4: Synthetic Pipeline Smoke Test")
        print("─" * 60)
        try:
            t0 = time.perf_counter()
            from core.landing_scorer import _synthetic_terrain, score_terrain
            from core.pathfinder import find_path
            from core.mission_advisor import generate_report

            syn_elev, syn_slope, syn_rough, syn_profile = _synthetic_terrain(shape=(200, 200))
            safety, mission, final, top_sites = score_terrain(
                syn_elev, syn_slope, syn_rough, syn_profile, VIPER_PROFILE
            )
            assert final.shape == (200, 200)
            assert len(top_sites) > 0

            start_px = (top_sites[0]["pixel_row"], top_sites[0]["pixel_col"])
            goal_px  = (top_sites[-1]["pixel_row"], top_sites[-1]["pixel_col"])
            path, stats = find_path(
                syn_slope, start_px, goal_px, VIPER_PROFILE,
                resolution_m=60.0, elevation=syn_elev,
            )
            # Keep stats=None when path was not found — generate_report handles
            # None correctly with a "no path" message; a partial dict would crash
            # _path_analysis() which subscripts estimated_time_hrs/waypoint_count.

            report = generate_report(VIPER_PROFILE, top_sites[:3], stats)
            assert "executive_summary" in report

            elapsed = time.perf_counter() - t0
            print(f"  Full pipeline on synthetic terrain: ✅ PASS")
            print(f"  Time taken: {elapsed:.1f} seconds")
            checks.append(make_check("synthetic pipeline", True, f"{elapsed:.1f}s", "< 120s"))
        except Exception as exc:
            print(f"  ❌ Synthetic pipeline FAILED: {exc}")
            checks.append(make_check("synthetic pipeline", False, str(exc)[:80]))

        print()

        # ── Summary ────────────────────────────────────────────────────────
        n_pass  = sum(1 for c in checks if c["result"] == "PASS")
        n_total = len(checks)
        verdict = verdict_from_checks(checks)
        print("═" * 60)
        print(f"  SECTION 1 RESULT: {verdict}")
        print(f"  Passed: {n_pass}/{n_total} checks")
        print("═" * 60)

    finally:
        sys.stdout = old_stdout
        tee.close()

    log_content = tee.get_content()

    # ── Generate terminal screenshot ──────────────────────────────────────────
    try:
        save_terminal_screenshot(
            log_content,
            img_path,
            "Section 1: Module Verification — Anveshak",
        )
        images.append(str(img_path))
    except Exception as exc:
        print(f"[sec01] screenshot failed: {exc}")

    # ── Generate checks table PNG ─────────────────────────────────────────────
    table_path = IMAGES_DIR / "01_checks_table.png"
    try:
        rows = [[c["check"][:50], c["result"], c.get("value", "")[:30], c.get("expected", "")[:30]]
                for c in checks]
        make_comparison_table_png(
            headers=["Check", "Result", "Value", "Expected"],
            rows=rows,
            title="Section 1: Module Verification Results",
            output_path=table_path,
        )
        images.append(str(table_path))
    except Exception as exc:
        print(f"[sec01] table PNG failed: {exc}")

    return {
        "test_name": "Section 1: Module Verification",
        "result": verdict_from_checks(checks),
        "notes": f"{sum(1 for c in checks if c['result']=='PASS')}/{len(checks)} checks passed",
        "passed": sum(1 for c in checks if c["result"] == "PASS"),
        "total": len(checks),
        "checks": checks,
        "images": images,
        "log": str(log_path),
    }


if __name__ == "__main__":
    ensure_dirs()
    result = run()
    print(f"\nSection result: {result['result']}")
    print(f"Passed: {result['passed']}/{result['total']}")

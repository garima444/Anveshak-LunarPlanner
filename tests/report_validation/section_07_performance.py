"""
tests/report_validation/section_07_performance.py
──────────────────────────────────────────────────
Section 7: Performance Benchmarks
Measures wall-clock time for each core pipeline stage.

Always uses synthetic terrain for reproducibility.
Generous thresholds to avoid flakiness across hardware.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

from tests.report_validation.utils import (
    IMAGES_DIR,
    LOGS_DIR,
    GEOLOGICAL_RTG_PROFILE,
    VIPER_PROFILE,
    TeeOutput,
    ensure_dirs,
    make_check,
    make_comparison_table_png,
    print_result,
    print_section_header,
    save_terminal_screenshot,
    verdict_from_checks,
)


# ── Benchmark thresholds (generous for low-end hardware) ─────────────────────
_BENCHMARKS = [
    ("_synthetic_terrain(500×500)",        120.0),
    ("score_terrain(300×300)",             120.0),
    ("find_path(300×300, diagonal)",        60.0),
    ("detect_anomalies(300×300)",          180.0),
    ("train_classifier(300×300)",          240.0),
    ("classify_terrain(300×300)",          120.0),
    ("generate_report()",                    5.0),
]


def _benchmark(name: str, fn, *args, **kwargs):
    """Time a function call. Returns (result, elapsed_s)."""
    t0 = time.perf_counter()
    try:
        res = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        return res, elapsed, None
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return None, elapsed, str(exc)


def run(elevation=None, slope=None, roughness=None, profile=None, out_dir=None) -> dict:
    """Run Section 7: Performance Benchmarks."""
    ensure_dirs()
    log_path = LOGS_DIR  / "07_performance_benchmarks.txt"
    img_tbl  = IMAGES_DIR / "07_performance_benchmark_table.png"

    tee = TeeOutput(log_path)
    old_stdout = sys.stdout
    sys.stdout = tee

    checks:    list[dict] = []
    images:    list[str]  = []
    bm_rows:   list[list] = []  # for table PNG

    try:
        print_section_header("SECTION 7: PERFORMANCE BENCHMARKS")
        print(f"  Python:   {sys.version.split()[0]}")
        print(f"  Platform: {sys.platform}")
        print("  Note: All benchmarks use synthetic terrain for reproducibility.")
        print()

        from core.landing_scorer import _synthetic_terrain, score_terrain
        from core.pathfinder import find_path
        from core.anomaly_detector import detect_anomalies
        from core.terrain_classifier import train_classifier, classify_terrain
        from core.mission_advisor import generate_report

        # ── Benchmark 1: synthetic terrain generation ─────────────────────
        print("─" * 60)
        print("  BM1: _synthetic_terrain(500×500)")
        res1, t1, err1 = _benchmark("synthetic_terrain", _synthetic_terrain, shape=(500, 500))
        ok1 = err1 is None and t1 <= 120.0
        print(f"    Time:   {t1:.2f}s  {'✅' if ok1 else '⚠️'}")
        if err1:
            print(f"    Error:  {err1}")
        checks.append(make_check("BM1 _synthetic_terrain", ok1, f"{t1:.2f}s", "< 120s"))
        bm_rows.append(["_synthetic_terrain(500×500)", f"{t1:.2f}s", "< 120s",
                         "✅ PASS" if ok1 else "⚠️ WARN"])

        if res1:
            syn_elev, syn_slope, syn_rough, syn_profile = res1
            # Shrink to 300×300 for most tests
            s300_elev, s300_slope, s300_rough = (
                _synthetic_terrain(shape=(300, 300))[:3]
            )
            s300_elev, s300_slope, s300_rough, s300_profile = _synthetic_terrain(shape=(300, 300))
        else:
            print("  ⚠️  Using fallback 300×300 terrain")
            s300_elev, s300_slope, s300_rough, s300_profile = _synthetic_terrain(shape=(300, 300))

        # ── Benchmark 2: score_terrain ────────────────────────────────────
        print("─" * 60)
        print("  BM2: score_terrain(300×300)")
        res2, t2, err2 = _benchmark("score_terrain", score_terrain,
                                     s300_elev, s300_slope, s300_rough, s300_profile,
                                     GEOLOGICAL_RTG_PROFILE)
        ok2 = err2 is None and t2 <= 120.0
        print(f"    Time:   {t2:.2f}s  {'✅' if ok2 else '⚠️'}")
        if err2:
            print(f"    Error:  {err2}")
        checks.append(make_check("BM2 score_terrain", ok2, f"{t2:.2f}s", "< 120s"))
        bm_rows.append(["score_terrain(300×300)", f"{t2:.2f}s", "< 120s",
                         "✅ PASS" if ok2 else "⚠️ WARN"])

        if res2:
            safety_sc, mission_sc, final_sc, top_sites = res2
        else:
            safety_sc = mission_sc = final_sc = np.zeros((300, 300))
            top_sites = []

        # ── Benchmark 3: find_path ────────────────────────────────────────
        print("─" * 60)
        print("  BM3: find_path(300×300, diagonal)")
        start_px = (10, 10)
        goal_px  = (289, 289)
        rover_fp = {**VIPER_PROFILE, "battery_wh": 2000.0}
        res3, t3, err3 = _benchmark("find_path", find_path,
                                     s300_slope, start_px, goal_px, rover_fp,
                                     60.0, s300_elev)
        ok3 = err3 is None and t3 <= 60.0
        path3 = res3[0] if res3 else None
        path_found = path3 is not None
        print(f"    Time:   {t3:.2f}s  {'✅' if ok3 else '⚠️'}")
        print(f"    Path found: {'✅' if path_found else '❌ (no path)'}")
        if err3:
            print(f"    Error:  {err3}")
        checks.append(make_check("BM3 find_path", ok3, f"{t3:.2f}s", "< 60s"))
        checks.append(make_check("BM3 path exists", path_found))
        bm_rows.append(["find_path(300×300)", f"{t3:.2f}s", "< 60s",
                         "✅ PASS" if ok3 else "⚠️ WARN"])

        # ── Benchmark 4: detect_anomalies ─────────────────────────────────
        print("─" * 60)
        print("  BM4: detect_anomalies(300×300)")
        res4, t4, err4 = _benchmark("detect_anomalies", detect_anomalies,
                                     s300_elev, s300_slope, s300_rough, s300_profile)
        ok4 = err4 is None and t4 <= 180.0
        n_anom = len(res4) if res4 else 0
        print(f"    Time:       {t4:.2f}s  {'✅' if ok4 else '⚠️'}")
        print(f"    Anomalies:  {n_anom} detected")
        if err4:
            print(f"    Error:  {err4}")
        checks.append(make_check("BM4 detect_anomalies", ok4, f"{t4:.2f}s", "< 180s"))
        bm_rows.append(["detect_anomalies(300×300)", f"{t4:.2f}s", "< 180s",
                         "✅ PASS" if ok4 else "⚠️ WARN"])

        # ── Benchmark 5: train_classifier ─────────────────────────────────
        print("─" * 60)
        print("  BM5: train_classifier(300×300)")
        res5, t5, err5 = _benchmark("train_classifier", train_classifier,
                                     s300_elev, s300_slope, s300_rough, s300_profile,
                                     safety_sc, mission_sc)
        ok5 = err5 is None and t5 <= 240.0
        print(f"    Time:   {t5:.2f}s  {'✅' if ok5 else '⚠️'}")
        if err5:
            print(f"    Error:  {err5}")
        clf = res5[0] if res5 else None
        checks.append(make_check("BM5 train_classifier", ok5, f"{t5:.2f}s", "< 240s"))
        bm_rows.append(["train_classifier(300×300)", f"{t5:.2f}s", "< 240s",
                         "✅ PASS" if ok5 else "⚠️ WARN"])

        # ── Benchmark 6: classify_terrain ─────────────────────────────────
        print("─" * 60)
        print("  BM6: classify_terrain(300×300)")
        if clf is not None:
            res6, t6, err6 = _benchmark("classify_terrain", classify_terrain,
                                         clf, s300_elev, s300_slope, s300_rough, s300_profile)
        else:
            res6, t6, err6 = None, 0.0, "classifier not available"
        ok6 = err6 is None and t6 <= 120.0
        print(f"    Time:   {t6:.2f}s  {'✅' if ok6 else '⚠️'}")
        if err6:
            print(f"    Error:  {err6}")
        checks.append(make_check("BM6 classify_terrain", ok6, f"{t6:.2f}s", "< 120s"))
        bm_rows.append(["classify_terrain(300×300)", f"{t6:.2f}s", "< 120s",
                         "✅ PASS" if ok6 else "⚠️ WARN"])

        # ── Benchmark 7: generate_report ──────────────────────────────────
        print("─" * 60)
        print("  BM7: generate_report()")
        # Must include ALL keys that compute_path_stats() returns AND that
        # mission_advisor._path_analysis() accesses directly (not via .get()).
        dummy_stats = {
            "total_distance_m":     5000.0,
            "total_distance_km":    5.0,
            "max_slope_deg":        8.0,
            "mean_slope_deg":       4.0,
            "estimated_time_hrs":   10.0,   # 5 km ÷ 0.5 km/h
            "waypoint_count":       84,
            "battery_pct_used":     42.0,
            "battery_feasible":     True,
        }
        dummy_sites = top_sites[:3] if top_sites else [{"rank": 1, "lat": -89.0, "lon": 0.0,
                                                         "elevation_m": -2000.0, "slope_deg": 4.0,
                                                         "roughness_m": 0.05, "safety_score": 0.9,
                                                         "mission_score": 0.8, "final_score": 0.87,
                                                         "pixel_row": 150, "pixel_col": 150,
                                                         "reasoning": "Test site"}]
        res7, t7, err7 = _benchmark("generate_report", generate_report,
                                     GEOLOGICAL_RTG_PROFILE, dummy_sites, dummy_stats)
        ok7 = err7 is None and t7 <= 5.0
        print(f"    Time:   {t7:.2f}s  {'✅' if ok7 else '⚠️'}")
        if err7:
            print(f"    Error:  {err7}")
        checks.append(make_check("BM7 generate_report", ok7, f"{t7:.2f}s", "< 5s"))
        bm_rows.append(["generate_report()", f"{t7:.2f}s", "< 5s",
                         "✅ PASS" if ok7 else "⚠️ WARN"])

        # ── Summary ────────────────────────────────────────────────────────
        print()
        print("═" * 68)
        print("  PERFORMANCE BENCHMARK SUMMARY")
        print("═" * 68)
        print(f"  {'Operation':<35} {'Time':>8}  {'Threshold':>10}  {'Status':>6}")
        print("  " + "─" * 64)
        for row in bm_rows:
            op, t_s, thr, status = row
            flag = "✅" if "PASS" in status else "⚠️"
            print(f"  {op:<35} {t_s:>8}  {thr:>10}  {flag}")
        print()
        n_pass = sum(1 for c in checks if c["result"] == "PASS")
        print(f"  Benchmarks within threshold: {n_pass}/{len(checks)}")

    finally:
        sys.stdout = old_stdout
        tee.close()

    log_content = tee.get_content()

    # ── Terminal screenshot ───────────────────────────────────────────────────
    try:
        ss_path = IMAGES_DIR / "07_performance_terminal.png"
        save_terminal_screenshot(log_content, ss_path,
                                 "Section 7: Performance Benchmarks — Anveshak")
        images.append(str(ss_path))
    except Exception as exc:
        print(f"[sec07] screenshot failed: {exc}")

    # ── Table image ───────────────────────────────────────────────────────────
    try:
        make_comparison_table_png(
            headers=["Operation", "Time", "Threshold", "Status"],
            rows=bm_rows,
            title=f"Performance Benchmarks — Python {sys.version.split()[0]}",
            output_path=img_tbl,
        )
        images.append(str(img_tbl))
    except Exception as exc:
        print(f"[sec07] table image failed: {exc}")

    return {
        "test_name": "Section 7: Performance Benchmarks",
        "result": verdict_from_checks(checks),
        "notes": (
            f"{sum(1 for c in checks if c['result']=='PASS')}/{len(checks)} "
            "benchmarks within threshold"
        ),
        "passed": sum(1 for c in checks if c["result"] == "PASS"),
        "total": len(checks),
        "checks": checks,
        "benchmark_rows": bm_rows,
        "images": images,
        "log": str(log_path),
    }


if __name__ == "__main__":
    ensure_dirs()
    result = run()
    print(f"\nSection result: {result['result']}")
    print(f"Passed: {result['passed']}/{result['total']}")

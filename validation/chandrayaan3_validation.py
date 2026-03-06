"""
validation/chandrayaan3_validation.py — Chandrayaan-3 landing site validation.

Chandrayaan-3 landed at 69.373°S, 32.319°E on 23 Aug 2023.
This script runs the Anveshak scoring system and checks whether it
independently recommends that region. Result appears as Table 2 in the paper.

Coverage note: LDEM_80S_20M.JP2 covers 80–90°S only. Chandrayaan-3 at 69.373°S
is outside this dataset. The script handles this explicitly and reports it as a
scientifically meaningful finding — our system targets the extreme polar region
where PSR/water-ice probability is highest, while C3 targeted the sub-polar zone
as a technological demonstration.

Run from the project root:
    conda activate lunar-planner
    python validation/chandrayaan3_validation.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so core.* imports resolve
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.terrain import load_terrain, latlon_to_pixel, pixel_to_latlon
from core.landing_scorer import score_terrain
from core.terrain_classifier import load_classifier, classify_terrain, CLASS_NAMES
from core.visualizer import create_mission_map

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHANDRAYAAN3_LAT  = -69.373
CHANDRAYAAN3_LON  =  32.319
CHANDRAYAAN3_NAME = "Chandrayaan-3 Statio Shiv Shakti"
MOON_RADIUS_KM    = 1737.4

# Rover profiles
PROFILE_GEO = {
    "mission_type":      "geological",
    "power_source":      "rtg",
    "max_slope_deg":     20,
    "min_flat_radius_m": 100,
    "priority":          0.6,
}
PROFILE_ICE = {
    "mission_type":      "water_ice",
    "power_source":      "rtg",
    "max_slope_deg":     15,
    "min_flat_radius_m": 120,
    "priority":          0.4,
}

# Artemis III candidate sites (NASA, 2023) — all within 80–90°S coverage
ARTEMIS_SITES = [
    {"name": "Faustini Crater",  "lat": -87.3, "lon":  77.0},
    {"name": "Shackleton Ridge", "lat": -89.5, "lon":   0.0},
    {"name": "Haworth Edge",     "lat": -86.9, "lon":  -5.3},
    {"name": "Nobile Rim",       "lat": -85.2, "lon":  53.5},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_moon(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km on the Moon (R = 1737.4 km)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2.0 * MOON_RADIUS_KM * math.asin(math.sqrt(a))


def find_nearest_top_site(
    top_sites: list[dict],
    c3_lat: float,
    c3_lon: float,
) -> tuple[dict | None, float]:
    """Return (nearest_site_dict, distance_km) from C3 to closest top site."""
    if not top_sites:
        return None, float("inf")
    best_site   = top_sites[0]
    best_dist   = haversine_moon(c3_lat, c3_lon, top_sites[0]["lat"], top_sites[0]["lon"])
    for site in top_sites[1:]:
        d = haversine_moon(c3_lat, c3_lon, site["lat"], site["lon"])
        if d < best_dist:
            best_dist = d
            best_site = site
    return best_site, best_dist


def evaluate_validation(
    final_score_at_c3: float | None,
    nearest_dist_km:   float,
    in_bounds:         bool,
) -> str:
    """Return a validation verdict string for one rover profile."""
    if not in_bounds:
        if nearest_dist_km < 500:
            return "COVERAGE_BOUNDARY_MODERATE"
        return "COVERAGE_BOUNDARY_WEAK"
    if nearest_dist_km < 200 and final_score_at_c3 is not None and final_score_at_c3 > 0.5:
        return "STRONG"
    if nearest_dist_km < 500 and final_score_at_c3 is not None and final_score_at_c3 > 0.3:
        return "MODERATE"
    if final_score_at_c3 is not None and final_score_at_c3 > 0.2:
        return "WEAK"
    return "NOT_VALIDATED"


# ---------------------------------------------------------------------------
# Score extraction at arbitrary coordinates
# ---------------------------------------------------------------------------

def _extract_at_coord(
    lon: float,
    lat: float,
    safety: "np.ndarray",
    mission: "np.ndarray",
    final: "np.ndarray",
    class_map: "np.ndarray | None",
    H: int,
    W: int,
    profile: dict,
) -> tuple[int, int, bool, float | None, float | None, float | None, str]:
    """Convert (lon, lat) → pixel, bounds-check, extract all scores.

    Returns (row, col, in_bounds, safety_val, mission_val, final_val, class_name).
    Values are None and class_name is 'OUT_OF_COVERAGE' when out of bounds.
    """
    import numpy as np  # local import — numpy already loaded by this point
    row, col = latlon_to_pixel(lon, lat, profile)
    in_bounds = (0 <= row < H) and (0 <= col < W)
    if in_bounds:
        s = float(safety[row, col])
        m = float(mission[row, col])
        f = float(final[row, col])
        cls = CLASS_NAMES[int(class_map[row, col])] if class_map is not None else "N/A"
    else:
        s = m = f = None
        cls = "OUT_OF_COVERAGE"
    return row, col, in_bounds, s, m, f, cls


# ---------------------------------------------------------------------------
# Validation report builder
# ---------------------------------------------------------------------------

def _profile_label(rp: dict) -> str:
    return f"{rp['mission_type']}/rtg/slope≤{rp['max_slope_deg']}/priority={rp['priority']}"


def _format_score(val: float | None) -> str:
    return f"{val:.4f}" if val is not None else "OOB"


def run_validation() -> None:
    # ---- Outputs directory (project root / outputs) ------------------------
    out_dir = _PROJECT_ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Load terrain ---------------------------------------------------
    print("Loading terrain …")
    elevation, slope, roughness, profile = load_terrain()
    H, W = elevation.shape

    # ---- 2. Convert C3 coords to pixel and bounds-check --------------------
    c3_row, c3_col = latlon_to_pixel(CHANDRAYAAN3_LON, CHANDRAYAAN3_LAT, profile)
    in_bounds = (0 <= c3_row < H) and (0 <= c3_col < W)

    if in_bounds:
        coverage_note = "C3 pixel is WITHIN dataset coverage (80–90°S)."
    else:
        coverage_note = (
            f"C3 pixel ({c3_row}, {c3_col}) is OUTSIDE dataset coverage "
            f"(80–90°S). Chandrayaan-3 at {CHANDRAYAAN3_LAT}°S is in the "
            f"sub-polar zone, outside the extreme polar DEM."
        )

    # ---- 3. Load classifier -----------------------------------------------
    clf       = load_classifier()
    class_map = None
    if clf is not None:
        print("Classifying terrain …")
        class_map = classify_terrain(clf, elevation, slope, roughness, profile)

    # ---- 4. Run scoring for both profiles ----------------------------------
    print("Scoring — Profile A (geological) …")
    safety_geo, mission_geo, final_geo, top_sites_geo = score_terrain(
        elevation, slope, roughness, profile, PROFILE_GEO
    )

    print("Scoring — Profile B (water_ice) …")
    safety_ice, mission_ice, final_ice, top_sites_ice = score_terrain(
        elevation, slope, roughness, profile, PROFILE_ICE
    )

    # ---- 5. Extract scores at C3 pixel (or report OOB) --------------------
    def _extract_scores(safety, mission, final):
        if in_bounds:
            s = float(safety[c3_row, c3_col])
            m = float(mission[c3_row, c3_col])
            f = float(final[c3_row, c3_col])
            if class_map is not None:
                cls = CLASS_NAMES[int(class_map[c3_row, c3_col])]
            else:
                cls = "N/A (no model)"
            return s, m, f, cls
        else:
            return None, None, None, "OUT_OF_COVERAGE"

    s_geo, m_geo, f_geo, cls_geo = _extract_scores(safety_geo, mission_geo, final_geo)
    s_ice, m_ice, f_ice, cls_ice = _extract_scores(safety_ice, mission_ice, final_ice)

    # ---- 5b. Extract scores at Artemis III candidate sites ----------------
    artemis_results: list[dict] = []
    for site in ARTEMIS_SITES:
        _, _, ib_geo, sg, mg, fg, cg = _extract_at_coord(
            site["lon"], site["lat"],
            safety_geo, mission_geo, final_geo, class_map, H, W, profile,
        )
        _, _, ib_ice, si, mi, fi, ci = _extract_at_coord(
            site["lon"], site["lat"],
            safety_ice, mission_ice, final_ice, class_map, H, W, profile,
        )
        artemis_results.append({
            "name":      site["name"],
            "lat":       site["lat"],
            "lon":       site["lon"],
            "in_bounds": ib_geo,          # same grid — geo/ice share profile
            # Profile A (geological)
            "safety_geo":  sg,
            "mission_geo": mg,
            "final_geo":   fg,
            "class_geo":   cg,
            # Profile B (water_ice)
            "safety_ice":  si,
            "mission_ice": mi,
            "final_ice":   fi,
            "class_ice":   ci,
        })

    # ---- 6. Nearest top-10 site for each profile --------------------------
    nearest_geo, dist_geo = find_nearest_top_site(
        top_sites_geo, CHANDRAYAAN3_LAT, CHANDRAYAAN3_LON
    )
    nearest_ice, dist_ice = find_nearest_top_site(
        top_sites_ice, CHANDRAYAAN3_LAT, CHANDRAYAAN3_LON
    )

    # ---- 7. Validation metrics --------------------------------------------
    verdict_geo = evaluate_validation(f_geo, dist_geo, in_bounds)
    verdict_ice = evaluate_validation(f_ice, dist_ice, in_bounds)
    overall_verdict = verdict_geo if verdict_geo < verdict_ice else verdict_ice
    # Pick the "better" verdict (STRONG > MODERATE > WEAK > ...)
    _ORDER = {
        "STRONG": 5, "MODERATE": 4, "WEAK": 3,
        "COVERAGE_BOUNDARY_MODERATE": 2, "COVERAGE_BOUNDARY_WEAK": 1,
        "NOT_VALIDATED": 0,
    }
    overall_verdict = max([verdict_geo, verdict_ice], key=lambda v: _ORDER.get(v, 0))

    # ---- 8. Format nearest-site lines ------------------------------------
    def _nearest_line(site: dict | None, dist_km: float) -> str:
        if site is None:
            return "  (no sites returned)"
        return (
            f"  Rank {site['rank']} | lat={site['lat']:.3f}°, "
            f"lon={site['lon']:.3f}° | dist={dist_km:.1f} km"
        )

    # ---- 9. Build report text --------------------------------------------
    oob_tag = "" if in_bounds else " (OUT OF COVERAGE)"
    lines: list[str] = [
        "=" * 60,
        "=== CHANDRAYAAN-3 VALIDATION REPORT ===",
        "=" * 60,
        f"Site:     {CHANDRAYAAN3_NAME}",
        f"Actual:   {CHANDRAYAAN3_LAT}°S, {CHANDRAYAAN3_LON}°E",
        f"Dataset:  80–90°S  |  C3 is{oob_tag}",
        "",
        f"--- Profile A: {_profile_label(PROFILE_GEO)} ---",
        f"  Nearest top site: {_nearest_line(nearest_geo, dist_geo)}",
        f"  Score at C3 pixel: safety={_format_score(s_geo)} / "
        f"mission={_format_score(m_geo)} / final={_format_score(f_geo)}",
        f"  Terrain class:     {cls_geo}",
        f"  Validation:        {verdict_geo}",
        "",
        f"--- Profile B: {_profile_label(PROFILE_ICE)} ---",
        f"  Nearest top site: {_nearest_line(nearest_ice, dist_ice)}",
        f"  Score at C3 pixel: safety={_format_score(s_ice)} / "
        f"mission={_format_score(m_ice)} / final={_format_score(f_ice)}",
        f"  Terrain class:     {cls_ice}",
        f"  Validation:        {verdict_ice}",
        "",
        "--- Summary ---",
        f"  Coverage note: {coverage_note}",
        f"  Overall verdict: {overall_verdict}",
        "=" * 60,
    ]

    if not in_bounds:
        lines += [
            "",
            "Science context:",
            "  Our system targets 80–90°S (extreme polar region) where PSR",
            "  and water-ice probability are highest. Chandrayaan-3 targeted",
            "  the sub-polar zone (~70°S) as a technological demonstration —",
            "  a deliberate choice, not the scientifically optimal ice site.",
            "  The distance from C3 to our nearest recommended site quantifies",
            "  the difference between these two mission objectives.",
        ]

    # ---- Artemis III section ---------------------------------------------
    lines += [
        "",
        "=" * 60,
        "=== ARTEMIS III CANDIDATE SITES ===",
        "=" * 60,
        "NASA candidate regions for Artemis III crewed landing (2023).",
        "All sites are within 80–90°S dataset coverage.",
        "",
        f"  {'Site':<20} {'Lat':>7} {'Lon':>7}  "
        f"{'safe_A':>7} {'miss_A':>7} {'fin_A':>7}  "
        f"{'safe_B':>7} {'miss_B':>7} {'fin_B':>7}  {'Class (A)'}",
        "  " + "-" * 94,
    ]
    for r in artemis_results:
        def _fs(v: float | None) -> str:
            return f"{v:.4f}" if v is not None else "  OOB  "
        cov = "" if r["in_bounds"] else " [OOB]"
        lines.append(
            f"  {r['name']:<20} {r['lat']:>7.2f} {r['lon']:>7.2f}  "
            f"{_fs(r['safety_geo']):>7} {_fs(r['mission_geo']):>7} {_fs(r['final_geo']):>7}  "
            f"{_fs(r['safety_ice']):>7} {_fs(r['mission_ice']):>7} {_fs(r['final_ice']):>7}  "
            f"{r['class_geo']}{cov}"
        )
    lines += [
        "",
        "  Columns: safe_A/miss_A/fin_A = Profile A (geological/slope≤20)",
        "           safe_B/miss_B/fin_B = Profile B (water_ice/slope≤15)",
        "=" * 60,
    ]

    report_text = "\n".join(lines)

    # ---- 10. Print to console --------------------------------------------
    print("\n" + report_text)

    # ---- 11. Save text report --------------------------------------------
    txt_path = out_dir / "chandrayaan3_validation.txt"
    txt_path.write_text(report_text, encoding="utf-8")
    print(f"\nText report saved → {txt_path}")

    # ---- 12. Build HTML validation map -----------------------------------
    print("Building validation HTML map …")

    # Base map from visualizer (Profile A — geological matches C3 context)
    map_html = create_mission_map(
        elevation, slope, final_geo, top_sites_geo, None, None, profile
    )

    # Build validation info table for HTML
    def _html_score(val: float | None) -> str:
        return f"{val:.4f}" if val is not None else "<em>OOB</em>"

    def _nearest_html(site: dict | None, dist_km: float) -> str:
        if site is None:
            return "<em>none</em>"
        return (
            f"Rank {site['rank']} | {site['lat']:.3f}°, {site['lon']:.3f}° "
            f"| <strong>{dist_km:.1f} km</strong>"
        )

    validation_table_html = f"""
<div id="validation-table" style="
    font-family: monospace;
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 20px;
    margin: 20px 0;
    border-radius: 8px;
    max-width: 900px;
">
  <h3 style="color:#ffd700; margin-top:0;">Chandrayaan-3 Validation</h3>
  <p>
    <strong>Site:</strong> {CHANDRAYAAN3_NAME}<br>
    <strong>Coords:</strong> {CHANDRAYAAN3_LAT}°S, {CHANDRAYAAN3_LON}°E<br>
    <strong>Dataset coverage:</strong> 80–90°S &nbsp;
    <span style="color:{'#ff6b6b' if not in_bounds else '#69db7c'}">
      {'C3 is OUT OF COVERAGE' if not in_bounds else 'C3 is IN COVERAGE'}
    </span>
  </p>
  <table style="border-collapse:collapse; width:100%;">
    <thead>
      <tr style="background:#16213e; color:#a9b1d6;">
        <th style="padding:8px; text-align:left; border-bottom:1px solid #333;">Profile</th>
        <th style="padding:8px; text-align:left; border-bottom:1px solid #333;">Nearest site</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Safety</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Mission</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Final</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Class</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Verdict</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:8px; border-bottom:1px solid #222;">A: {PROFILE_GEO['mission_type']}/slope≤{PROFILE_GEO['max_slope_deg']}</td>
        <td style="padding:8px; border-bottom:1px solid #222; font-size:0.9em;">{_nearest_html(nearest_geo, dist_geo)}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_html_score(s_geo)}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_html_score(m_geo)}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_html_score(f_geo)}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222; font-size:0.85em;">{cls_geo}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222; color:#ffd700;"><strong>{verdict_geo}</strong></td>
      </tr>
      <tr>
        <td style="padding:8px;">B: {PROFILE_ICE['mission_type']}/slope≤{PROFILE_ICE['max_slope_deg']}</td>
        <td style="padding:8px; font-size:0.9em;">{_nearest_html(nearest_ice, dist_ice)}</td>
        <td style="padding:8px; text-align:center;">{_html_score(s_ice)}</td>
        <td style="padding:8px; text-align:center;">{_html_score(m_ice)}</td>
        <td style="padding:8px; text-align:center;">{_html_score(f_ice)}</td>
        <td style="padding:8px; text-align:center; font-size:0.85em;">{cls_ice}</td>
        <td style="padding:8px; text-align:center; color:#ffd700;"><strong>{verdict_ice}</strong></td>
      </tr>
    </tbody>
  </table>
  <p style="margin-top:12px; font-size:0.9em; color:#a9b1d6;">
    <strong>Overall verdict:</strong>
    <span style="color:#ffd700; font-size:1.1em;">{overall_verdict}</span>
  </p>
  <p style="font-size:0.85em; color:#888;">
    {coverage_note}
  </p>
</div>
"""

    # Build Artemis III HTML table
    def _hs(v: float | None) -> str:
        if v is None:
            return "<em style='color:#888'>OOB</em>"
        # Colour-code by final score: green ≥0.4, amber ≥0.25, red below
        color = "#69db7c" if v >= 0.4 else ("#ffd43b" if v >= 0.25 else "#ff6b6b")
        return f"<span style='color:{color}'>{v:.4f}</span>"

    artemis_rows_html = ""
    for r in artemis_results:
        oob_badge = "" if r["in_bounds"] else " <sup style='color:#ff6b6b'>OOB</sup>"
        artemis_rows_html += f"""
      <tr>
        <td style="padding:8px; border-bottom:1px solid #222; font-weight:bold;">{r['name']}{oob_badge}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{r['lat']:.2f}°</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{r['lon']:.2f}°</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['safety_geo'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['mission_geo'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['final_geo'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['safety_ice'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['mission_ice'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222;">{_hs(r['final_ice'])}</td>
        <td style="padding:8px; text-align:center; border-bottom:1px solid #222; font-size:0.82em; color:#a9b1d6;">{r['class_geo']}</td>
      </tr>"""

    artemis_table_html = f"""
<div id="artemis-table" style="
    font-family: monospace;
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 20px;
    margin: 20px 0;
    border-radius: 8px;
    max-width: 1000px;
">
  <h3 style="color:#ffd700; margin-top:0;">Artemis III Candidate Sites — Score Extraction</h3>
  <p style="font-size:0.9em; color:#a9b1d6; margin-bottom:12px;">
    NASA candidate regions for Artemis III crewed landing (2023). All within 80–90°S dataset coverage.<br>
    <strong>A</strong> = geological/rtg/slope≤20/priority=0.6 &nbsp;|&nbsp;
    <strong>B</strong> = water_ice/rtg/slope≤15/priority=0.4
  </p>
  <table style="border-collapse:collapse; width:100%;">
    <thead>
      <tr style="background:#16213e; color:#a9b1d6;">
        <th style="padding:8px; text-align:left; border-bottom:1px solid #333;">Site</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Lat</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Lon</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Safe (A)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Miss (A)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Final (A)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Safe (B)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Miss (B)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Final (B)</th>
        <th style="padding:8px; text-align:center; border-bottom:1px solid #333;">Class</th>
      </tr>
    </thead>
    <tbody>{artemis_rows_html}
    </tbody>
  </table>
  <p style="font-size:0.8em; color:#666; margin-top:10px;">
    Score colours: <span style='color:#69db7c'>green ≥0.40</span> &nbsp;
    <span style='color:#ffd43b'>amber ≥0.25</span> &nbsp;
    <span style='color:#ff6b6b'>red &lt;0.25</span>
  </p>
</div>
"""

    # Wrap into full HTML page
    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Chandrayaan-3 Validation — Anveshak</title>
  <style>
    body {{
      margin: 0;
      padding: 20px;
      background: #0d0d1a;
      color: #e0e0e0;
      font-family: sans-serif;
    }}
    h2 {{
      color: #ffd700;
      margin-bottom: 4px;
    }}
    .subtitle {{
      color: #888;
      font-size: 0.9em;
      margin-bottom: 20px;
    }}
  </style>
</head>
<body>
  <h2>Chandrayaan-3 Validation — Anveshak Lunar Mission Planner</h2>
  <p class="subtitle">
    Dataset: LOLA LDEM_80S_20M.JP2 | Coverage: 80–90°S |
    C3 actual: {CHANDRAYAAN3_LAT}°S, {CHANDRAYAAN3_LON}°E
  </p>
  {validation_table_html}
  {artemis_table_html}
  <h3 style="color:#a9b1d6; margin-top:24px;">Mission Map (Profile A — Geological)</h3>
  {map_html}
</body>
</html>
"""

    html_path = out_dir / "chandrayaan3_validation.html"
    html_path.write_text(html_page, encoding="utf-8")
    print(f"HTML report saved  → {html_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_validation()

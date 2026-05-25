"""
core/mission_advisor.py — Rule-based mission report generation.

Generates a structured plain-English mission report from analysis results
(rover profile, top landing sites, path statistics, optional class map).
No AI API calls — pure rule-based text generation.

Public API:
    generate_report(rover_profile, top_sites, path_stats, class_map=None) -> dict

Example::

    report = generate_report(rover_dict, top_sites, path_stats)
    # report["feasibility_status"]  -> "NOMINAL"
    # report["executive_summary"]   -> "Anveshak-1 mission analysis..."
"""

from __future__ import annotations

import numpy as np

# Mirror of terrain_classifier.CLASS_NAMES — avoids importing the heavy
# terrain_classifier module (which pulls in pyproj/rasterio at import time).
CLASS_NAMES = {
    0: "HAZARD_ZONE",
    1: "RISKY_LANDING",
    2: "TRAVERSE_CORRIDOR",
    3: "SAFE_LANDING",
    4: "SCIENCE_TARGET",
}


# ---------------------------------------------------------------------------
# Terrain descriptor helpers
# ---------------------------------------------------------------------------

def _describe_slope(deg: float) -> str:
    if deg < 5:
        return "flat"
    if deg < 15:
        return "gentle"
    if deg < 25:
        return "moderate"
    return "steep"


def _describe_roughness(m: float) -> str:
    if m < 5:
        return "smooth"
    if m < 20:
        return "moderate"
    if m < 50:
        return "rough"
    return "extremely rough"


def _describe_elevation(m: float) -> str:
    if m < -5000:
        return f"deep polar basin at {m:.0f} m"
    if m < -2000:
        return f"low basin floor at {m:.0f} m"
    if m < 0:
        return f"below-datum depression at {m:.0f} m"
    if m < 2000:
        return f"near-datum plateau at {m:.0f} m"
    if m < 5000:
        return f"elevated highland at {m:.0f} m"
    return f"prominent ridge summit at {m:.0f} m"


def _site_class_name(site: dict, class_map: np.ndarray) -> str:
    row = int(site["pixel_row"])
    col = int(site["pixel_col"])
    if 0 <= row < class_map.shape[0] and 0 <= col < class_map.shape[1]:
        cls_id = int(class_map[row, col])
        return CLASS_NAMES.get(cls_id, "")
    return ""


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _executive_summary(rover_profile: dict, top_sites: list[dict]) -> str:
    name = rover_profile.get("rover_name", "Rover")
    n = len(top_sites)
    mission = rover_profile.get("mission_type", "unknown").replace("_", " ")
    site = top_sites[0]
    abs_lat = abs(site["lat"])
    lon = site["lon"]
    safety = site["safety_score"]
    mission_score = site["mission_score"]

    if safety > 0.6:
        suitability = "suitable"
    elif safety >= 0.3:
        suitability = "presenting moderate risk"
    else:
        suitability = "high-risk"

    return (
        f"{name} {mission} mission analysis identified {n} candidate landing sites "
        f"across the lunar south pole region. The primary landing site at "
        f"{abs_lat:.2f}°S, {lon:.2f}°E is {suitability}, with safety score "
        f"{safety:.2f} and mission score {mission_score:.2f}. This report provides "
        f"terrain characterisation, traverse planning, risk assessment, and operational "
        f"recommendations for the {mission} mission profile."
    )


def _landing_site_analysis(top_sites: list[dict], class_map: np.ndarray | None) -> str:
    site = top_sites[0]
    abs_lat = abs(site["lat"])
    lon = site["lon"]
    elev = site["elevation_m"]
    slope = site["slope_deg"]
    roughness = site["roughness_m"]

    slope_desc = _describe_slope(slope)
    rough_desc = _describe_roughness(roughness)
    elev_desc = _describe_elevation(elev)

    lines = [
        f"PRIMARY SITE (Rank 1): {abs_lat:.2f}°S, {lon:.2f}°E",
        f"  Terrain: {elev_desc}. Slope {slope:.1f}° ({slope_desc}), "
        f"roughness {roughness:.1f} m ({rough_desc}).",
    ]

    if class_map is not None:
        cls_name = _site_class_name(site, class_map)
        if cls_name:
            lines.append(f"  Terrain class: {cls_name}.")

    if len(top_sites) >= 2:
        s2 = top_sites[1]
        delta_safety = site["safety_score"] - s2["safety_score"]
        delta_mission = site["mission_score"] - s2["mission_score"]
        lines.append(
            f"\nCOMPARISON (Rank 1 vs Rank 2): Rank 1 leads by "
            f"{delta_safety:+.2f} safety score and {delta_mission:+.2f} mission score. "
            f"Rank 2 site at {abs(s2['lat']):.2f}°S, {s2['lon']:.2f}°E has slope "
            f"{s2['slope_deg']:.1f}° vs {slope:.1f}° and roughness "
            f"{s2['roughness_m']:.1f} m vs {roughness:.1f} m."
        )

    if len(top_sites) >= 3:
        s3 = top_sites[2]
        lines.append(
            f"Rank 3 site at {abs(s3['lat']):.2f}°S, {s3['lon']:.2f}°E: "
            f"final score {s3['final_score']:.2f}, slope {s3['slope_deg']:.1f}°, "
            f"roughness {s3['roughness_m']:.1f} m."
        )

    return "\n".join(lines)


def _path_analysis(path_stats: dict | None, rover_profile: dict) -> str:
    if path_stats is None:
        return (
            "No viable traverse path was identified between the primary landing site "
            "and the nearest science waypoint. This may indicate terrain impassability "
            "or insufficient flat corridor between sites. Manual route replanning or "
            "site reselection is recommended."
        )

    dist_km = path_stats["total_distance_km"]
    time_hrs = path_stats["estimated_time_hrs"]
    waypoints = path_stats["waypoint_count"]
    max_slope = path_stats["max_slope_deg"]
    mean_slope = path_stats["mean_slope_deg"]
    speed = rover_profile.get("speed_kmh", 0.5)

    lines = [
        f"Planned traverse: {dist_km:.2f} km across {waypoints} waypoints.",
        f"Estimated duration: {time_hrs:.1f} hrs at nominal {speed} km/h.",
        f"Slope profile — mean: {mean_slope:.1f}°, peak: {max_slope:.1f}°.",
    ]

    if max_slope > 15:
        lines.append(
            f"WARNING: Steepest section reaches {max_slope:.1f}°. "
            f"Reduced traverse speed and increased wheel slip risk at this segment."
        )

    # Soft terrain bearing assessment (PSR + data quality + slope error proxy).
    # Source: Heiken et al. 1991, Lunar Sourcebook.
    if path_stats.get("soft_terrain_warning"):
        pct = path_stats.get("soft_terrain_pct", 0.0)
        lines.append(
            f"TERRAIN CAUTION: {pct:.0f}% of traverse path crosses terrain with "
            f"elevated soft soil risk indicators (PSR-adjacent terrain, low DEM "
            f"confidence, uncertain slope). Wheel sinkage assessment requires "
            f"ground-truth soil data. Mission planners should review flagged path "
            f"segments before final approval. "
            f"Source: Heiken et al. 1991, Lunar Sourcebook."
        )
    else:
        lines.append(
            "Terrain bearing capacity: LOW RISK along planned traverse corridor."
        )

    return " ".join(lines)


def _risk_assessment(
    top_sites: list[dict],
    path_stats: dict | None,
    rover_profile: dict,
) -> str:
    site = top_sites[0]
    slope = site["slope_deg"]
    roughness = site["roughness_m"]
    elev = site["elevation_m"]
    power_source = rover_profile.get("power_source", "rtg")
    max_slope_cap = rover_profile.get("max_slope_deg", 15.0)

    # ---- 1. Terrain risk ----
    if slope < 10 and roughness < 10:
        terrain_risk = "LOW"
        terrain_note = f"slope {slope:.1f}° and roughness {roughness:.1f} m within safe thresholds"
    elif slope > 20 or roughness > 30:
        terrain_risk = "HIGH"
        terrain_note = f"slope {slope:.1f}° or roughness {roughness:.1f} m exceeds operational limits"
    else:
        terrain_risk = "MODERATE"
        terrain_note = f"slope {slope:.1f}° and roughness {roughness:.1f} m require careful navigation"

    # ---- 2. Power risk ----
    if power_source == "solar":
        if elev < -3000:
            power_risk = "HIGH"
            power_note = f"elevation {elev:.0f} m likely within permanently shadowed basin — solar generation severely limited"
        elif elev < -1000:
            power_risk = "MODERATE"
            power_note = f"elevation {elev:.0f} m may experience extended shadow periods"
        else:
            power_risk = "LOW"
            power_note = f"elevation {elev:.0f} m expected adequate solar illumination"

        # Override with physics-based sunlight fraction when available
        sunlight_frac = site.get("sunlight_fraction")
        if sunlight_frac is not None:
            if sunlight_frac < 0.2:
                power_risk = "HIGH"
                power_note = (
                    f"sunlight fraction {sunlight_frac:.2f} — site is in or near "
                    f"permanently shadowed region (PSR); solar generation critically limited"
                )
            elif sunlight_frac < 0.5:
                power_risk = "MODERATE"
                power_note = (
                    f"sunlight fraction {sunlight_frac:.2f} — partial shadowing expected; "
                    f"solar panels will experience reduced output"
                )
            else:
                power_risk = "LOW"
                power_note = (
                    f"sunlight fraction {sunlight_frac:.2f} — adequate solar illumination expected"
                )
    else:
        power_risk = "LOW"
        power_note = "RTG power source provides continuous generation independent of illumination"

    # ---- 3. Navigation risk ----
    if path_stats is None:
        nav_risk = "HIGH"
        nav_note = "no viable path found — terrain passability unconfirmed"
    else:
        path_max = path_stats["max_slope_deg"]
        if path_max < max_slope_cap * 0.5:
            nav_risk = "LOW"
            nav_note = f"path max slope {path_max:.1f}° well within rover {max_slope_cap}° capability"
        elif path_max < max_slope_cap * 0.8:
            nav_risk = "MODERATE"
            nav_note = f"path max slope {path_max:.1f}° approaching rover {max_slope_cap}° limit"
        else:
            nav_risk = "HIGH"
            nav_note = f"path max slope {path_max:.1f}° near or exceeding rover {max_slope_cap}° limit"

    return (
        f"1. TERRAIN RISK — {terrain_risk}: {terrain_note}.\n"
        f"2. POWER RISK — {power_risk}: {power_note}.\n"
        f"3. NAVIGATION RISK — {nav_risk}: {nav_note}."
    )


def _science_objectives(
    rover_profile: dict,
    top_sites: list[dict],
    path_stats: dict | None,
    anomalies: list[dict] | None = None,
) -> list[str]:
    site = top_sites[0]
    abs_lat = abs(site["lat"])
    lon = site["lon"]
    elev = site["elevation_m"]
    mission_type = rover_profile.get("mission_type", "water_ice")
    distance = path_stats["total_distance_km"] if path_stats else "unknown"

    if mission_type == "water_ice":
        dist_str = f"{distance:.1f}" if isinstance(distance, float) else distance
        objectives = [
            f"Subsurface ice detection using neutron spectrometry at {abs_lat:.2f}°S "
            f"{lon:.2f}°E permanently shadowed region",
            f"Volatile mapping across {dist_str} km traverse corridor",
            f"Regolith sampling at crater floor elevation {elev:.0f} m",
        ]
    elif mission_type == "geological":
        dist_str = f"{distance:.1f}" if isinstance(distance, float) else distance
        objectives = [
            f"Stratigraphic analysis of elevation transition zone at {abs_lat:.2f}°S "
            f"{lon:.2f}°E",
            f"Impact melt sampling at roughness anomaly sites along traverse",
            f"Mineralogical survey across {dist_str} km traverse",
        ]
    else:  # atmospheric
        dist_str = f"{distance:.1f}" if isinstance(distance, float) else distance
        objectives = [
            f"Solar wind interaction measurement at ridge elevation {elev:.0f} m "
            f"near {abs_lat:.2f}°S",
            f"Exospheric composition sampling across illuminated {dist_str} km traverse",
            f"Dust particle flux measurement at exposed high-altitude landing site",
        ]

    # ---- Anomaly-specific objectives (up to 2) ----
    if anomalies:
        relevant = sorted(
            [a for a in anomalies if mission_type in a.get("recommended_for", [])],
            key=lambda a: a["anomaly_strength"],
            reverse=True,
        )
        _atype_label = {
            "THERMAL_PROXY":     "thermal proxy",
            "ELEVATION_ANOMALY": "elevation anomaly",
            "ROUGHNESS_ANOMALY": "roughness anomaly",
            "SLOPE_TRANSITION":  "slope transition",
        }
        for a in relevant[:2]:
            atype_str = _atype_label.get(a["anomaly_type"], a["anomaly_type"].lower())
            abs_a_lat = abs(a["lat"])
            a_lon     = a["lon"]
            strength  = a["anomaly_strength"]
            px        = a["pixel_count"]
            objectives.append(
                f"Investigate {atype_str} cluster at "
                f"{abs_a_lat:.2f}°S {a_lon:.2f}°E "
                f"(strength {strength:.2f}, {px} pixels)"
            )

    return objectives


def _mission_feasibility(
    top_sites: list[dict],
    path_stats: dict | None,
    rover_profile: dict,
) -> tuple[str, list[str]]:
    site = top_sites[0]
    safety = site["safety_score"]
    max_slope_cap = rover_profile.get("max_slope_deg", 15.0)

    reasons: list[str] = []

    # HIGH_RISK conditions
    if safety < 0.3:
        reasons.append(f"primary site safety score {safety:.2f} below minimum threshold of 0.30")
        return "HIGH_RISK", reasons
    if path_stats is None:
        reasons.append("no viable traverse path identified between landing site and science targets")
        return "HIGH_RISK", reasons

    # MARGINAL conditions
    path_max = path_stats["max_slope_deg"]
    marginal = False

    if 0.3 <= safety <= 0.6:
        reasons.append(f"safety score {safety:.2f} in marginal range (0.30–0.60)")
        marginal = True
    if path_max >= max_slope_cap * 0.8:
        reasons.append(
            f"path max slope {path_max:.1f}° exceeds 80% of rover capability ({max_slope_cap}°)"
        )
        marginal = True

    if marginal:
        return "MARGINAL", reasons

    # NOMINAL
    reasons.append(
        f"safety score {safety:.2f} above threshold; path max slope {path_max:.1f}° "
        f"within rover {max_slope_cap}° capability"
    )
    return "NOMINAL", reasons


def _recommendations(
    top_sites: list[dict],
    path_stats: dict | None,
    rover_profile: dict,
    feasibility: str,
) -> list[str]:
    site = top_sites[0]
    abs_lat = abs(site["lat"])
    lon = site["lon"]
    mission_type = rover_profile.get("mission_type", "water_ice")
    speed = rover_profile.get("speed_kmh", 0.5)

    if feasibility == "NOMINAL":
        recs = [
            f"Proceed with {abs_lat:.2f}°S, {lon:.2f}°E as primary landing target.",
        ]
        if mission_type == "water_ice":
            recs.append("Deploy neutron spectrometer immediately post-landing for subsurface volatile survey.")
        elif mission_type == "geological":
            recs.append("Begin camera and spectrometer survey of immediate landing zone before traverse.")
        else:
            recs.append("Initialise atmospheric sensors and commence baseline measurements post-landing.")

        if path_stats:
            dist = path_stats["total_distance_km"]
            time = path_stats["estimated_time_hrs"]
            recs.append(
                f"Execute {dist:.1f} km traverse at {speed} km/h over estimated {time:.1f} hrs "
                f"to primary science target."
            )
        return recs

    if feasibility == "MARGINAL":
        recs = [
            "Consider additional orbital reconnaissance before committing to primary site.",
        ]
        # Identify the highest risk factor
        site_safety = site["safety_score"]
        if path_stats and path_stats["max_slope_deg"] >= rover_profile.get("max_slope_deg", 15.0) * 0.8:
            recs.append(
                f"Traverse slope risk is elevated — path peak {path_stats['max_slope_deg']:.1f}° "
                f"approaches rover limit. Consider alternative routing."
            )
        else:
            recs.append(
                f"Landing site safety score {site_safety:.2f} is marginal. "
                f"Verify terrain clearance with higher-resolution imagery."
            )
        if len(top_sites) >= 2:
            s2 = top_sites[1]
            recs.append(
                f"Maintain {abs(s2['lat']):.2f}°S, {s2['lon']:.2f}°E (Rank 2) "
                f"as contingency landing site."
            )
        else:
            recs.append("Identify contingency landing site from extended search area.")
        return recs

    # HIGH_RISK
    return [
        "Mission replanning recommended — primary site does not meet safety thresholds.",
        "Evaluate expanded search area or alternative power/mobility configurations.",
        "Consult terrain data for alternative approach corridor.",
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    rover_profile: dict,
    top_sites: list[dict],
    path_stats: dict | None,
    class_map: np.ndarray | None = None,
    anomalies: list[dict] | None = None,
) -> dict:
    """Generate a structured plain-English mission report.

    Parameters
    ----------
    rover_profile : dict
        Rover configuration (rover_name, mission_type, power_source,
        max_slope_deg, min_flat_radius_m, speed_kmh, priority).
    top_sites : list[dict]
        Ranked landing sites from score_terrain(), each with keys:
        rank, pixel_row, pixel_col, lon, lat, elevation_m, slope_deg,
        roughness_m, safety_score, mission_score, final_score, reasoning.
    path_stats : dict | None
        Path statistics from find_path(), or None if no path was found.
    class_map : np.ndarray | None
        Optional uint8 (H, W) terrain class array from classify_terrain().

    Returns
    -------
    dict with keys:
        executive_summary, landing_site_analysis, path_analysis,
        risk_assessment, science_objectives, feasibility_status,
        feasibility_reasons, recommendations
    """
    if not top_sites:
        print("[advisor] No landing sites provided — returning error report.")
        return {
            "executive_summary": "No viable landing sites were identified in the analysis area.",
            "landing_site_analysis": "Insufficient site data.",
            "path_analysis": "No path analysis available.",
            "risk_assessment": "Unable to assess risk without site data.",
            "science_objectives": [],
            "feasibility_status": "HIGH_RISK",
            "feasibility_reasons": ["no landing sites identified"],
            "recommendations": [
                "Mission replanning recommended — no viable sites found.",
                "Evaluate expanded search area or relaxed rover constraints.",
                "Consult terrain data for alternative approach corridor.",
            ],
        }

    print(f"[advisor] Generating report for {rover_profile.get('rover_name', 'rover')} "
          f"({rover_profile.get('mission_type', 'unknown')} mission, "
          f"{len(top_sites)} sites, path={'yes' if path_stats else 'none'}).")

    feasibility_status, feasibility_reasons = _mission_feasibility(
        top_sites, path_stats, rover_profile
    )

    return {
        "executive_summary": _executive_summary(rover_profile, top_sites),
        "landing_site_analysis": _landing_site_analysis(top_sites, class_map),
        "path_analysis": _path_analysis(path_stats, rover_profile),
        "risk_assessment": _risk_assessment(top_sites, path_stats, rover_profile),
        "science_objectives": _science_objectives(rover_profile, top_sites, path_stats, anomalies),
        "feasibility_status": feasibility_status,
        "feasibility_reasons": feasibility_reasons,
        "recommendations": _recommendations(
            top_sites, path_stats, rover_profile, feasibility_status
        ),
    }

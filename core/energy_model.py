"""
core/energy_model.py — Physics-based energy consumption and solar illumination model.

Public API
----------
compute_path_energy(path, slope_array, rover_profile, resolution_m, elevation) -> dict
estimate_sunlight(elevation, profile, power_source=None) -> np.ndarray
compute_sun_elevation_deg(mission_day) -> float
compute_day_illumination(sunlight_map, mission_day) -> np.ndarray
find_recharge_stops(path, slope_array, sunlight_map, rover_profile,
                    resolution_m, elevation, mission_day, profile) -> list[dict]
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import zoom

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATTERY_WH_DEFAULT     = 1000.0
BASE_POWER_W           = 100.0
REGEN_FRACTION         = 0.3
SLOPE_MOTOR_FACTOR     = 3.0
ENERGY_RISK_MODERATE   = 40.0    # battery % threshold
ENERGY_RISK_HIGH       = 75.0
SUNLIGHT_POLAR_FLOOR   = 0.05    # lat < -89°
SUNLIGHT_HIGH_LAT      = 0.7     # lat > -85°
SUNLIGHT_RIDGE_BONUS   = 0.2     # elev > local_mean + 500 m
SUNLIGHT_BASIN_PENALTY = 0.3     # elev < local_mean - 1000 m
DOWNSAMPLE_STEP        = 100     # pixel stride for lat grid

_SQRT2 = math.sqrt(2.0)

# ---------------------------------------------------------------------------
# Solar recharging constants
# ---------------------------------------------------------------------------

# Solar irradiance at 1 AU; panel output scales proportionally with illumination.
# Source: Kopp, G. & Lean, J.L. (2011). GRL 38, L01706. doi:10.1029/2010GL045777.
#         Also confirmed in NASA TRS-2020-220228.
SOLAR_CONSTANT_W_M2 = 1361.0

# Duration of one complete lunar synodic cycle (new moon to new moon).
# Source: Seidelmann, P.K. (ed., 1992). Explanatory Supplement to the
#         Astronomical Almanac. University Science Books, p. 699. IAU standard.
LUNAR_SYNODIC_PERIOD_DAYS = 29.530589

# Moon's obliquity to the ecliptic — amplitude of the south-pole Sun-elevation
# oscillation over one synodic month.
# Source: Seidelmann, P.K. et al. (2007). Celest. Mech. Dyn. Astr. 98(3), 155–180.
#         doi:10.1007/s10569-007-9072-y
MOON_OBLIQUITY_DEG = 1.5424

# Battery state-of-charge at which the rover halts and waits to recharge.
# Source: NASA/TM-2022-217504 "VIPER Operational Concept Document" §4.3 p. 22.
BATTERY_STOP_THRESHOLD_PCT = 20.0

# Battery state-of-charge target before the rover resumes traverse.
# Source: ESA ECSS-E-ST-20-08C §5.4.2 (Li-ion cycle preservation standard).
BATTERY_RESUME_THRESHOLD_PCT = 80.0

# Rover idle power draw while stationary (thermal, avionics, comms; not propulsion).
# Source: ISRO Chandrayaan-3 Mission Report 2023; Pragyan idle ~30 W.
#         25 W is a conservative floor below the cited Pragyan figure.
IDLE_POWER_W = 25.0


# ---------------------------------------------------------------------------
# compute_path_energy
# ---------------------------------------------------------------------------

def compute_path_energy(
    path: list[tuple[int, int]] | None,
    slope_array: np.ndarray,
    rover_profile: dict,
    resolution_m: float = 60.0,
    elevation: np.ndarray | None = None,
    mobility_risk_map: np.ndarray | None = None,
) -> dict:
    """Compute energy consumption statistics for a traversed path.

    Parameters
    ----------
    path : list of (row, col) tuples, or None
    slope_array : 2-D float32 array of slope in degrees
    rover_profile : dict with optional keys ``battery_wh``, ``speed_kmh``
    resolution_m : ground sampling distance in metres per pixel
    elevation : optional 2-D float32 elevation array (enables downhill regen)
    mobility_risk_map : optional float32 [0,1] sinkage risk array from
        core.mobility.compute_trafficability_map().  When provided, a
        terrain-dependent rolling resistance cost is added to each step.
        Baseline μr = 0.015 for nominal compacted regolith (Carrier et al.
        1991; Wong 2008 Table 2.3); scales up to 4× on worst-case soft terrain
        (consistent with Iagnemma & Dubowsky 2004 planetary rover estimates).

    Returns
    -------
    dict with keys:
        total_energy_wh, uphill_energy_wh, downhill_regen_wh,
        energy_per_km, battery_pct_used, energy_risk
    """
    _zero = {
        "total_energy_wh":    0.0,
        "uphill_energy_wh":   0.0,
        "downhill_regen_wh":  0.0,
        "energy_per_km":      0.0,
        "battery_pct_used":   0.0,
        "energy_risk":        "LOW",
    }

    if not path or len(path) < 2:
        return _zero

    speed_kmh = float(rover_profile.get("speed_kmh", 0.5)) or 0.5
    speed_m_s = speed_kmh * 1000.0 / 3600.0

    battery_wh = float(rover_profile.get("battery_wh", BATTERY_WH_DEFAULT))
    if battery_wh <= 0:
        battery_wh = BATTERY_WH_DEFAULT

    h, w = slope_array.shape

    total_energy_wh   = 0.0
    uphill_energy_wh  = 0.0
    downhill_regen_wh = 0.0
    total_dist_m      = 0.0

    for i in range(len(path) - 1):
        r0, c0 = path[i]
        r1, c1 = path[i + 1]

        # Step distance (cardinal vs diagonal)
        dr = abs(r1 - r0)
        dc = abs(c1 - c0)
        step_m = resolution_m * (_SQRT2 if (dr == 1 and dc == 1) else 1.0)
        total_dist_m += step_m

        # Slope at destination pixel (clamp to array bounds)
        sr = max(0, min(r1, h - 1))
        sc = max(0, min(c1, w - 1))
        slope_deg = float(slope_array[sr, sc])
        if not math.isfinite(slope_deg):
            slope_deg = 0.0
        slope_rad = math.radians(slope_deg)

        # Time for this step
        time_hrs = (step_m / speed_m_s) / 3600.0

        flat_cost_wh = BASE_POWER_W * time_hrs

        # Rolling resistance surcharge (Bekker-Wong soft terrain).
        # Only applied when mobility_risk_map is provided; without the terramechanics
        # layer the slope-based model covers bulk terrain effects and rolling resistance
        # is implicitly zero (consistent with existing validation baselines).
        # Baseline μr = 0.015 for compacted nominal regolith (Carrier et al. 1991;
        # Wong 2008 Table 2.3); scales up to 4× on worst-case soft terrain (Iagnemma &
        # Dubowsky 2004).
        if mobility_risk_map is not None:
            rr = max(0, min(sr, mobility_risk_map.shape[0] - 1))
            rc = max(0, min(sc, mobility_risk_map.shape[1] - 1))
            local_risk = float(mobility_risk_map[rr, rc])
            rr_factor  = 0.015 * (1.0 + 3.0 * local_risk)
            total_energy_wh += flat_cost_wh * rr_factor

        # Determine uphill / downhill direction
        is_downhill = False
        if elevation is not None:
            er0 = max(0, min(r0, elevation.shape[0] - 1))
            ec0 = max(0, min(c0, elevation.shape[1] - 1))
            er1 = max(0, min(r1, elevation.shape[0] - 1))
            ec1 = max(0, min(c1, elevation.shape[1] - 1))
            e0 = float(elevation[er0, ec0])
            e1 = float(elevation[er1, ec1])
            if math.isfinite(e0) and math.isfinite(e1) and e1 < e0:
                is_downhill = True

        if is_downhill:
            regen_wh = flat_cost_wh * REGEN_FRACTION * math.sin(slope_rad)
            net_cost = flat_cost_wh - regen_wh
            downhill_regen_wh += regen_wh
            total_energy_wh   += max(0.0, net_cost)
        else:
            slope_cost_wh = flat_cost_wh * (1.0 + math.sin(slope_rad) * SLOPE_MOTOR_FACTOR)
            uphill_energy_wh += slope_cost_wh
            total_energy_wh  += slope_cost_wh

    total_dist_km = total_dist_m / 1000.0
    energy_per_km = (total_energy_wh / total_dist_km) if total_dist_km > 0 else 0.0
    battery_pct_used = (total_energy_wh / battery_wh) * 100.0

    if battery_pct_used < ENERGY_RISK_MODERATE:
        energy_risk = "LOW"
    elif battery_pct_used < ENERGY_RISK_HIGH:
        energy_risk = "MODERATE"
    else:
        energy_risk = "HIGH"

    return {
        "total_energy_wh":   round(total_energy_wh,   4),
        "uphill_energy_wh":  round(uphill_energy_wh,  4),
        "downhill_regen_wh": round(downhill_regen_wh, 4),
        "energy_per_km":     round(energy_per_km,     4),
        "battery_pct_used":  round(battery_pct_used,  4),
        "energy_risk":       energy_risk,
    }


# ---------------------------------------------------------------------------
# estimate_sunlight
# ---------------------------------------------------------------------------

def estimate_sunlight(
    elevation: np.ndarray,
    profile: dict,
    power_source: str | None = None,
) -> np.ndarray:
    """Build a float32 solar illumination map matching the DEM shape.

    Uses a memory-efficient downsampled approach: builds lat/lon grid at
    stride DOWNSAMPLE_STEP, computes sunlight values, then upsamples.

    Parameters
    ----------
    elevation : 2-D float32 array
    profile : dict from load_terrain() — must contain ``transform`` and ``crs``
    power_source : optional str; if ``"solar"`` applies extra polar penalty

    Returns
    -------
    np.ndarray, shape == elevation.shape, dtype float32, values in [0, 1]
    """
    import rasterio.transform as rt
    import pyproj

    h, w = elevation.shape

    # Source: AVGVISIB_75S_120M_201608.TIF (NASA LOLA 2016) — fraction of 22,396
    # observations with direct solar illumination. Use directly when available.
    illum = profile.get("illumination_map")
    if illum is not None:
        out = illum.astype(np.float32)
        out[~np.isfinite(elevation)] = np.float32(0.0)
        return out

    # Build downsampled row/col index arrays
    rows_ds = np.arange(0, h, DOWNSAMPLE_STEP, dtype=np.int32)
    cols_ds = np.arange(0, w, DOWNSAMPLE_STEP, dtype=np.int32)
    ds_h = len(rows_ds)
    ds_w = len(cols_ds)

    col_grid, row_grid = np.meshgrid(cols_ds, rows_ds)  # (ds_h, ds_w)

    # Pixel coords → projected XY (Moon polar-stereographic)
    transform = profile["transform"]
    xs, ys = rt.xy(transform, row_grid.ravel(), col_grid.ravel())
    xs = np.array(xs, dtype=np.float64)
    ys = np.array(ys, dtype=np.float64)

    # Projected XY → lon/lat
    crs_stere  = "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
    crs_lonlat = "+proj=longlat +R=1737400 +no_defs"
    transformer = pyproj.Transformer.from_crs(crs_stere, crs_lonlat, always_xy=True)
    lons, lats = transformer.transform(xs, ys)

    lats = lats.reshape(ds_h, ds_w)

    # Downsampled elevation (nanmean blocks)
    # Use simple sampling at the downsampled pixel positions
    elev_ds = elevation[row_grid, col_grid].astype(np.float64)
    with np.errstate(all="ignore"):
        global_mean_elev = float(np.nanmean(elevation))

    # Build sunlight at downsampled resolution
    sunlight_ds = np.full((ds_h, ds_w), 0.5, dtype=np.float64)

    # Polar floor
    sunlight_ds[lats < -89.0] = SUNLIGHT_POLAR_FLOOR

    # High-lat bonus (only where not already set to polar floor)
    mask_high = (lats > -85.0) & (lats >= -89.0)
    sunlight_ds[mask_high] = SUNLIGHT_HIGH_LAT

    # Ridge bonus
    ridge_mask = elev_ds > (global_mean_elev + 500.0)
    sunlight_ds[ridge_mask] = np.clip(
        sunlight_ds[ridge_mask] + SUNLIGHT_RIDGE_BONUS, 0.0, 1.0
    )

    # Basin penalty
    basin_mask = elev_ds < (global_mean_elev - 1000.0)
    sunlight_ds[basin_mask] = np.clip(
        sunlight_ds[basin_mask] - SUNLIGHT_BASIN_PENALTY, 0.0, 1.0
    )

    # Clamp [0, 1]
    sunlight_ds = np.clip(sunlight_ds, 0.0, 1.0)

    # Additional solar penalty at near-permanent-shadow latitudes
    if power_source == "solar":
        sunlight_ds[lats < -88.0] *= 0.6
        sunlight_ds = np.clip(sunlight_ds, 0.0, 1.0)

    # Upsample to full DEM shape using actual array shapes to avoid off-by-one
    zoom_r = h / ds_h
    zoom_c = w / ds_w
    sunlight_full = zoom(sunlight_ds, (zoom_r, zoom_c), order=1)

    # Ensure exact shape match (zoom rounding can be off by 1 pixel)
    if sunlight_full.shape != (h, w):
        from scipy.ndimage import zoom as _zoom
        sunlight_full = _zoom(sunlight_ds, (h / ds_h, w / ds_w), order=1)
        # Fallback: crop or pad
        out = np.zeros((h, w), dtype=np.float64)
        rh = min(sunlight_full.shape[0], h)
        rw = min(sunlight_full.shape[1], w)
        out[:rh, :rw] = sunlight_full[:rh, :rw]
        sunlight_full = out

    # NaN elevation pixels → 0.0
    nan_mask = ~np.isfinite(elevation)
    sunlight_full[nan_mask] = 0.0

    return np.clip(sunlight_full, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# compute_sun_elevation_deg
# ---------------------------------------------------------------------------

def compute_sun_elevation_deg(mission_day: float) -> float:
    """Approximate Sun elevation above the lunar south-pole horizon.

    The Moon's obliquity (1.5424°) causes the Sun to oscillate ±1.5424° over
    each 29.53-day synodic month at the poles. Day 0 = new moon (minimum
    south-pole illumination); day ~7.38 = first quarter (maximum).

    Parameters
    ----------
    mission_day : float
        Day within the lunar synodic cycle, in [0, 29.530589).

    Returns
    -------
    float
        Sun elevation in degrees, range [-1.5424, +1.5424].
    """
    angle_rad = 2.0 * math.pi * mission_day / LUNAR_SYNODIC_PERIOD_DAYS
    return MOON_OBLIQUITY_DEG * math.sin(angle_rad)


# ---------------------------------------------------------------------------
# compute_day_illumination
# ---------------------------------------------------------------------------

def compute_day_illumination(
    sunlight_map: np.ndarray,
    mission_day: float,
) -> np.ndarray:
    """Scale the long-term average illumination map to a specific mission day.

    The AVGVISIB map gives the fraction of time each pixel is sunlit averaged
    over the measurement period. For day d within the synodic cycle the Sun
    rides ±1.5424° above/below the horizon, modulating illumination probability.

    Parameters
    ----------
    sunlight_map : np.ndarray, float32, shape (H, W), values in [0, 1]
        Long-term average illumination fraction (profile["sunlight_map"]).
    mission_day : float
        Day within the lunar synodic cycle, in [0, 29.530589).

    Returns
    -------
    np.ndarray, float32, shape (H, W), values in [0, 1]
        Day-specific illumination probability per pixel.
    """
    sun_elev_deg = compute_sun_elevation_deg(mission_day)
    scale = (sun_elev_deg + MOON_OBLIQUITY_DEG) / (2.0 * MOON_OBLIQUITY_DEG)
    scale = max(0.0, min(1.0, scale))
    return np.clip(
        sunlight_map.astype(np.float32) * np.float32(scale),
        np.float32(0.0),
        np.float32(1.0),
    )


# ---------------------------------------------------------------------------
# find_recharge_stops
# ---------------------------------------------------------------------------

def find_recharge_stops(
    path: list[tuple[int, int]] | None,
    slope_array: np.ndarray,
    sunlight_map: np.ndarray | None,
    rover_profile: dict,
    resolution_m: float,
    elevation: np.ndarray | None,
    mission_day: float,
    profile: dict,
) -> list[dict]:
    """Simulate battery state along a path and identify forced recharge stops.

    For solar rovers only. Walks the path pixel by pixel, subtracting step
    energy (same formula as compute_path_energy), and records each pixel where
    the battery falls to BATTERY_STOP_THRESHOLD_PCT. At each stop the rover
    waits until the battery reaches BATTERY_RESUME_THRESHOLD_PCT, or the stop
    is marked infeasible (recharge_time_hrs=None) if illumination is too low.

    Parameters
    ----------
    path : list of (row, col) tuples, or None
    slope_array : 2-D float32 slope array (degrees)
    sunlight_map : 2-D float32 average illumination map [0, 1], or None
    rover_profile : dict; requires keys power_source, battery_wh, speed_kmh,
                    solar_panel_w
    resolution_m : ground sampling distance (metres per pixel)
    elevation : optional 2-D float32 elevation array (enables downhill regen)
    mission_day : day within lunar synodic cycle [0, 29.530589)
    profile : terrain profile dict with 'transform' key (rasterio Affine)

    Returns
    -------
    list[dict] — one entry per forced stop, with keys:
        pixel_row, pixel_col, lat, lon,
        illumination_frac, P_charge_w, net_charge_rate_wh_hr,
        battery_at_stop_pct, energy_gained_wh, recharge_time_hrs
        (recharge_time_hrs is None when net charging rate <= 0)
    """
    if rover_profile.get("power_source") != "solar":
        return []
    if not path or len(path) < 2:
        return []
    if sunlight_map is None:
        return []

    solar_panel_w = float(rover_profile.get("solar_panel_w", 0.0))
    if solar_panel_w <= 0.0:
        return []

    speed_kmh = float(rover_profile.get("speed_kmh", 0.5)) or 0.5
    speed_m_s = speed_kmh * 1000.0 / 3600.0

    battery_wh = float(rover_profile.get("battery_wh", BATTERY_WH_DEFAULT))
    if battery_wh <= 0:
        battery_wh = BATTERY_WH_DEFAULT

    stop_wh   = battery_wh * BATTERY_STOP_THRESHOLD_PCT   / 100.0
    resume_wh = battery_wh * BATTERY_RESUME_THRESHOLD_PCT / 100.0

    h, w = slope_array.shape
    day_illum = compute_day_illumination(sunlight_map, mission_day)

    import rasterio.transform as rt
    import pyproj
    crs_stere  = "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
    crs_lonlat = "+proj=longlat +R=1737400 +no_defs"
    _transformer = pyproj.Transformer.from_crs(crs_stere, crs_lonlat, always_xy=True)
    _tf = profile["transform"]

    def _pixel_to_latlon(r: int, c: int) -> tuple[float, float]:
        x, y = rt.xy(_tf, r, c)
        lon, lat = _transformer.transform(x, y)
        return float(lat), float(lon)

    current_wh = battery_wh
    stops: list[dict] = []

    for i in range(len(path) - 1):
        r0, c0 = path[i]
        r1, c1 = path[i + 1]

        dr = abs(r1 - r0)
        dc = abs(c1 - c0)
        step_m = resolution_m * (_SQRT2 if (dr == 1 and dc == 1) else 1.0)

        sr = max(0, min(r1, h - 1))
        sc = max(0, min(c1, w - 1))
        slope_deg = float(slope_array[sr, sc])
        if not math.isfinite(slope_deg):
            slope_deg = 0.0
        slope_rad = math.radians(slope_deg)

        time_hrs     = (step_m / speed_m_s) / 3600.0
        flat_cost_wh = BASE_POWER_W * time_hrs

        is_downhill = False
        if elevation is not None:
            er0 = max(0, min(r0, elevation.shape[0] - 1))
            ec0 = max(0, min(c0, elevation.shape[1] - 1))
            er1 = max(0, min(r1, elevation.shape[0] - 1))
            ec1 = max(0, min(c1, elevation.shape[1] - 1))
            e0  = float(elevation[er0, ec0])
            e1  = float(elevation[er1, ec1])
            if math.isfinite(e0) and math.isfinite(e1) and e1 < e0:
                is_downhill = True

        if is_downhill:
            regen_wh  = flat_cost_wh * REGEN_FRACTION * math.sin(slope_rad)
            step_cost = max(0.0, flat_cost_wh - regen_wh)
        else:
            step_cost = flat_cost_wh * (1.0 + math.sin(slope_rad) * SLOPE_MOTOR_FACTOR)

        current_wh -= step_cost
        current_wh  = max(0.0, current_wh)

        if current_wh <= stop_wh:
            di_r = max(0, min(r1, day_illum.shape[0] - 1))
            di_c = max(0, min(c1, day_illum.shape[1] - 1))
            pixel_illum = float(day_illum[di_r, di_c])

            P_charge = solar_panel_w * pixel_illum
            net_rate = max(0.0, P_charge - IDLE_POWER_W)
            battery_at_stop_pct = (current_wh / battery_wh) * 100.0

            if net_rate > 0.0:
                energy_gained = resume_wh - current_wh
                recharge_hrs  = energy_gained / net_rate
                current_wh    = resume_wh
            else:
                energy_gained = 0.0
                recharge_hrs  = None   # infeasible — no net charging at this pixel

            lat, lon = _pixel_to_latlon(r1, c1)

            stops.append({
                "pixel_row":             r1,
                "pixel_col":             c1,
                "lat":                   round(lat, 5),
                "lon":                   round(lon, 5),
                "illumination_frac":     round(pixel_illum, 4),
                "P_charge_w":            round(P_charge, 2),
                "net_charge_rate_wh_hr": round(net_rate, 2),
                "battery_at_stop_pct":   round(battery_at_stop_pct, 2),
                "energy_gained_wh":      round(energy_gained, 2),
                "recharge_time_hrs":     round(recharge_hrs, 2) if recharge_hrs is not None else None,
            })

    return stops


# ---------------------------------------------------------------------------
# __main__ — visual verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pathlib import Path
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from affine import Affine

    print("Generating synthetic sunlight preview …")

    H, W = 200, 200
    # Synthetic elevation: gentle gradient + ridge in upper third
    elev_syn = np.zeros((H, W), dtype=np.float32)
    elev_syn[:, :] = np.linspace(-4000, 1000, W)[np.newaxis, :]
    elev_syn[30:50, :] += 2000   # ridge band

    # Synthetic profile: Moon polar-stere covering ~-88° to -90°S
    _map_scale = 500.0
    _origin    = -50000.0
    transform_syn = Affine(_map_scale, 0, _origin, 0, -_map_scale, -_origin)
    profile_syn = {
        "transform": transform_syn,
        "crs": "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs",
        "height": H,
        "width":  W,
    }

    sunlight = estimate_sunlight(elev_syn, profile_syn, power_source="solar")
    print(f"  shape={sunlight.shape}, dtype={sunlight.dtype}, "
          f"min={sunlight.min():.3f}, max={sunlight.max():.3f}")

    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "sunlight_preview.png"

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    im0 = axes[0].imshow(elev_syn, cmap="terrain", origin="upper")
    axes[0].set_title("Synthetic Elevation (m)")
    plt.colorbar(im0, ax=axes[0])

    im1 = axes[1].imshow(sunlight, cmap="YlOrRd", origin="upper", vmin=0, vmax=1)
    axes[1].set_title("Estimated Sunlight Fraction")
    plt.colorbar(im1, ax=axes[1])

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"  Saved → {out_path}")

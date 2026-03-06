"""
core/energy_model.py — Physics-based energy consumption and solar illumination model.

Public API
----------
compute_path_energy(path, slope_array, rover_profile, resolution_m, elevation) -> dict
estimate_sunlight(elevation, profile, power_source=None) -> np.ndarray
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
# compute_path_energy
# ---------------------------------------------------------------------------

def compute_path_energy(
    path: list[tuple[int, int]] | None,
    slope_array: np.ndarray,
    rover_profile: dict,
    resolution_m: float = 60.0,
    elevation: np.ndarray | None = None,
) -> dict:
    """Compute energy consumption statistics for a traversed path.

    Parameters
    ----------
    path : list of (row, col) tuples, or None
    slope_array : 2-D float32 array of slope in degrees
    rover_profile : dict with optional keys ``battery_wh``, ``speed_kmh``
    resolution_m : ground sampling distance in metres per pixel
    elevation : optional 2-D float32 elevation array (enables downhill regen)

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

"""
multi_res_fusion.py — Multi-resolution LOLA DEM fusion.

Loads three DEM stages at different resolutions, aligns them to a common
reference grid, and fuses into a single elevation array by priority:
    Stage3 (5 m, reference TIF) > Stage2 (10 m JP2) > Stage1 (20 m JP2)

All downstream modules call load_fused() to get aligned elevation data.
"""

from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import reproject, Resampling

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE = Path(__file__).parent.parent

PATHS = {
    "ref_prod":    BASE / "data" / "processed_dem.tif",
    "ref_preview": BASE / "data" / "processed_dem_preview.tif",
    "dem_20m":     BASE / "data" / "dem" / "DEM_20m" / "LDEM_80S_20M.JP2",
    "slope_20m":   BASE / "data" / "dem" / "DEM_20m" / "LDEC_80S_20M.JP2",
    "dem_10m":     BASE / "data" / "dem" / "DEM_10m" / "LDEM_85S_10M.JP2",
    "slope_10m":   BASE / "data" / "dem" / "DEM_10m" / "LDEC_85S_10M.JP2",
}

# LBL-derived parameters for each JP2 (no embedded CRS/geotransform)
JP2_PARAMS = {
    "dem_20m":   {"map_scale_m": 20.0, "proj_offset_px": 15199.5},
    "slope_20m": {"map_scale_m": 20.0, "proj_offset_px": 15199.5},
    "dem_10m":   {"map_scale_m": 10.0, "proj_offset_px": 15167.5},
    "slope_10m": {"map_scale_m": 10.0, "proj_offset_px": 15167.5},
}

# Raw int16 values that represent nodata in LOLA JP2s
LOLA_NODATA_RAW = {0, -32768}

# LOLA DN → elevation metres (from LBL SCALING_FACTOR)
JP2_SCALE = 0.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _jp2_affine(map_scale_m: float, proj_offset_px: float) -> Affine:
    """Construct rasterio Affine from LBL map_scale and proj_offset."""
    origin_x = -proj_offset_px * map_scale_m
    origin_y =  proj_offset_px * map_scale_m
    return Affine(map_scale_m, 0, origin_x,
                  0, -map_scale_m, origin_y)


def _load_jp2_raw(path: Path) -> tuple[np.ndarray, tuple[int, int]]:
    """Read band 1 of a JP2 as int16. Returns (array, (height, width))."""
    with rasterio.open(path) as src:
        raw = src.read(1).astype(np.int16)
        shape = (src.height, src.width)
    return raw, shape


def _scale_jp2(raw_int16: np.ndarray) -> np.ndarray:
    """Convert raw int16 DN → float32 elevation_m; mark nodata as NaN.

    np.isin() on a 30400×30400 int16 array promotes to int64 internally,
    allocating ~5 GB.  Boolean OR of equality tests stays at 1 byte/px.
    """
    arr = raw_int16.astype(np.float32) * JP2_SCALE
    nodata_mask = (raw_int16 == 0) | (raw_int16 == -32768)
    arr[nodata_mask] = np.nan
    return arr


def _resample_to_ref(
    src_data: np.ndarray,
    src_affine: Affine,
    src_crs,
    ref_profile: dict,
) -> np.ndarray:
    """Reproject src_data onto the reference grid using bilinear resampling."""
    dst = np.full(
        (ref_profile["height"], ref_profile["width"]),
        np.nan,
        dtype=np.float32,
    )
    reproject(
        source=src_data,
        destination=dst,
        src_transform=src_affine,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=ref_profile["transform"],
        dst_crs=ref_profile["crs"],
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return dst


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_fused(use_preview: bool = True) -> dict:
    """
    Load and fuse all DEM stages onto a common reference grid.

    Parameters
    ----------
    use_preview : bool
        True  → use processed_dem_preview.tif  (1666×1666, ~120 m/px, fast)
        False → use processed_dem.tif          (3333×3333,  ~60 m/px, production)

    Returns
    -------
    dict with keys:
        dem          – float32 fused elevation (Stage3 > Stage2 > Stage1)
        dem_stage1   – 20 m DEM resampled to ref grid
        dem_stage2   – 10 m DEM resampled to ref grid
        dem_stage3   – reference DEM (the processed TIF, Stage3)
        slope_stage1 – 20 m slope resampled to ref grid
        slope_stage2 – 10 m slope resampled to ref grid
        profile      – rasterio profile (crs, transform, height, width, …)
        resolution_m – pixel size in metres (from ref transform)
    """
    ref_path = PATHS["ref_preview"] if use_preview else PATHS["ref_prod"]

    # ------------------------------------------------------------------
    # 1. Open reference → extract profile and Stage3 elevation data
    # ------------------------------------------------------------------
    with rasterio.open(ref_path) as ref:
        ref_crs       = ref.crs
        ref_transform = ref.transform
        ref_height    = ref.height
        ref_width     = ref.width
        ref_profile   = {
            "crs":       ref_crs,
            "transform": ref_transform,
            "height":    ref_height,
            "width":     ref_width,
            "dtype":     "float32",
            "nodata":    np.nan,
            "count":     1,
        }
        stage3 = ref.read(1).astype(np.float32)   # already in metres

    # ------------------------------------------------------------------
    # 2. Load Stage1 (20 m) DEM and slope
    # ------------------------------------------------------------------
    print("Loading Stage1 20 m DEM …")
    raw1_dem, _ = _load_jp2_raw(PATHS["dem_20m"])
    scaled1_dem = _scale_jp2(raw1_dem)
    affine1 = _jp2_affine(**JP2_PARAMS["dem_20m"])
    stage1 = _resample_to_ref(scaled1_dem, affine1, ref_crs, ref_profile)
    del raw1_dem, scaled1_dem

    print("Loading Stage1 20 m slope …")
    raw1_slp, _ = _load_jp2_raw(PATHS["slope_20m"])
    scaled1_slp = _scale_jp2(raw1_slp)
    slope1 = _resample_to_ref(scaled1_slp, affine1, ref_crs, ref_profile)
    del raw1_slp, scaled1_slp

    # ------------------------------------------------------------------
    # 3. Load Stage2 (10 m) DEM and slope
    # ------------------------------------------------------------------
    print("Loading Stage2 10 m DEM …")
    raw2_dem, _ = _load_jp2_raw(PATHS["dem_10m"])
    scaled2_dem = _scale_jp2(raw2_dem)
    affine2 = _jp2_affine(**JP2_PARAMS["dem_10m"])
    stage2 = _resample_to_ref(scaled2_dem, affine2, ref_crs, ref_profile)
    del raw2_dem, scaled2_dem

    print("Loading Stage2 10 m slope …")
    raw2_slp, _ = _load_jp2_raw(PATHS["slope_10m"])
    scaled2_slp = _scale_jp2(raw2_slp)
    slope2 = _resample_to_ref(scaled2_slp, affine2, ref_crs, ref_profile)
    del raw2_slp, scaled2_slp

    # ------------------------------------------------------------------
    # 4. Fuse elevation: Stage3 > Stage2 > Stage1
    # ------------------------------------------------------------------
    fused = stage3.copy()

    mask2 = np.isnan(fused)
    fused[mask2] = stage2[mask2]

    mask1 = np.isnan(fused)
    fused[mask1] = stage1[mask1]

    # ------------------------------------------------------------------
    # 5. Return
    # ------------------------------------------------------------------
    resolution_m = abs(ref_profile["transform"].a)

    return {
        "dem":          fused,
        "dem_stage1":   stage1,
        "dem_stage2":   stage2,
        "dem_stage3":   stage3,
        "slope_stage1": slope1,
        "slope_stage2": slope2,
        "profile":      ref_profile,
        "resolution_m": resolution_m,
    }


# ---------------------------------------------------------------------------
# Quick sanity check (run as script)
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("multi_res_fusion — sanity check (preview mode)")
    print("=" * 60)

    result = load_fused(use_preview=True)

    expected_shape = (result["profile"]["height"], result["profile"]["width"])
    print(f"\nReference grid : {expected_shape[0]}×{expected_shape[1]} px")
    print(f"Resolution     : {result['resolution_m']:.2f} m/px\n")

    layers = [
        ("dem          (fused)",  result["dem"]),
        ("dem_stage1   (20 m)",   result["dem_stage1"]),
        ("dem_stage2   (10 m)",   result["dem_stage2"]),
        ("dem_stage3   (ref)",    result["dem_stage3"]),
        ("slope_stage1 (20 m)",   result["slope_stage1"]),
        ("slope_stage2 (10 m)",   result["slope_stage2"]),
    ]

    all_ok = True
    for name, arr in layers:
        if arr.shape != expected_shape:
            print(f"  ERROR shape mismatch: {name} → {arr.shape}")
            all_ok = False
            continue
        nan_count  = int(np.isnan(arr).sum())
        nan_pct    = 100.0 * nan_count / arr.size
        valid_vals = arr[~np.isnan(arr)]
        if valid_vals.size > 0:
            vmin, vmax = float(valid_vals.min()), float(valid_vals.max())
            range_str  = f"{vmin:+.1f} m … {vmax:+.1f} m"
        else:
            range_str = "all NaN"
        print(
            f"  {name:30s}  shape={arr.shape}  dtype={arr.dtype}"
            f"  NaN={nan_count:>8,} ({nan_pct:5.1f}%)  range=[{range_str}]"
        )

    print()
    if all_ok:
        # Confirm fused has <= NaNs of each individual stage
        nan_fused  = int(np.isnan(result["dem"]).sum())
        nan_stage3 = int(np.isnan(result["dem_stage3"]).sum())
        nan_stage2 = int(np.isnan(result["dem_stage2"]).sum())
        nan_stage1 = int(np.isnan(result["dem_stage1"]).sum())
        ok_msg = (
            "PASS" if nan_fused <= min(nan_stage3, nan_stage2, nan_stage1)
            else "WARN (fused has more NaNs than a stage — unexpected)"
        )
        print(f"Fusion NaN check: {ok_msg}")
        print(f"  fused={nan_fused:,}  stage3={nan_stage3:,}  stage2={nan_stage2:,}  stage1={nan_stage1:,}")
    print()


if __name__ == "__main__":
    main()

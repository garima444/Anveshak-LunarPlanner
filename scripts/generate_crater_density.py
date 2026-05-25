"""
scripts/generate_crater_density.py — Rasterize Robbins (2019) crater catalog.

Downloads/reads the Robbins & Hynek (2019) lunar crater database and produces a
crater-density GeoTIFF at 240 m resolution in lunar polar stereographic projection,
matching the ancillary layer expected by core/terrain.py.

Prerequisites
-------------
Download the catalog CSV (~100 MB) from:
    https://zenodo.org/record/3528686
    File: lunar_crater_database_robbins_2019.csv

Then run:
    python scripts/generate_crater_density.py --csv path/to/lunar_crater_database_robbins_2019.csv

Output
------
    data/Geology/CRATER_DENSITY_75S_240M.tif
    uint8, 0–255 (255 = highest crater density), 240 m/px, polar stereographic.

Scientific basis
----------------
Crater density predicts rock abundance (ejecta blocks) and regolith porosity.
High crater density → more fragmented, loosely packed regolith → higher wheel sinkage.
Reference: Bandfield et al. (2011) JGR Planets 116, E00H02.

Columns used from Robbins catalog
----------------------------------
    LAT_CIRC_IMG  — crater center latitude (degrees)
    LON_CIRC_IMG  — crater center longitude (degrees, 0–360 East)
    DIAM_CIRC_IMG — crater diameter (km)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parent.parent
OUTPUT_PATH = BASE / "data" / "Geology" / "CRATER_DENSITY_75S_240M.tif"

# Grid parameters (matching DEM ancillary grid)
GRID_RES_M     = 240.0          # output resolution
MOON_RADIUS_M  = 1_737_400.0   # metres
MIN_DIAM_KM    = 0.1           # filter: include craters ≥ 100 m diameter
SOUTH_LAT_CUT  = -65.0         # only include craters south of this latitude
KERNEL_SIZE    = 5             # smoothing kernel for density (pixels)

# Polar stereographic grid extent (covers 65–90°S at 240m/px)
# Origin = pole; grid is square with side ≈ 2 × 1737.4 × tan(25°) km ≈ 1620 km
GRID_EXTENT_M  = 1_620_000.0   # half-width of the polar stereo grid
GRID_SIDE      = int(2 * GRID_EXTENT_M / GRID_RES_M)   # number of pixels per side


def latlon_to_polar_stereo(lat_deg: np.ndarray, lon_deg: np.ndarray) -> tuple:
    """Convert lat/lon (degrees) to lunar polar stereographic (x, y) in metres."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    # South polar stereographic: scale factor k = cos(lat)/cos(45+lat/2)²
    # Simplified to r = R × (1 + sin(lat_0)) / (1 + sin(lat)) × cos(lat) × tan((45+lat/2)…)
    # Approximate: r ≈ R × cos(lat) / (1 - sin(lat)) for south pole projection
    sin_lat = np.sin(lat)
    r = MOON_RADIUS_M * np.cos(lat) / (1.0 - sin_lat)   # equidistant approx
    x = r * np.sin(lon)
    y = r * np.cos(lon)   # y increases toward pole in south-polar projection
    return x, y


def polar_stereo_to_pixel(x: np.ndarray, y: np.ndarray) -> tuple:
    """Convert polar-stereo (x, y) metres to pixel (row, col) indices."""
    col = ((x + GRID_EXTENT_M) / GRID_RES_M).astype(int)
    row = ((GRID_EXTENT_M - y) / GRID_RES_M).astype(int)
    return row, col


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate crater density GeoTIFF from Robbins 2019 catalog")
    parser.add_argument(
        "--csv", required=True,
        help="Path to lunar_crater_database_robbins_2019.csv (download from https://zenodo.org/record/3528686)"
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    print(f"Reading crater catalog: {csv_path}")
    try:
        import pandas as pd
    except ImportError:
        print("ERROR: pandas is required. Install with: pip install pandas")
        sys.exit(1)

    df = pd.read_csv(csv_path, usecols=["LAT_CIRC_IMG", "LON_CIRC_IMG", "DIAM_CIRC_IMG"], low_memory=False)
    print(f"  Loaded {len(df):,} craters")

    # Filter: south pole region and minimum diameter
    df = df[df["LAT_CIRC_IMG"] <= SOUTH_LAT_CUT]
    df = df[df["DIAM_CIRC_IMG"] >= MIN_DIAM_KM]
    print(f"  Filtered to {len(df):,} craters (lat ≤ {SOUTH_LAT_CUT}°, diam ≥ {MIN_DIAM_KM} km)")

    if len(df) == 0:
        print("ERROR: No craters match the filter. Check column names in the CSV.")
        sys.exit(1)

    # Convert to polar stereo pixel coordinates
    lat_arr = df["LAT_CIRC_IMG"].to_numpy(dtype=np.float64)
    lon_arr = df["LON_CIRC_IMG"].to_numpy(dtype=np.float64)
    x, y = latlon_to_polar_stereo(lat_arr, lon_arr)
    rows, cols = polar_stereo_to_pixel(x, y)

    # Count craters per pixel cell
    print(f"  Rasterizing to {GRID_SIDE}×{GRID_SIDE} grid @ {GRID_RES_M:.0f} m/px …")
    density = np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.float32)
    valid = (rows >= 0) & (rows < GRID_SIDE) & (cols >= 0) & (cols < GRID_SIDE)
    np.add.at(density, (rows[valid], cols[valid]), 1.0)

    # Optional area-weighted count: weight by crater area (π × r²)
    r_px = (df["DIAM_CIRC_IMG"].to_numpy(dtype=np.float64) * 500.0 / GRID_RES_M)  # radius in pixels
    weights = np.pi * r_px ** 2
    density_weighted = np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.float32)
    np.add.at(density_weighted, (rows[valid], cols[valid]), weights[valid].astype(np.float32))
    del r_px, weights

    # Smooth with a small kernel to reduce single-pixel spikes
    from scipy.ndimage import uniform_filter
    density_smooth = uniform_filter(density_weighted, size=KERNEL_SIZE)

    # Normalise to uint8 0–255
    d_max = float(density_smooth.max())
    if d_max > 0:
        density_u8 = np.clip(density_smooth / d_max * 255.0, 0, 255).astype(np.uint8)
    else:
        print("WARNING: All crater densities are zero — output will be blank.")
        density_u8 = np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.uint8)

    # Build affine transform (south polar stereographic, pixel centre convention)
    from affine import Affine
    transform = Affine(GRID_RES_M, 0.0, -GRID_EXTENT_M,
                       0.0, -GRID_RES_M, GRID_EXTENT_M)

    # Write GeoTIFF
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    import rasterio
    import rasterio.crs
    moon_crs = rasterio.crs.CRS.from_proj4(
        "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
    )
    with rasterio.open(
        OUTPUT_PATH, "w",
        driver="GTiff",
        height=GRID_SIDE, width=GRID_SIDE,
        count=1, dtype="uint8",
        crs=moon_crs,
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(density_u8[np.newaxis, :, :])

    print(f"  Written: {OUTPUT_PATH}")
    print(f"  Grid size: {GRID_SIDE}×{GRID_SIDE} px @ {GRID_RES_M:.0f} m/px")
    print(f"  Max density (before normalisation): {d_max:.1f} weighted crater-area units")
    print(f"  Non-zero pixels: {int(np.count_nonzero(density_u8)):,} / {GRID_SIDE**2:,}")
    print("\nDone. Anveshak will now load crater density from this file automatically.")


if __name__ == "__main__":
    main()

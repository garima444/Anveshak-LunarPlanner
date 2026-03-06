"""
preprocessing.py — Downsample the raw LOLA DEM for use in Anveshak.

Input:  data/dem/ldem_87s_5mpp.tif   (5 m/px, ~3.3 GB)
Output: data/processed_dem.tif        (60 m/px, factor-12 average resample)
        data/processed_dem_preview.tif (120 m/px, factor-24 average resample)

Run:
    conda activate anveshak
    python preprocessing.py
"""

from __future__ import annotations

import os
from pathlib import Path

import rasterio
from rasterio.enums import Resampling

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).parent
INPUT_PATH = BASE_DIR / "data" / "dem" / "ldem_87s_5mpp.tif"
OUT_60M    = BASE_DIR / "data" / "processed_dem.tif"
OUT_120M   = BASE_DIR / "data" / "processed_dem_preview.tif"

FACTOR_60M  = 12   # 5 m × 12 = 60 m/px
FACTOR_120M = 24   # 5 m × 24 = 120 m/px


def resample_and_save(
    src: rasterio.DatasetReader,
    factor: int,
    output_path: Path,
) -> None:
    """Read *src* downsampled by *factor* and write a compressed GeoTIFF."""
    new_height = src.height // factor
    new_width  = src.width  // factor

    print(f"    Reading and resampling (factor={factor}) → "
          f"{new_width} × {new_height} px …")

    data = src.read(
        out_shape=(src.count, new_height, new_width),
        resampling=Resampling.average,
    )

    # Scale the affine transform to match the new resolution
    new_transform = src.transform * src.transform.scale(
        src.width  / new_width,
        src.height / new_height,
    )

    profile = src.profile.copy()
    profile.update(
        width=new_width,
        height=new_height,
        transform=new_transform,
        compress="deflate",
        predictor=2,       # horizontal differencing — good for elevation data
        zlevel=6,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        bigtiff="IF_SAFER",
    )

    print(f"    Writing {output_path.name} …")
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data)

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"    Saved  : {output_path}")
    print(f"    Shape  : {src.count} band(s), {new_height} rows × {new_width} cols")
    print(f"    Size   : {size_mb:.1f} MB")


def main() -> None:
    # ------------------------------------------------------------------
    # Step 1 — Validate input
    # ------------------------------------------------------------------
    print("\n[1/5] Checking input file …")
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"DEM not found: {INPUT_PATH}\n"
            "Place ldem_87s_5mpp.tif in data/dem/ and re-run."
        )
    input_mb = INPUT_PATH.stat().st_size / (1024 ** 2)
    print(f"    Found  : {INPUT_PATH}")
    print(f"    Size   : {input_mb:.0f} MB ({input_mb/1024:.2f} GB)")

    # ------------------------------------------------------------------
    # Step 2 — Inspect source metadata
    # ------------------------------------------------------------------
    print("\n[2/5] Reading source metadata …")
    with rasterio.open(INPUT_PATH) as src:
        print(f"    Bands  : {src.count}")
        print(f"    Shape  : {src.height} rows × {src.width} cols")
        print(f"    Dtype  : {src.dtypes[0]}")
        print(f"    CRS    : {src.crs}")
        print(f"    NoData : {src.nodata}")
        print(f"    Bounds : {src.bounds}")
        print(f"    Transform:\n        {src.transform}")

        res_x = abs(src.transform.a)
        res_y = abs(src.transform.e)
        print(f"    Pixel size (from transform): {res_x:.4f} × {res_y:.4f} map units")

        # ------------------------------------------------------------------
        # Step 3 — Produce 60 m/px output
        # ------------------------------------------------------------------
        print(f"\n[3/5] Downsampling to 60 m/px (factor {FACTOR_60M}) …")
        OUT_60M.parent.mkdir(parents=True, exist_ok=True)
        resample_and_save(src, FACTOR_60M, OUT_60M)

        # ------------------------------------------------------------------
        # Step 4 — Produce 120 m/px preview
        # ------------------------------------------------------------------
        print(f"\n[4/5] Downsampling to 120 m/px (factor {FACTOR_120M}) …")
        resample_and_save(src, FACTOR_120M, OUT_120M)

    # ------------------------------------------------------------------
    # Step 5 — Summary
    # ------------------------------------------------------------------
    print("\n[5/5] Done. Output files:")
    for path in (OUT_60M, OUT_120M):
        mb = path.stat().st_size / (1024 ** 2)
        print(f"    {path.relative_to(BASE_DIR)}  ({mb:.1f} MB)")

    print("\nNext step: set DEM_PATH=data/processed_dem.tif in .env")
    print("           or use processed_dem_preview.tif for fast development.\n")


if __name__ == "__main__":
    main()

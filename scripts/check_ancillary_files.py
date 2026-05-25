"""
scripts/check_ancillary_files.py — Data setup diagnostic.

Prints a table showing which ancillary files are present and what proxy
is used when each is absent. Run before validation to verify your data setup.

Usage:
    python scripts/check_ancillary_files.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent.parent


def _fmt_size(path: Path) -> str:
    try:
        mb = path.stat().st_size / (1024 ** 2)
        return f"{mb:.1f} MB"
    except OSError:
        return "?"


def main() -> None:
    checks = [
        # (label, path, required, proxy_description)
        ("DEM 80–90°S (20m JP2)",
         BASE / "data/dem/DEM_20M/LDEM_80S_20M.JP2",
         True, "— REQUIRED: system cannot run without this"),
        ("DEM 65–80°S (30m TIFF)",
         BASE / "data/dem/LDEM_75S_30MPP_ADJ.tiff",
         False, "Chandrayaan-3 test will SKIP"),
        ("DEM 85–90°S (10m JP2)",
         BASE / "data/dem/DEM_10m/LDEM_85S_10M.JP2",
         False, "85S region unavailable (80S used instead)"),
        ("DEM 87–90°S (5m GeoTIFF)",
         BASE / "data/dem/DEM_5M/ldem_87s_5mpp.tif",
         False, "87S region unavailable"),
        ("PSR mask 65S (240m)",
         BASE / "data/PSR/LPSR_65S_240M_201608.tiff",
         False, "PSR checks will report False for 65S region"),
        ("PSR mask 75S (120m)",
         BASE / "data/PSR/LPSR_75S_120M_201608.tiff",
         False, "PSR checks will report False for 80S region"),
        ("PSR mask 85S (60m)",
         BASE / "data/PSR/LPSR_85S_060M_201608.tiff",
         False, "PSR checks will report False for 85/87S regions"),
        ("Solar illumination 65S (240m)",
         BASE / "data/SolarIllumination/AVGVISIB_65S_240M_201608.tiff",
         False, "Synthetic sunlight model used for 65S region"),
        ("Solar illumination 75S (120m)",
         BASE / "data/SolarIllumination/AVGVISIB_75S_120M_201608.tiff",
         False, "Synthetic sunlight model used for 80S region"),
        ("Solar illumination 85S (60m)",
         BASE / "data/SolarIllumination/AVGVISIB_85S_060M_201608.tiff",
         False, "Synthetic sunlight model used for 85/87S regions"),
        ("Earth visibility 65S (240m)",
         BASE / "data/EarthVisibility/AVGVISIB_65S_240M_201608_EARTH.tiff",
         False, "Earth visibility not available"),
        ("Earth visibility 75S (120m)",
         BASE / "data/EarthVisibility/AVGVISIB_75S_120M_201608_EARTH.tiff",
         False, "Earth visibility not available"),
        ("Earth visibility 85S (60m)",
         BASE / "data/EarthVisibility/AVGVISIB_85S_060M_201608_EARTH.tiff",
         False, "Earth visibility not available"),
        ("Sky visibility 65S (240m)",
         BASE / "data/SkyVisibility/SKYV_65S_240M.tiff",
         False, "Sky visibility not available"),
        ("Diviner cold-trap temperature",
         BASE / "data/Thermal/diviner_Clrtbol_max.tif",
         False, "PSR + elevation proxy used for volatile_detection science"),
        ("M3 OH-band (mineralogy)",
         BASE / "data/Mineralogy/M3_OH_BAND_75S_240M.tif",
         False, "Elevation gradient proxy (better for 80–90°S; M3 has no coverage)"),
        ("LROC crater density",
         BASE / "data/Geology/CRATER_DENSITY_75S_240M.tif",
         False, "Roughness proxy. Run scripts/generate_crater_density.py to create."),
    ]

    col_w = [35, 8, 10, 8]
    header = f"{'File':<{col_w[0]}}  {'Status':<{col_w[1]}}  {'Size':<{col_w[2]}}  Note"
    print("\n" + "=" * 80)
    print("  Anveshak — Ancillary Data Files Status")
    print("=" * 80)
    print(header)
    print("-" * 80)

    n_ok = 0
    n_missing_req = 0
    n_missing_opt = 0

    for label, path, required, proxy in checks:
        ok = path.exists()
        if ok:
            status = "OK"
            size   = _fmt_size(path)
            n_ok  += 1
        else:
            status = "REQUIRED!" if required else "missing"
            size   = "—"
            if required:
                n_missing_req += 1
            else:
                n_missing_opt += 1

        print(f"{label:<{col_w[0]}}  {status:<{col_w[1]}}  {size:<{col_w[2]}}  {proxy}")

    print("-" * 80)
    print(f"  {n_ok} present  |  {n_missing_req} REQUIRED missing  |  {n_missing_opt} optional missing")
    if n_missing_req:
        print("\n  ⚠  REQUIRED files are missing — the system cannot run. Download from NASA PDS.")
    if n_missing_opt:
        print(f"\n  ℹ  {n_missing_opt} optional files missing. Proxy fallbacks are active (see 'Note' column).")
    print("=" * 80 + "\n")

    sys.exit(1 if n_missing_req else 0)


if __name__ == "__main__":
    main()

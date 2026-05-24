"""
config.py — Anveshak application configuration.

All paths, limits, and environment-variable overrides live here.
Import with:  from config import Config
"""

from __future__ import annotations

import os
from pathlib import Path


class Config:
    # ------------------------------------------------------------------ Paths
    BASE_DIR         = Path(__file__).parent
    BUNDLED_DATA_DIR = BASE_DIR / "data" / "bundled"
    UPLOAD_DIR       = BASE_DIR / "uploads"
    TEMP_DIR         = BASE_DIR / "temp"
    MODEL_DIR        = BASE_DIR / "models"

    # Create directories on import (safe for concurrent workers — exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ Size limits
    # DEM files can be 1–5 GB (LOLA 5 m/px GeoTIFF = ~3.3 GB compressed).
    # Uploaded in 8 MB chunks to keep memory flat during transfer.
    MAX_DEM_SIZE_MB       = 5120         # 5 GB hard cap for DEM uploads
    MAX_ANCILLARY_SIZE_MB = 500          # 500 MB hard cap for ancillary layers
    UPLOAD_CHUNK_SIZE     = 8 * 1024 * 1024  # 8 MB per chunk (throughput vs. memory)

    # ----------------------------------------------------------- Processing
    WORKING_RESOLUTION_M = 60
    PREVIEW_RESOLUTION_M = 120
    MAX_ARRAY_DIM        = 12_000

    # ------------------------------------------------------------- Session
    SESSION_EXPIRE_HOURS = 4
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-in-production")

    # -------------------------------------------------------------- Server
    HOST      = "0.0.0.0"
    PORT      = int(os.environ.get("PORT", 8000))
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

    # ------------------------------------------ NASA COG streaming URLs
    # Cloud-Optimised GeoTIFFs on NASA PGDA; streamed via GDAL /vsicurl/
    # when the local DEM file is absent (deployment without large data files).
    NASA_DEM_URLS: dict[str, dict] = {
        "south_pole_80_90": {
            "url":         "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF",
            "coverage":    "80°S to 90°S",
            "resolution_m": 20,
            "description": "Primary south pole — Artemis, VIPER, Chang'e-7 targets",
        },
        "south_pole_75_90": {
            "url":         "https://pgda.gsfc.nasa.gov/data/LOLA_30mpp/LDEM_75S_30MPP_ADJ.TIF",
            "coverage":    "75°S to 90°S",
            "resolution_m": 30,
            "description": "Extended south pole region",
        },
    }

    # ------------------------------- Bundled ancillary file names
    # Small ancillary files (≤200 MB) pre-bundled with deployment.
    # Keys match the file_map keys used in core/terrain.py load_terrain().
    BUNDLED_FILES: dict[str, str] = {
        "psr":              "LPSR_75S_120M_201608.TIF",
        "illumination":     "AVGVISIB_75S_120M_201608.TIF",
        "earth_visibility": "AVGVISIB_75S_120M_201608_EARTH.TIF",
        "sky_visibility":   "SKYV_65S_240M.TIF",
        "mas_57m":          "MAS_57M_16.JP2",
        "mas_225m":         "MAS_225M_16.JP2",
        "mas_560m":         "MAS_560M_16.JP2",
        "hurst_exponent":   "HE_8.JP2",
    }

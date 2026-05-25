"""
main.py — Anveshak FastAPI application.

Wires core ML modules (terrain, landing_scorer, pathfinder, visualizer)
into a web API with a rover-profile form interface.

Key design decisions
--------------------
* Terrain is loaded lazily per region and cached in _terrain_cache.  The default
  region (south_pole_80_90) starts loading at startup; other regions load on first
  request.  Custom-uploaded DEMs are never cached (too large / one-off use).
* RoverProfile is fully dynamic: battery_wh, psr_intent, dem_region are all
  first-class fields that flow through to the scorer and pathfinder.
* /upload_dem streams the file in 1 MB chunks with a hard 500 MB limit to avoid
  OOM on the server.  Uploaded files are stored in data/uploaded/.
"""

from __future__ import annotations

# ── Windows encoding fix ─────────────────────────────────────────────────────
# Reconfigure stdout/stderr to UTF-8 so Unicode chars in core print() calls
# (arrows, degree signs, Greek letters) don't raise UnicodeEncodeError on
# Windows cp1252 terminals / uvicorn captured output.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import json
import shutil
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import hashlib
import sqlite3

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, Field, validator
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from config import Config
from core.terrain import (
    DEM_REGIONS,
    get_dem_region_info,
    load_terrain_by_region,
    latlon_to_pixel,
    crop_region,
)
from core.landing_scorer import score_terrain
from core.pathfinder import find_path, generate_waypoints
from core.visualizer import create_mission_map, create_score_chart
from core.mission_advisor import generate_report
from core.anomaly_detector import detect_anomalies
from core.energy_model import find_recharge_stops

# ---------------------------------------------------------------------------
# Session management (itsdangerous signed cookies)
# ---------------------------------------------------------------------------

_serializer = URLSafeTimedSerializer(Config.SECRET_KEY)
_SESSION_MAX_AGE = Config.SESSION_EXPIRE_HOURS * 3600   # seconds


def _get_session_id(request: Request, response: Response) -> str:
    """Extract or create a session ID from the signed 'anveshak_sid' cookie.

    On first visit (or after expiry): generates a UUID4 hex, signs it with
    itsdangerous, sets the cookie, and returns the plain ID.
    On subsequent visits: verifies and returns the existing ID.
    If the cookie is tampered / expired: rotates to a fresh session.
    """
    cookie = request.cookies.get("anveshak_sid")
    if cookie:
        try:
            return _serializer.loads(cookie, max_age=_SESSION_MAX_AGE)
        except (BadSignature, SignatureExpired):
            pass  # tampered or expired — issue a fresh session below
    sid = _uuid_mod.uuid4().hex
    signed = _serializer.dumps(sid)
    response.set_cookie(
        "anveshak_sid", signed,
        httponly=True,
        max_age=_SESSION_MAX_AGE,
        samesite="lax",
    )
    return sid


def _session_dir(session_id: str) -> Path:
    """Return (and create) the per-session upload directory."""
    d = Config.UPLOAD_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Auth — sqlite3 + hashlib.sha256 (no external deps, B-tech level logic)
# ---------------------------------------------------------------------------

_DB_PATH = Config.UPLOAD_DIR / "users.db"   # persistent disk — survives Render restarts


def _init_db() -> None:
    """Create the users table if it does not exist."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                institute     TEXT    NOT NULL,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _register_user(institute: str, email: str, password: str) -> bool:
    """Insert a new user. Returns False if email already exists."""
    _init_db()   # ensure table exists even if db was deleted at runtime
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO users (institute, email, password_hash) VALUES (?,?,?)",
                (institute, email, _hash_password(password)),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def _verify_login(email: str, password: str) -> Optional[dict]:
    """Return user dict on success, None on wrong credentials."""
    with sqlite3.connect(_DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, institute, email FROM users WHERE email=? AND password_hash=?",
            (email, _hash_password(password)),
        ).fetchone()
    return {"id": row[0], "institute": row[1], "email": row[2]} if row else None


def _get_current_user(request: Request) -> Optional[dict]:
    """Extract authenticated user from the signed 'anveshak_user' cookie."""
    cookie = request.cookies.get("anveshak_user")
    if not cookie:
        return None
    try:
        data = _serializer.loads(cookie, max_age=_SESSION_MAX_AGE)
        return data if isinstance(data, dict) and "id" in data else None
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# Terrain cache:  region_key -> (elevation, slope, roughness, profile)
# ---------------------------------------------------------------------------

_terrain_cache: dict[str, tuple] = {}
_terrain_loading: set[str] = set()
_DEFAULT_REGION = "south_pole_80_90"


async def _ensure_terrain_loaded(region_key: str) -> None:
    """Load terrain for *region_key* into cache if not already present.

    Concurrent requests for the same region wait for the first load to finish
    rather than triggering duplicate loads.
    """
    if region_key in _terrain_cache:
        return

    if region_key in _terrain_loading:
        while region_key in _terrain_loading:
            await asyncio.sleep(0.5)
        return

    _terrain_loading.add(region_key)
    try:
        print(f"[main] Loading terrain for region '{region_key}' …")
        elev, sl, rough, prof = await asyncio.to_thread(
            load_terrain_by_region, region_key
        )
        # Pre-compute and cache the latitude grid alongside terrain arrays.
        # _build_lat_grid calls pyproj in 50-row strips and takes 2–4 s on
        # a 10133-column DEM.  It only depends on the affine transform, which
        # is fixed per region — so computing it once saves time on every request.
        from core.landing_scorer import _build_lat_grid  # noqa: PLC0415
        print(f"[main] Pre-computing latitude grid for region '{region_key}' …")
        lat_grid = await asyncio.to_thread(_build_lat_grid, prof)
        prof["_lat_grid_cache"] = lat_grid
        _terrain_cache[region_key] = (elev, sl, rough, prof)
        print(f"[main] Terrain + lat grid cached for region '{region_key}'.")
    except Exception as exc:
        print(f"[main] Terrain load failed for '{region_key}': {exc}")
        raise
    finally:
        _terrain_loading.discard(region_key)


# ---------------------------------------------------------------------------
# Lifespan: pre-load default region at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()   # ensure users table exists on every startup

    async def _preload():
        try:
            await _ensure_terrain_loaded(_DEFAULT_REGION)
        except Exception as exc:
            print(f"[main] Default terrain load failed: {exc}. "
                  f"Falling back to synthetic demo terrain.")
            try:
                from core.landing_scorer import _synthetic_terrain
                elev, sl, rough, prof = await asyncio.to_thread(
                    _synthetic_terrain
                )
                _terrain_cache[_DEFAULT_REGION] = (elev, sl, rough, prof)
                print("[main] Synthetic terrain loaded as fallback.")
            except Exception as e2:
                print(f"[main] Synthetic fallback also failed: {e2}")

    asyncio.create_task(_preload())
    yield


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Anveshak",
    description="Lunar South Pole Mission Planner API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
Config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Request model — fully dynamic rover + mission profile
# ---------------------------------------------------------------------------

class RoverProfile(BaseModel):
    # Identity
    rover_name:   str = Field("Anveshak-1",   description="Rover name (display only)")
    mission_name: str = Field("Mission Alpha", description="Mission name (display only)")
    agency:       str = Field("",             description="Space agency / operator")

    # Mission
    mission_type: str = Field(
        "water_ice",
        description="water_ice | geological | atmospheric"
    )
    power_source: str = Field(
        "rtg",
        description="rtg (nuclear) | solar (photovoltaic)"
    )

    # Traverse constraints
    max_slope_deg: float = Field(
        15.0, ge=1.0, le=45.0,
        description=(
            "Maximum traversable slope in degrees. "
            "Pragyan (ISRO): 12°. VIPER (NASA): 20°. "
            "Source: ISRO mission spec / NASA VIPER Fact Sheet NF-2022-08-032-JSC."
        )
    )
    abs_max_slope_deg: float = Field(
        25.0, ge=1.0, le=45.0,
        description=(
            "Absolute hard-limit slope — terrain above this is always impassable. "
            "Must be ≥ max_slope_deg. Default 25° provides a hazard buffer."
        )
    )
    min_flat_radius_m: float = Field(
        300.0, ge=50.0, le=2000.0,
        description="Minimum radius of flat area required for landing (metres)."
    )
    speed_kmh: float = Field(
        0.5, ge=0.01, le=10.0,
        description=(
            "Nominal traverse speed in km/h. "
            "Pragyan: 0.036 km/h. VIPER: 0.6 km/h. "
            "Source: Pragyan wheel speed ~1 cm/s; VIPER nominal drive rate."
        )
    )

    # Energy system
    battery_wh: float = Field(
        1000.0, ge=10.0, le=20000.0,
        description=(
            "Total battery capacity in Watt-hours. "
            "Pragyan (ISRO): ~50 Wh (30 W solar panel, ~1.6 h charge). "
            "VIPER (NASA): ~450 Wh (4× Saft Li-ion cells). "
            "Generic RTG concept: 1000 Wh buffer. "
            "Source: ISRO Chandrayaan-3 mission report; "
            "NASA VIPER Power System description, JPL Tech Brief."
        )
    )

    # Solar panel — only used when power_source == "solar"
    solar_panel_w: float = Field(
        50.0, ge=1.0, le=5000.0,
        description=(
            "Solar panel rated net output in Watts. Used only when "
            "power_source == 'solar'. "
            "Pragyan (ISRO): 50 W panel (ISRO Chandrayaan-3 Mission Report 2023). "
            "VIPER (NASA): ~450 W peak array (NASA Fact Sheet NF-2022-08-032-JSC). "
            "Yutu-2 (CNSA): ~52 W (CRRC cells; CNSA Chang'e-4 documentation)."
        )
    )

    mission_day: float = Field(
        7.4, ge=0.0, lt=29.530589,
        description=(
            "Day within the lunar synodic cycle at mission start, in [0, 29.530589). "
            "Day 0 = new moon (minimum south-pole Sun elevation). "
            "Day ~7.4 = first quarter (maximum south-pole illumination). "
            "Day ~14.76 = full moon (zero net Sun elevation at south pole). "
            "Source: Seidelmann (1992) Explanatory Supplement, IAU standard "
            "synodic period 29.530589 days."
        )
    )

    # Rover mobility
    wheel_radius_m: float = Field(
        0.25, ge=0.01, le=2.0,
        description=(
            "Wheel radius in metres — sets the rover-capability roughness threshold. "
            "Pragyan (ISRO Chandrayaan-3): 0.075 m (150 mm diameter ÷ 2). "
            "  Source: ISRO Chandrayaan-3 Mission Document, 2023. "
            "VIPER (NASA): 0.25 m (500 mm diameter ÷ 2). "
            "  Source: NASA VIPER Fact Sheet NF-2022-08-032-JSC. "
            "Terrain becomes hazardous when pixel-roughness ≥ wheel_radius × 20 "
            "(2× radius clearance × 10× pixel-to-wheel scale factor). "
            "Default 0.25 m matches VIPER as the reference polar rover."
        )
    )
    rover_mass_kg: float = Field(
        150.0, ge=1.0, le=5000.0,
        description=(
            "Total rover mass in kg — used for per-wheel load in the Bekker-Wong "
            "sinkage model (Bekker 1969; Carrier et al. 1991 Lunar Sourcebook Table 9.28). "
            "Pragyan (ISRO Chandrayaan-3): 26 kg. "
            "  Source: ISRO Chandrayaan-3 Mission Report 2023. "
            "VIPER (NASA): 430 kg. "
            "  Source: Colaprete et al. (2019) EPSC-DPS Joint Meeting 2019. "
            "Default 150 kg for a generic mid-class rover."
        )
    )
    wheel_width_m: float = Field(
        0.20, ge=0.01, le=1.0,
        description=(
            "Wheel tread width in metres — Bekker contact-patch parameter b. "
            "Wider wheels distribute load over more area, reducing sinkage. "
            "Pragyan: 0.050 m (ISRO Chandrayaan-3 Mission Document 2023). "
            "VIPER: 0.20 m (NASA VIPER Fact Sheet NF-2022-08-032-JSC). "
            "Default 0.20 m matches VIPER."
        )
    )
    n_wheels: int = Field(
        6, ge=1, le=12,
        description=(
            "Number of driven wheels — divides total mass to give per-wheel load "
            "for the Bekker-Wong sinkage calculation. "
            "Pragyan: 6. VIPER: 6. Yutu-2: 6. "
            "Source: respective mission documentation."
        )
    )

    # PSR strategy
    psr_intent: str = Field(
        "rim",
        description=(
            "Permanently Shadowed Region (PSR) access strategy. "
            "'rim'    — land on rim, short sorties inside (VIPER/Artemis approach). "
            "'enter'  — rover enters PSR (RTG-only; ice drilling/volatile sampling). "
            "'avoid'  — avoid PSR and 2 km buffer (atmospheric/geology missions). "
            "Source: NASA/TM-2022-217504; Xiao et al. 2021 Nat. Astron."
        )
    )

    # Science vs safety trade-off
    priority: float = Field(
        0.3, ge=0.0, le=1.0,
        description="0 = maximum safety, 1 = maximum science."
    )

    # Science experiment catalog — drives science_map construction and path cost discount
    # science_weight = priority × 0.5 (max 50% cost reduction at high-value pixels)
    science_experiments: list[str] = Field(
        default_factory=list,
        description=(
            "Science experiment IDs to guide path routing. "
            "volatile_detection (Paige 2010), mineralogy (Spudis 2013 Mini-RF CPR), "
            "thermal_environment (Mazarico 2011 illumination gradient), "
            "geomorphology (Kreslavsky 2000 MAS fractal), "
            "space_weathering (Kreslavsky 2000 freshness index). "
            "Empty list = slope-only routing (existing behaviour). "
            "Note: regolith_mechanics removed (May 2026 data-source upgrade)."
        )
    )

    @validator("science_experiments", each_item=True)
    def _check_science_exp(cls, v: str) -> str:
        valid = {
            "volatile_detection", "mineralogy", "thermal_environment",
            "geomorphology", "space_weathering",
            # NOTE: "regolith_mechanics" removed (data-source upgrade, May 2026);
            # replaced by geomorphology (MAS fractal) + space_weathering (freshness_index).
        }
        if v not in valid:
            raise ValueError(f"Unknown science experiment: {v!r}. Valid: {sorted(valid)}")
        return v

    # Terrain source
    dem_region: str = Field(
        "south_pole_80_90",
        description=(
            "DEM region key (see /dem_regions). "
            "Use 'custom:<filename>' for uploaded files."
        )
    )

    mission_duration_days: float = Field(
        14.0, ge=1.0, le=365.0,
        description="Planned mission duration in Earth days."
    )

    # Number of top landing sites to return (1–10)
    n_results: int = Field(
        3, ge=1, le=10,
        description="Number of top landing sites to return in results."
    )

    # Focus area — optional geographic sub-region to restrict analysis.
    # Two specification modes (mutually exclusive):
    #   Rectangular: provide focus_lat_min + focus_lat_max (full longitude range used).
    #   Circular:    provide focus_center_lat + focus_center_lon + focus_radius_km.
    focus_lat_min: Optional[float] = Field(
        None, ge=-90.0, le=0.0,
        description="Focus area south boundary in decimal degrees (e.g. -89.5)."
    )
    focus_lat_max: Optional[float] = Field(
        None, ge=-90.0, le=0.0,
        description="Focus area north boundary in decimal degrees (e.g. -80.0)."
    )
    focus_center_lat: Optional[float] = Field(
        None, ge=-90.0, le=0.0,
        description="Center latitude for circular focus area (decimal degrees)."
    )
    focus_center_lon: Optional[float] = Field(
        None, ge=0.0, le=360.0,
        description="Center longitude for circular focus area (°E, 0–360)."
    )
    focus_radius_km: Optional[float] = Field(
        None, ge=1.0, le=2000.0,
        description="Radius for circular focus area in km."
    )

    # Mission target — if provided, the A* planner routes toward this coordinate.
    target_lat: Optional[float] = Field(
        None, ge=-90.0, le=0.0,
        description="Target latitude in decimal degrees."
    )
    target_lon: Optional[float] = Field(
        None, ge=0.0, le=360.0,
        description="Target longitude in °E (0–360)."
    )
    target_name: Optional[str] = Field(
        None,
        description="Named target (e.g. 'Shackleton Crater') — display only."
    )

    @validator("focus_lat_max", always=True)
    def _check_focus_bounds(cls, v, values):
        lat_min = values.get("focus_lat_min")
        if lat_min is not None and v is not None and lat_min >= v:
            raise ValueError("focus_lat_min must be less than focus_lat_max.")
        return v

    @validator("psr_intent")
    def _check_psr(cls, v):
        if v not in ("rim", "enter", "avoid"):
            raise ValueError("psr_intent must be 'rim', 'enter', or 'avoid'")
        return v

    @validator("mission_type")
    def _check_mission(cls, v):
        if v not in ("water_ice", "geological", "atmospheric"):
            raise ValueError("mission_type must be water_ice, geological, or atmospheric")
        return v

    @validator("power_source")
    def _check_power(cls, v):
        if v not in ("rtg", "solar"):
            raise ValueError("power_source must be 'rtg' or 'solar'")
        return v


# ---------------------------------------------------------------------------
# Zero path_stats fallback
# ---------------------------------------------------------------------------

_ZERO_STATS: dict = {
    "total_distance_m":  0.0,
    "total_distance_km": 0.0,
    "max_slope_deg":     0.0,
    "mean_slope_deg":    0.0,
    "estimated_time_hrs": 0.0,
    "waypoint_count":    0,
    "total_energy_wh":   0.0,
    "uphill_energy_wh":  0.0,
    "downhill_regen_wh": 0.0,
    "energy_per_km":     0.0,
    "battery_pct_used":  0.0,
    "energy_risk":       "LOW",
    "battery_feasible":  True,
    # Soft terrain risk (added May 2026 data-source upgrade)
    "mean_soft_risk":       0.0,
    "max_soft_risk":        0.0,
    "soft_terrain_pct":     0.0,
    "stuck_risk":           "LOW",
    "soft_terrain_warning": False,
}


# ---------------------------------------------------------------------------
# Core analysis helper
# ---------------------------------------------------------------------------

async def _run_analysis(rover: RoverProfile) -> dict:
    # Resolve terrain (load on demand if not in cache)
    region_key = rover.dem_region or _DEFAULT_REGION
    if region_key not in _terrain_cache:
        try:
            await _ensure_terrain_loaded(region_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Terrain load failed: {exc}")

    if region_key not in _terrain_cache:
        raise HTTPException(
            status_code=503,
            detail="Terrain not yet loaded. Please retry in a moment.",
        )

    elevation, slope, roughness, profile = _terrain_cache[region_key]

    # Focus-area crop — converts focus spec to bounding box, then crops.
    # Returns new arrays; never mutates the shared cache.
    import math as _math  # noqa: PLC0415
    _crop_bounds: tuple | None = None
    _MOON_KM_PER_DEG = 2 * _math.pi * 1737.4 / 360.0  # ≈ 30.35 km/degree

    if (rover.focus_center_lat is not None
            and rover.focus_center_lon is not None
            and rover.focus_radius_km is not None):
        # Circular focus area → rectangular bounding box
        _r = rover.focus_radius_km
        _lat_d = _r / _MOON_KM_PER_DEG
        _cos = abs(_math.cos(_math.radians(rover.focus_center_lat)))
        _lon_d = _r / (_MOON_KM_PER_DEG * _cos) if _cos > 0.01 else 180.0
        _crop_bounds = (
            (rover.focus_center_lon - _lon_d) % 360.0,
            (rover.focus_center_lon + _lon_d) % 360.0,
            rover.focus_center_lat - _lat_d,
            rover.focus_center_lat + _lat_d,
        )
    elif rover.focus_lat_min is not None and rover.focus_lat_max is not None:
        # Rectangular (lat-only): full longitude range
        _crop_bounds = (0.0, 360.0, rover.focus_lat_min, rover.focus_lat_max)

    _focus_active = _crop_bounds is not None
    if _focus_active:
        _lon_min, _lon_max, _lat_min, _lat_max = _crop_bounds
        elevation, slope, roughness, profile = crop_region(
            elevation, slope, roughness, profile,
            _lon_min, _lon_max, _lat_min, _lat_max,
        )
        # crop_region strips the stale lat-grid cache; recompute for the new extent.
        from core.landing_scorer import _build_lat_grid  # noqa: PLC0415
        profile = dict(profile)
        profile["_lat_grid_cache"] = _build_lat_grid(profile)

    rover_dict = {
        "rover_name":           rover.rover_name,
        "mission_type":         rover.mission_type,
        "power_source":         rover.power_source,
        "max_slope_deg":        rover.max_slope_deg,
        "min_flat_radius_m":    rover.min_flat_radius_m,
        "speed_kmh":            rover.speed_kmh,
        "priority":             rover.priority,
        "battery_wh":           rover.battery_wh,
        "psr_intent":           rover.psr_intent,
        "solar_panel_w":        rover.solar_panel_w,
        "mission_day":          rover.mission_day,
        "science_experiments":  rover.science_experiments,
        # Terramechanics parameters (Bekker-Wong sinkage model)
        "wheel_radius_m":       rover.wheel_radius_m,
        "rover_mass_kg":        rover.rover_mass_kg,
        "wheel_width_m":        rover.wheel_width_m,
        "n_wheels":             rover.n_wheels,
    }

    # Soft terrain / sinkage risk map (Bekker-Wong terramechanics).
    # Computed once here and plumbed into scoring, pathfinding, and energy modelling.
    # Source: Bekker (1969); Carrier et al. (1991); Arvidson et al. (2004, 2011).
    import gc
    from core.mobility import compute_trafficability_map
    mobility_risk_map = await asyncio.to_thread(
        compute_trafficability_map,
        elevation, roughness, profile,
        rover_dict, float(profile.get("resolution_m", 60.0)),
    )

    # Score terrain — discard safety/mission arrays immediately to free memory
    _safety, _mission, final_score, top_sites = await asyncio.to_thread(
        score_terrain, elevation, slope, roughness, profile, rover_dict,
        mobility_risk_map,
    )
    del _safety, _mission
    gc.collect()

    # Build science value map when experiments are selected.
    # Uses real ancillary data (Diviner, M3, LROC) when present; falls back to
    # DEM-derived proxies automatically.  science_weight = priority × 0.5.
    science_map = None
    if rover.science_experiments:
        from core.landing_scorer import build_science_map  # noqa: PLC0415
        lat_grid = profile.get("_lat_grid_cache")
        psr_map  = profile.get("psr_mask")
        res_m    = float(profile.get("resolution_m", 60.0))
        science_map = await asyncio.to_thread(
            build_science_map,
            elevation, slope, roughness, lat_grid, profile,
            rover.science_experiments, res_m, psr_map,
        )

    if not top_sites:
        raise HTTPException(status_code=500, detail="No viable landing sites found.")

    # Trim to requested number of results
    n_req = getattr(rover, "n_results", 3)
    top_sites = top_sites[:max(1, n_req)]

    # Inject sunlight_fraction into each site from the sunlight_map
    sunlight_map = profile.get("sunlight_map")
    for site in top_sites:
        if sunlight_map is not None:
            r, c = latlon_to_pixel(site["lon"], site["lat"], profile)
            r = max(0, min(r, sunlight_map.shape[0] - 1))
            c = max(0, min(c, sunlight_map.shape[1] - 1))
            site["sunlight_fraction"] = round(float(sunlight_map[r, c]), 3)
        else:
            site["sunlight_fraction"] = None

    # Anomaly detection
    anomalies = await asyncio.to_thread(
        detect_anomalies, elevation, slope, roughness, profile
    )

    # Waypoints (anomaly-guided when available; science-biased when experiments selected)
    waypoints = generate_waypoints(
        top_sites, rover.mission_type, n=3, anomalies=anomalies,
        science_map=science_map,
        science_experiments=rover.science_experiments,
    )

    # If the user supplied a target, prepend it so the planner tries it first.
    if rover.target_lat is not None and rover.target_lon is not None:
        dr, dc = latlon_to_pixel(rover.target_lon, rover.target_lat, profile)
        waypoints = [(dr, dc)] + waypoints

    # Path planning
    path = None
    path_stats = None
    if waypoints:
        start = (top_sites[0]["pixel_row"], top_sites[0]["pixel_col"])
        res_m = float(profile.get("resolution_m", 60.0))

        for i, candidate_goal in enumerate(waypoints):
            if start == candidate_goal:
                continue
            print(f"[main] Attempting path to waypoint {i}: {candidate_goal}")
            path, path_stats = await asyncio.to_thread(
                find_path, slope, start, candidate_goal, rover_dict, res_m, elevation,
                science_map, mobility_risk_map, profile,
            )
            if path is not None:
                print(f"[main] Path found to waypoint {i}.")
                break

        if path is None:
            for site in top_sites[1:5]:
                fallback_goal = (site["pixel_row"], site["pixel_col"])
                if start == fallback_goal:
                    continue
                print(f"[main] Fallback: trying path to site rank {site['rank']}")
                path, path_stats = await asyncio.to_thread(
                    find_path, slope, start, fallback_goal, rover_dict, res_m, elevation,
                    science_map, mobility_risk_map, profile,
                )
                if path is not None:
                    print(f"[main] Fallback path found to site rank {site['rank']}.")
                    break

    if path_stats is None:
        path_stats = dict(_ZERO_STATS)

    del science_map, mobility_risk_map
    gc.collect()

    # Solar recharge stop simulation
    recharge_stops: list[dict] = []
    if path is not None and rover.power_source == "solar":
        _sunlight = profile.get("sunlight_map")
        if _sunlight is not None:
            recharge_stops = await asyncio.to_thread(
                find_recharge_stops,
                path,
                slope,
                _sunlight,
                rover_dict,
                float(profile.get("resolution_m", 60.0)),
                elevation,
                rover.mission_day,
                profile,
            )

    # Mission report
    report = generate_report(
        rover_dict, top_sites,
        path_stats if path_stats != _ZERO_STATS else None,
        anomalies=anomalies,
    )

    # Visualisation
    _aoi_bounds: dict | None = None
    if _focus_active and _crop_bounds is not None:
        _lon_min_v, _lon_max_v, _lat_min_v, _lat_max_v = _crop_bounds
        _aoi_bounds = {
            "lat_min": _lat_min_v, "lat_max": _lat_max_v,
            "lon_min": _lon_min_v, "lon_max": _lon_max_v,
        }
    _dest_used = (
        {"lat": rover.target_lat, "lon": rover.target_lon, "name": rover.target_name}
        if rover.target_lat is not None else None
    )
    map_html = await asyncio.to_thread(
        create_mission_map,
        elevation, slope, final_score, top_sites, path, path_stats, profile,
        recharge_stops, _aoi_bounds, _dest_used,
    )
    chart_html = await asyncio.to_thread(create_score_chart, top_sites)

    # Mission summary
    site = top_sites[0]
    sun_pct = (
        f", sunlight {site['sunlight_fraction']*100:.0f}%"
        if site.get("sunlight_fraction") is not None else ""
    )
    mission_summary = (
        f"{rover.rover_name} ({rover.mission_type.replace('_', ' ').title()}, "
        f"{rover.power_source.upper()}, PSR={rover.psr_intent}) — analysis complete. "
        f"Top landing site at {abs(site['lat']):.2f}°S, {site['lon']:.2f}°E: "
        f"safety {site['safety_score']:.2f}, mission {site['mission_score']:.2f}"
        f"{sun_pct}. "
        f"Traverse: {path_stats['total_distance_km']:.1f} km, "
        f"{path_stats['estimated_time_hrs']:.1f} h, "
        f"battery {path_stats['battery_pct_used']:.0f}%."
    )

    if not path_stats.get("battery_feasible", True):
        batt_pct = path_stats.get("battery_pct_used", 0.0)
        mission_summary = (
            f"⚠ BATTERY WARNING: path requires {batt_pct:.0f}% of "
            f"{rover.battery_wh:.0f} Wh capacity "
            f"({batt_pct - 100:.0f}% over limit). "
            f"Increase battery_wh or choose a closer waypoint. | "
            + mission_summary
        )

    if rover.power_source == "solar" and recharge_stops:
        n_stops = len(recharge_stops)
        total_recharge_hrs = sum(
            s["recharge_time_hrs"] for s in recharge_stops
            if s["recharge_time_hrs"] is not None
        )
        infeasible = sum(1 for s in recharge_stops if s["recharge_time_hrs"] is None)
        stop_note = (
            f" | Solar: {n_stops} recharge stop(s), est. {total_recharge_hrs:.1f} h total."
        )
        if infeasible:
            stop_note += f" ⚠ {infeasible} stop(s) have NO viable charging (shadow zone)."
        mission_summary += stop_note

    return jsonable_encoder({
        "top_sites":       top_sites,
        "path_stats":      path_stats,
        "anomalies":       anomalies,
        "map_html":        map_html,
        "chart_html":      chart_html,
        "mission_summary": mission_summary,
        "report":          report,
        "recharge_stops":  recharge_stops,
        "aoi_bounds":      _aoi_bounds,
        "dest_used":       _dest_used,
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def landing(request: Request):
    """Landing page with features, about, and contact sections."""
    user = _get_current_user(request)
    return templates.TemplateResponse(
        request, "landing.html", {"user": user, "navbar_mode": "landing"}
    )


@app.get("/planner", include_in_schema=False)
async def planner(request: Request):
    """Mission planner app — main analysis tool."""
    user = _get_current_user(request)
    return templates.TemplateResponse(
        request, "app.html", {"user": user, "navbar_mode": "app"}
    )


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    user = _get_current_user(request)
    if user:
        return RedirectResponse("/planner", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"navbar_mode": "auth", "error": None}
    )


@app.get("/signup", include_in_schema=False)
async def signup_page(request: Request):
    user = _get_current_user(request)
    if user:
        return RedirectResponse("/planner", status_code=302)
    return templates.TemplateResponse(
        request, "signup.html", {"navbar_mode": "auth", "error": None}
    )


@app.get("/logout", include_in_schema=False)
async def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("anveshak_user")
    return resp


@app.post("/auth/signup", include_in_schema=False)
async def auth_signup(
    request: Request,
    institute: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    if len(password) < 6:
        return templates.TemplateResponse(
            request, "signup.html",
            {"navbar_mode": "auth",
             "error": "Password must be at least 6 characters."},
            status_code=400,
        )
    success = _register_user(institute.strip(), email.strip().lower(), password)
    if not success:
        return templates.TemplateResponse(
            request, "signup.html",
            {"navbar_mode": "auth",
             "error": "An account with this email already exists."},
            status_code=400,
        )
    user = _verify_login(email.strip().lower(), password)
    signed = _serializer.dumps(user)
    resp = RedirectResponse("/planner", status_code=303)
    resp.set_cookie("anveshak_user", signed, httponly=True,
                    max_age=_SESSION_MAX_AGE, samesite="lax")
    return resp


@app.post("/auth/login", include_in_schema=False)
async def auth_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = _verify_login(email.strip().lower(), password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html",
            {"navbar_mode": "auth",
             "error": "Invalid email or password. Please try again."},
            status_code=401,
        )
    signed = _serializer.dumps(user)
    resp = RedirectResponse("/planner", status_code=303)
    resp.set_cookie("anveshak_user", signed, httponly=True,
                    max_age=_SESSION_MAX_AGE, samesite="lax")
    return resp


@app.get("/setup", include_in_schema=False)
async def setup(request: Request):
    """Data source configuration page — choose DEM region and upload ancillary files."""
    user = _get_current_user(request)
    return templates.TemplateResponse(
        request, "setup.html", {"user": user}
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cached_regions": list(_terrain_cache.keys()),
        "loading_regions": list(_terrain_loading),
    }


@app.get("/dem_regions")
async def dem_regions():
    """List all available DEM regions with metadata and availability status."""
    return get_dem_region_info()


@app.post("/upload_dem")
async def upload_dem(file: UploadFile = File(...)):
    """Upload a custom DEM file (GeoTIFF, JP2, ENVI .img, SRTM .hgt).

    Returns a region_key of the form 'custom:<filename>' which can be used
    in the dem_region field of /analyze requests.

    Limits
    ------
    * Max file size: 5 GB (Config.MAX_DEM_SIZE_MB).  Files are streamed in
      8 MB chunks so memory usage stays flat regardless of file size.
    * Only files with georeference (CRS + affine) are accepted.
    * Integer-format DEMs are assumed to use LOLA 0.5 m/DN scaling.
    * Float32 DEMs are assumed to already be in metres.

    Notes on large files (1–5 GB)
    ------------------------------
    1. The upload is chunked (8 MB/chunk) — no full-file buffering in RAM.
    2. rasterio validation is a metadata-only probe; it does not read pixel data.
    3. Disk on the server must have enough headroom for the file (5 GB on Render).
    4. Typical upload time at 10 MB/s: 256 MB ≈ 26 s, 3.3 GB ≈ 5.5 min.
    """
    _MAX_MB    = Config.MAX_DEM_SIZE_MB          # 5 120 MB (5 GB)
    _MAX_BYTES = _MAX_MB * 1024 * 1024
    _CHUNK     = Config.UPLOAD_CHUNK_SIZE         # 8 MB
    _ALLOWED_EXTS = {".tif", ".tiff", ".jp2", ".img", ".hgt"}

    suffix = Path(file.filename or "upload.tif").suffix.lower()
    if suffix not in _ALLOWED_EXTS:
        raise HTTPException(
            400,
            f"File extension '{suffix}' not supported. Accepted: {sorted(_ALLOWED_EXTS)}."
        )

    unique_name = f"{_uuid_mod.uuid4().hex}{suffix}"
    dest = Config.UPLOAD_DIR / unique_name

    # Stream to disk in fixed-size chunks — memory stays O(chunk) not O(file).
    bytes_written = 0
    try:
        with open(dest, "wb") as out_f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_BYTES:
                    out_f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"File too large ({bytes_written // (1024*1024):,} MB). "
                        f"Maximum DEM upload size is {_MAX_MB:,} MB (5 GB)."
                    )
                out_f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {exc}")

    # Validate with rasterio (quick metadata-only probe — no full read)
    try:
        import rasterio
        with rasterio.open(dest) as src:
            if src.crs is None:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    400,
                    "Uploaded file has no CRS. Georeference it first "
                    "(QGIS: Raster → Assign Projection)."
                )
            native_res = abs(src.transform.a)
            native_h, native_w = src.height, src.width
            bands = src.count
            dtype = str(src.dtypes[0])
            crs_str = str(src.crs)

        # Estimate working-set RAM at 60 m/px
        factor = max(1, round(60.0 / native_res))
        out_h, out_w = native_h // factor, native_w // factor
        est_ram_mb = out_h * out_w * 4 * 3 / (1024 ** 2)

        warn = None
        if est_ram_mb > 2000:
            warn = (
                f"Large DEM: working set ~{est_ram_mb:.0f} MB at 60 m/px. "
                f"Load may take several minutes."
            )
        if "1737" not in crs_str and "Moon" not in crs_str:
            warn = (warn or "") + (
                " CRS does not reference Moon radius 1737.4 km — "
                "lat/lon labels may be incorrect for non-lunar DEMs."
            )

    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Cannot read uploaded DEM with rasterio: {exc}")

    return {
        "region_key":     f"custom:{unique_name}",
        "filename":       unique_name,
        "size_mb":        round(bytes_written / (1024 * 1024), 2),
        "native_res_m":   round(native_res, 2),
        "native_size":    [native_h, native_w],
        "working_res_m":  60.0,
        "working_size":   [out_h, out_w],
        "est_ram_mb":     round(est_ram_mb, 0),
        "bands":          bands,
        "dtype":          dtype,
        "crs":            crs_str,
        "warn":           warn,
    }


# ---------------------------------------------------------------------------
# Rover presets
# ---------------------------------------------------------------------------

_ROVER_PRESETS: list[dict] = [
    {
        "id": "pragyan", "name": "Pragyan (Chandrayaan-3)",
        "agency": "ISRO", "flag": "🇮🇳",
        "source": "ISRO CY3 Mission Document 2023",
        "profile": {
            "rover_name": "Pragyan", "mission_type": "geological",
            "power_source": "solar", "max_slope_deg": 12.0,
            "abs_max_slope_deg": 18.0, "speed_kmh": 0.1,
            "battery_wh": 54.0, "solar_panel_w": 50.0,
            "wheel_radius_m": 0.075, "rover_mass_kg": 26.0,
            "wheel_width_m": 0.05, "n_wheels": 6,
            "mission_duration_days": 14.0, "priority": 0.4,
            "psr_intent": "avoid",
            "science_experiments": ["geomorphology", "space_weathering"],
        },
    },
    {
        "id": "viper", "name": "VIPER (NASA)",
        "agency": "NASA", "flag": "🇺🇸",
        "source": "NASA NF-2022-08-032-JSC",
        "profile": {
            "rover_name": "VIPER", "mission_type": "water_ice",
            "power_source": "solar", "max_slope_deg": 20.0,
            "abs_max_slope_deg": 30.0, "speed_kmh": 0.8,
            "battery_wh": 450.0, "solar_panel_w": 450.0,
            "wheel_radius_m": 0.25, "rover_mass_kg": 430.0,
            "wheel_width_m": 0.20, "n_wheels": 6,
            "mission_duration_days": 100.0, "priority": 0.4,
            "psr_intent": "rim",
            "science_experiments": ["volatile_detection", "mineralogy"],
        },
    },
    {
        "id": "artemis_ltv", "name": "Artemis LTV (NASA)",
        "agency": "NASA", "flag": "🇺🇸",
        "source": "NASA Artemis III SDT 2020",
        "profile": {
            "rover_name": "Artemis LTV", "mission_type": "water_ice",
            "power_source": "rtg", "max_slope_deg": 15.0,
            "abs_max_slope_deg": 22.0, "speed_kmh": 1.5,
            "battery_wh": 2000.0, "solar_panel_w": 0.0,
            "wheel_radius_m": 0.40, "rover_mass_kg": 900.0,
            "wheel_width_m": 0.30, "n_wheels": 6,
            "mission_duration_days": 14.0, "priority": 0.3,
            "psr_intent": "rim",
            "science_experiments": ["volatile_detection", "geomorphology"],
        },
    },
    {
        "id": "change7", "name": "Chang'e-7 Rover (CNSA)",
        "agency": "CNSA", "flag": "🇨🇳",
        "source": "CNSA Chang'e-7 overview 2023",
        "profile": {
            "rover_name": "Chang'e-7 Rover", "mission_type": "water_ice",
            "power_source": "solar", "max_slope_deg": 20.0,
            "abs_max_slope_deg": 30.0, "speed_kmh": 0.5,
            "battery_wh": 500.0, "solar_panel_w": 200.0,
            "wheel_radius_m": 0.15, "rover_mass_kg": 140.0,
            "wheel_width_m": 0.12, "n_wheels": 6,
            "mission_duration_days": 90.0, "priority": 0.5,
            "psr_intent": "rim",
            "science_experiments": ["volatile_detection", "mineralogy"],
        },
    },
    {
        "id": "luna27", "name": "Luna-27 (Roscosmos)",
        "agency": "Roscosmos", "flag": "🇷🇺",
        "source": "Roscosmos Luna-27 concept 2023",
        "profile": {
            "rover_name": "Luna-27", "mission_type": "water_ice",
            "power_source": "rtg", "max_slope_deg": 20.0,
            "abs_max_slope_deg": 28.0, "speed_kmh": 0.3,
            "battery_wh": 800.0, "solar_panel_w": 0.0,
            "wheel_radius_m": 0.20, "rover_mass_kg": 200.0,
            "wheel_width_m": 0.15, "n_wheels": 6,
            "mission_duration_days": 180.0, "priority": 0.4,
            "psr_intent": "enter",
            "science_experiments": ["volatile_detection", "thermal_environment"],
        },
    },
    {
        "id": "custom", "name": "Custom Rover",
        "agency": "", "flag": "🛸",
        "source": "User defined",
        "profile": {},
    },
]


@app.get("/rover_presets")
async def rover_presets():
    """Return all supported rover preset profiles."""
    return _ROVER_PRESETS


# ---------------------------------------------------------------------------
# Generic ancillary file upload endpoint
# ---------------------------------------------------------------------------

_VALID_FILE_TYPES = frozenset([
    "dem", "psr", "illumination", "earth_visibility", "sky_visibility",
    "minirf_cpr", "mas_57m", "mas_225m", "mas_560m", "hurst_exponent", "ldsm_err",
])
_ANCILLARY_ALLOWED_EXTS = frozenset([".tif", ".tiff", ".jp2", ".img", ".hgt"])
_MAX_ANCILLARY_BYTES = Config.MAX_ANCILLARY_SIZE_MB * 1024 * 1024


@app.post("/upload/{file_type}")
async def upload_file(
    file_type: str,
    file: UploadFile = File(...),
    response: Response = None,
    session_id: str = Depends(_get_session_id),
):
    """Upload an ancillary raster file for the current session.

    file_type must be one of: dem, psr, illumination, earth_visibility,
    sky_visibility, minirf_cpr, mas_57m, mas_225m, mas_560m, hurst_exponent, ldsm_err.

    Files are stored in uploads/<session_id>/<file_type><ext> and used
    automatically when /analyze is called in the same session.
    """
    if file_type not in _VALID_FILE_TYPES:
        raise HTTPException(
            400,
            f"Unknown file_type '{file_type}'. "
            f"Valid values: {sorted(_VALID_FILE_TYPES)}."
        )

    max_bytes = (
        Config.MAX_DEM_SIZE_MB * 1024 * 1024
        if file_type == "dem"
        else _MAX_ANCILLARY_BYTES
    )
    max_mb = max_bytes // (1024 * 1024)

    suffix = Path(file.filename or "upload.tif").suffix.lower()
    if suffix not in _ANCILLARY_ALLOWED_EXTS:
        raise HTTPException(
            400,
            f"Extension '{suffix}' not supported. Accepted: {sorted(_ANCILLARY_ALLOWED_EXTS)}."
        )

    sess_dir = _session_dir(session_id)
    dest = sess_dir / f"{file_type}{suffix}"

    # Stream in 8 MB chunks — keeps memory flat even for multi-GB DEM uploads.
    bytes_written = 0
    try:
        with open(dest, "wb") as out_f:
            while True:
                chunk = await file.read(Config.UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    out_f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"File too large ({bytes_written // (1024*1024):,} MB). "
                        f"Maximum for {file_type}: {max_mb:,} MB."
                    )
                out_f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {exc}")

    # Quick rasterio validation
    try:
        import rasterio  # noqa: PLC0415
        with rasterio.open(dest) as src:
            native_res = abs(src.transform.a)
            crs_str    = str(src.crs) if src.crs else "unknown"
            bands      = src.count
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Cannot read file with rasterio: {exc}")

    return {
        "file_type":   file_type,
        "filename":    dest.name,
        "size_mb":     round(bytes_written / (1024 * 1024), 2),
        "native_res_m": round(native_res, 2),
        "bands":       bands,
        "crs":         crs_str,
        "session_id":  session_id,
    }


# ---------------------------------------------------------------------------
# Session status
# ---------------------------------------------------------------------------

@app.get("/session/status")
async def session_status(
    session_id: str = Depends(_get_session_id),
    response: Response = None,
):
    """Report which ancillary files are available for the current session."""
    sess_dir = _session_dir(session_id)
    from core.terrain import get_bundled_path  # noqa: PLC0415

    status: dict[str, dict] = {}
    for key in _VALID_FILE_TYPES:
        uploaded = next(
            (f for f in sess_dir.iterdir()
             if f.stem == key and f.suffix in _ANCILLARY_ALLOWED_EXTS),
            None,
        ) if sess_dir.exists() else None
        bundled = get_bundled_path(key) if key != "dem" else None
        status[key] = {
            "uploaded": str(uploaded) if uploaded else None,
            "bundled":  str(bundled)  if bundled  else None,
            "available": uploaded is not None or bundled is not None,
        }

    # DEM: annotate with cached regions and NASA download guidance.
    # Primary path = user uploads the DEM; NASA streaming is an optional fallback.
    status["dem"]["cached_regions"] = list(_terrain_cache.keys())
    status["dem"]["nasa_download_urls"] = {
        k: v["url"] for k, v in Config.NASA_DEM_URLS.items()
    }
    status["dem"]["upload_note"] = (
        "Upload the DEM file via the form below (up to 5 GB). "
        "NASA COG streaming is attempted as an optional fallback when no file is uploaded, "
        "but may fail if GDAL libcurl is unavailable. "
        "Download links are provided above."
    )
    # A region counts as 'available' if it's already cached (previously loaded).
    status["dem"]["available"] = (
        status["dem"]["uploaded"] is not None
        or bool(status["dem"]["cached_regions"])
    )
    ready = all(status[k]["available"] for k in ("dem",))   # dem is the only hard requirement
    return {"session_id": session_id, "ready": ready, "files": status}


# ---------------------------------------------------------------------------
# Data sources info
# ---------------------------------------------------------------------------

@app.get("/data_sources")
async def data_sources():
    """List all supported ancillary files with NASA download URLs and size hints."""
    return {
        "dem_regions": {
            k: {
                "label":       v["label"],
                "coverage":    v["coverage"],
                "size_mb":     v["size_mb"],
                "citation":    v["citation"],
                "nasa_url":    Config.NASA_DEM_URLS.get(k, {}).get("url"),
                "cog_streaming": k in Config.NASA_DEM_URLS,
            }
            for k, v in DEM_REGIONS.items()
        },
        "ancillary": {
            "psr": {
                "description": "Permanently Shadowed Region mask (LPSR, Mazarico 2011)",
                "bundled_file": Config.BUNDLED_FILES.get("psr"),
                "nasa_url": "https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/JP2/LPSR_75S_120M_201608.JP2",
                "size_mb": 12,
            },
            "illumination": {
                "description": "Solar illumination fraction (AVGVISIB, Mazarico 2011)",
                "bundled_file": Config.BUNDLED_FILES.get("illumination"),
                "nasa_url": "https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/JP2/AVGVISIB_75S_120M_201608.JP2",
                "size_mb": 12,
            },
            "earth_visibility": {
                "description": "Earth visibility fraction (AVGVISIB_EARTH, Mazarico 2011)",
                "bundled_file": Config.BUNDLED_FILES.get("earth_visibility"),
                "size_mb": 12,
            },
            "sky_visibility": {
                "description": "Sky visibility / horizon blockage (SKYV, Mazarico 2011)",
                "bundled_file": Config.BUNDLED_FILES.get("sky_visibility"),
                "size_mb": 15,
            },
            "minirf_cpr": {
                "description": "Mini-RF Circular Polarisation Ratio (Spudis 2013, JGR)",
                "bundled_file": None,
                "nasa_url": "https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-5-cdr-v1/",
                "size_mb": 4200,
                "warn": "4.2 GB global file — streaming loader used automatically.",
            },
            "mas_57m": {
                "description": "Median Absolute Slope 57 m baseline (Kreslavsky 2000, JGR)",
                "bundled_file": Config.BUNDLED_FILES.get("mas_57m"),
                "size_mb": 50,
            },
            "mas_225m": {
                "description": "Median Absolute Slope 225 m baseline",
                "bundled_file": Config.BUNDLED_FILES.get("mas_225m"),
                "size_mb": 50,
            },
            "mas_560m": {
                "description": "Median Absolute Slope 560 m baseline",
                "bundled_file": Config.BUNDLED_FILES.get("mas_560m"),
                "size_mb": 50,
            },
            "hurst_exponent": {
                "description": "LOLA Hurst Exponent (Kreslavsky 2000, JGR)",
                "bundled_file": Config.BUNDLED_FILES.get("hurst_exponent"),
                "size_mb": 50,
            },
            "ldsm_err": {
                "description": "LOLA Slope Error (Barker 2023, NASA PGDA)",
                "bundled_file": None,
                "size_mb": 30,
            },
        },
    }


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

@app.get("/export/json/{session_id}")
async def export_json(session_id: str):
    """Download the last analysis result for a session as JSON."""
    result_file = Config.UPLOAD_DIR / session_id / "last_result.json"
    if not result_file.exists():
        raise HTTPException(404, "No analysis result found for this session. Run /analyze first.")
    return StreamingResponse(
        open(result_file, "rb"),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=anveshak_{session_id[:8]}.json"},
    )


@app.get("/export/pdf/{session_id}")
async def export_pdf(session_id: str):
    """Generate and download a PDF mission report for a session."""
    result_file = Config.UPLOAD_DIR / session_id / "last_result.json"
    if not result_file.exists():
        raise HTTPException(404, "No analysis result found for this session. Run /analyze first.")

    try:
        from reportlab.lib.pagesizes import A4  # noqa: PLC0415
        from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer  # noqa: PLC0415
        from reportlab.lib.units import cm  # noqa: PLC0415
        import io  # noqa: PLC0415
    except ImportError:
        raise HTTPException(
            503,
            "reportlab is not installed. Install it with: pip install reportlab>=4.0.0"
        )

    result = json.loads(result_file.read_text(encoding="utf-8"))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Anveshak — Lunar Mission Analysis Report", styles["Title"]))
    story.append(Spacer(1, 0.4 * cm))

    summary = result.get("mission_summary", "")
    story.append(Paragraph(summary, styles["BodyText"]))
    story.append(Spacer(1, 0.4 * cm))

    report_text = result.get("report", "")
    for line in report_text.splitlines():
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 0.2 * cm))
            continue
        if stripped.startswith("##"):
            story.append(Paragraph(stripped.lstrip("#").strip(), styles["Heading2"]))
        elif stripped.startswith("#"):
            story.append(Paragraph(stripped.lstrip("#").strip(), styles["Heading1"]))
        else:
            story.append(Paragraph(stripped, styles["BodyText"]))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=anveshak_{session_id[:8]}.pdf"},
    )


@app.get("/demo")
async def demo():
    rover = RoverProfile(
        rover_name="Demo Rover",
        mission_type="water_ice",
        power_source="rtg",
        max_slope_deg=15.0,
        min_flat_radius_m=300.0,
        speed_kmh=0.5,
        priority=0.3,
        battery_wh=1000.0,
        psr_intent="rim",
        dem_region=_DEFAULT_REGION,
    )
    try:
        result = await _run_analysis(rover)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content=result)


@app.post("/analyze")
async def analyze(
    rover: RoverProfile,
    request: Request,
    response: Response,
):
    session_id = _get_session_id(request, response)
    try:
        result = await _run_analysis(rover)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Persist result for export endpoints
    try:
        sess_dir = _session_dir(session_id)
        result_path = sess_dir / "last_result.json"
        result_path.write_text(
            json.dumps(result, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # export failure is non-fatal

    return JSONResponse(content=result)

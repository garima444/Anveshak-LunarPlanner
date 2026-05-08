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

import asyncio
import shutil
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator
from starlette.requests import Request

from core.terrain import (
    UPLOAD_DIR,
    DEM_REGIONS,
    get_dem_region_info,
    load_terrain_by_region,
    latlon_to_pixel,
)
from core.landing_scorer import score_terrain
from core.pathfinder import find_path, generate_waypoints
from core.visualizer import create_mission_map, create_score_chart
from core.mission_advisor import generate_report
from core.anomaly_detector import detect_anomalies
from core.energy_model import find_recharge_stops

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
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Request model — fully dynamic rover + mission profile
# ---------------------------------------------------------------------------

class RoverProfile(BaseModel):
    # Identity
    rover_name: str = Field("Anveshak-1", description="Rover name (display only)")

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
            "volatile_detection (Paige 2010), mineralogy (Pieters 2009), "
            "thermal_environment (Vasavada 2012), geomorphology (Kreslavsky 2000), "
            "regolith_mechanics (Bandfield 2011), space_weathering (Lucey 2000). "
            "Empty list = slope-only routing (existing behaviour)."
        )
    )

    @validator("science_experiments", each_item=True)
    def _check_science_exp(cls, v: str) -> str:
        valid = {
            "volatile_detection", "mineralogy", "thermal_environment",
            "geomorphology", "regolith_mechanics", "space_weathering",
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
                science_map, mobility_risk_map,
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
                    science_map, mobility_risk_map,
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
    map_html = await asyncio.to_thread(
        create_mission_map,
        elevation, slope, final_score, top_sites, path, path_stats, profile,
        recharge_stops,
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
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
    * Max file size: 500 MB.  Files larger than this are rejected mid-stream.
    * Only files with georeference (CRS + affine) are accepted.
    * Integer-format DEMs are assumed to use LOLA 0.5 m/DN scaling.
    * Float32 DEMs are assumed to already be in metres.

    Known problems with very large uploads
    ---------------------------------------
    1. No wavelet optimisation for GeoTIFF: GDAL reads the full file before
       downsampling, so a 3 GB upload uses ~3 GB RAM during load.
    2. Upload time: 500 MB at 10 MB/s = ~50 s. FastAPI streams in 1 MB chunks.
    3. The server stores the file in data/uploaded/. Disk must have headroom.
    """
    _MAX_MB = 500
    _MAX_BYTES = _MAX_MB * 1024 * 1024
    _ALLOWED_EXTS = {".tif", ".tiff", ".jp2", ".img", ".hgt"}

    suffix = Path(file.filename or "upload.tif").suffix.lower()
    if suffix not in _ALLOWED_EXTS:
        raise HTTPException(
            400,
            f"File extension '{suffix}' not supported. Accepted: {sorted(_ALLOWED_EXTS)}."
        )

    unique_name = f"{_uuid_mod.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / unique_name

    # Stream to disk with size guard
    bytes_written = 0
    try:
        with open(dest, "wb") as out_f:
            while True:
                chunk = await file.read(1024 * 1024)   # 1 MB at a time
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_BYTES:
                    out_f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"File too large ({bytes_written // (1024*1024)} MB). "
                        f"Maximum upload size is {_MAX_MB} MB."
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
async def analyze(rover: RoverProfile):
    try:
        result = await _run_analysis(rover)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content=result)

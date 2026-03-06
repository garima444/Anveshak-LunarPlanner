"""
main.py — Anveshak FastAPI application.

Wires core ML modules (terrain, landing_scorer, pathfinder, visualizer)
into a web API with a single rover-profile form interface.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from core.terrain import load_terrain, latlon_to_pixel
from core.landing_scorer import score_terrain
from core.pathfinder import find_path, generate_waypoints
from core.visualizer import create_mission_map, create_score_chart
from core.mission_advisor import generate_report
from core.anomaly_detector import detect_anomalies

# ---------------------------------------------------------------------------
# Global terrain state
# ---------------------------------------------------------------------------

elevation = slope = roughness = profile = None
_terrain_loaded: bool = False


# ---------------------------------------------------------------------------
# Lifespan: load terrain in background on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    async def _load():
        global elevation, slope, roughness, profile, _terrain_loaded
        try:
            elevation, slope, roughness, profile = await asyncio.to_thread(load_terrain)
            _terrain_loaded = True
            print("[main] Terrain loaded successfully.")
        except Exception as e:
            print(f"[main] Terrain load failed: {e}. Falling back to synthetic demo.")
            try:
                from core.landing_scorer import _synthetic_terrain
                elevation, slope, roughness, profile = await asyncio.to_thread(
                    _synthetic_terrain
                )
                _terrain_loaded = True
                print("[main] Synthetic terrain loaded.")
            except Exception as e2:
                print(f"[main] Synthetic terrain also failed: {e2}")

    asyncio.create_task(_load())
    yield


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Anveshak",
    description="Lunar South Pole Mission Planner API",
    version="0.1.0",
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


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class RoverProfile(BaseModel):
    rover_name: str = "Anveshak-1"
    mission_type: str = "water_ice"   # water_ice | geological | atmospheric
    power_source: str = "rtg"         # solar | rtg
    max_slope_deg: float = 15.0
    min_flat_radius_m: float = 300.0
    speed_kmh: float = 0.5
    priority: float = 0.3             # 0 = max safety, 1 = max science
    battery_wh: float = 1000.0


# ---------------------------------------------------------------------------
# Zero path_stats fallback
# ---------------------------------------------------------------------------

_ZERO_STATS = {
    "total_distance_m": 0.0,
    "total_distance_km": 0.0,
    "max_slope_deg": 0.0,
    "mean_slope_deg": 0.0,
    "estimated_time_hrs": 0.0,
    "waypoint_count": 0,
    "total_energy_wh": 0.0,
    "uphill_energy_wh": 0.0,
    "downhill_regen_wh": 0.0,
    "energy_per_km": 0.0,
    "battery_pct_used": 0.0,
    "energy_risk": "LOW",
}


# ---------------------------------------------------------------------------
# Core analysis helper
# ---------------------------------------------------------------------------

async def _run_analysis(rover: RoverProfile) -> dict:
    if not _terrain_loaded or elevation is None:
        raise HTTPException(
            status_code=503,
            detail="Terrain data not yet loaded. Retry in a moment.",
        )

    rover_dict = {
        "rover_name": rover.rover_name,
        "mission_type": rover.mission_type,
        "power_source": rover.power_source,
        "max_slope_deg": rover.max_slope_deg,
        "min_flat_radius_m": rover.min_flat_radius_m,
        "speed_kmh": rover.speed_kmh,
        "priority": rover.priority,
        "battery_wh": rover.battery_wh,
    }

    # Score terrain
    _, _, final_score, top_sites = await asyncio.to_thread(
        score_terrain, elevation, slope, roughness, profile, rover_dict
    )

    if not top_sites:
        raise HTTPException(status_code=500, detail="No viable landing sites found.")

    # Inject sunlight_fraction into each site from the sunlight_map
    sunlight_map = profile.get("sunlight_map")
    if sunlight_map is not None:
        for site in top_sites:
            r, c = latlon_to_pixel(site["lon"], site["lat"], profile)
            r = max(0, min(r, sunlight_map.shape[0] - 1))
            c = max(0, min(c, sunlight_map.shape[1] - 1))
            site["sunlight_fraction"] = float(sunlight_map[r, c])
    else:
        for site in top_sites:
            site["sunlight_fraction"] = None

    # Anomaly detection
    anomalies = await asyncio.to_thread(
        detect_anomalies, elevation, slope, roughness, profile
    )

    # Waypoints (anomaly-guided when available)
    waypoints = generate_waypoints(top_sites, rover.mission_type, n=3, anomalies=anomalies)

    # Path planning
    path = None
    path_stats = None
    if len(waypoints) >= 2:
        start = (top_sites[0]["pixel_row"], top_sites[0]["pixel_col"])
        goal = waypoints[0]
        if start == goal and len(waypoints) > 1:
            goal = waypoints[1]
        if start != goal:
            path, path_stats = await asyncio.to_thread(
                find_path, slope, start, goal, rover_dict,
                float(profile.get("resolution_m", 60.0)), elevation,
            )

    if path_stats is None:
        path_stats = dict(_ZERO_STATS)

    # Mission report
    report = generate_report(
        rover_dict, top_sites,
        path_stats if path_stats != _ZERO_STATS else None,
        anomalies=anomalies,
    )

    # Visualisation
    map_html = await asyncio.to_thread(
        create_mission_map, elevation, slope, final_score, top_sites, path, path_stats, profile
    )
    chart_html = await asyncio.to_thread(create_score_chart, top_sites)

    # Mission summary
    site = top_sites[0]
    mission_summary = (
        f"{rover.rover_name} mission analysis complete. "
        f"Top landing site at {abs(site['lat']):.2f}°S, {site['lon']:.2f}°E with "
        f"safety score {site['safety_score']:.2f} and mission score {site['mission_score']:.2f}. "
        f"Recommended path covers {path_stats['total_distance_km']:.1f}km estimated "
        f"{path_stats['estimated_time_hrs']:.1f}hrs traverse to primary science target."
    )

    return jsonable_encoder({
        "top_sites": top_sites,
        "path_stats": path_stats,
        "anomalies": anomalies,
        "map_html": map_html,
        "chart_html": chart_html,
        "mission_summary": mission_summary,
        "report": report,
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "terrain_loaded": _terrain_loaded}


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
    )
    try:
        result = await _run_analysis(rover)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(content=result)


@app.post("/analyze")
async def analyze(rover: RoverProfile):
    try:
        result = await _run_analysis(rover)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(content=result)

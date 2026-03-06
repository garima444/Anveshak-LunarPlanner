"""
app.py — Anveshak: Lunar South Pole Mission Planner
FastAPI entry point.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Anveshak - Lunar South Pole Mission Planner",
    version="0.1.0",
    description="Plan safe landing sites and rover traverses on the lunar south pole.",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MissionRequest(BaseModel):
    """Input parameters for a mission planning run."""

    lon_min: float = Field(..., description="Western boundary longitude in decimal degrees.")
    lon_max: float = Field(..., description="Eastern boundary longitude in decimal degrees.")
    lat_min: float = Field(..., description="Southern boundary latitude in decimal degrees.")
    lat_max: float = Field(..., description="Northern boundary latitude in decimal degrees.")
    max_slope_deg: float = Field(default=15.0, description="Maximum allowable slope for landing/traversal (degrees).")
    top_n_sites: int = Field(default=5, ge=1, le=20, description="Number of top landing sites to evaluate and return.")
    start_lon: float | None = Field(default=None, description="Rover start longitude (optional; defaults to best landing site).")
    start_lat: float | None = Field(default=None, description="Rover start latitude.")
    goal_lon: float | None = Field(default=None, description="Rover goal longitude (optional).")
    goal_lat: float | None = Field(default=None, description="Rover goal latitude.")


class MissionResponse(BaseModel):
    """Output from a completed mission planning run."""

    mission_id: str = Field(..., description="Unique identifier for this mission plan.")
    status: str = Field(..., description="'success' or 'error'.")
    message: str = Field(..., description="Human-readable status message.")
    results_url: str | None = Field(default=None, description="URL to the HTML results page, if available.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", summary="Health check")
async def health_check() -> dict:
    """Return a simple JSON health-check response.

    Visit /docs for the interactive Swagger UI.
    """
    return {
        "status": "ok",
        "app": "Anveshak",
        "version": "0.1.0",
        "docs_url": "/docs",
    }


@app.post("/plan", response_model=MissionResponse, summary="Run mission planner")
async def plan_mission(request: MissionRequest) -> MissionResponse:
    """Run the full mission planning pipeline for the given region.

    Steps (to be implemented):
    1. Load and crop the DEM to the requested bounding box.
    2. Compute slope map.
    3. Generate and score candidate landing sites.
    4. Plan rover traverse with A* if start/goal supplied.
    5. Render visualisation and save results.
    6. Return mission_id and results URL.
    """
    pass


@app.get("/results/{mission_id}", response_class=HTMLResponse, summary="View mission results")
async def get_results(request: Request, mission_id: str) -> HTMLResponse:
    """Render the HTML results page for a completed mission plan.

    Parameters
    ----------
    mission_id:
        The unique mission identifier returned by POST /plan.
    """
    pass

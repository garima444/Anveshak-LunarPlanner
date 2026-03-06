Screenshot 2026-02-21 094555.png
#Anveshak- Lunar Mission Planner - Progress

## Project Title
Multi-Resolution Terrain Fusion and ML-Based Adaptive Landing 
Site Selection for Lunar South Pole Rover Missions

## Project Stack
- Backend: Python FastAPI
- Frontend: Plain HTML + CSS + Vanilla JS
- ML: scikit-learn (Random Forest, DBSCAN), numpy, scipy
- Environment: Conda (lunar-planner), Python 3.11
- OS: Windows
- Project path: Z:\Anveshak\lunar-mission-planner

## Data Files (all in /data folder)
### GeoTIFF (rasterio reads directly)
- ldem_87s_5mpp.tif     → DEM elevation, 5m/px,  87-90S, 3.3GB
- ldem_87s_5mpp_hillshade.tif → visual only, 5m/px, 87-90S
- dem_5m_slope.tif      → pre-computed NASA slope, 5m/px, 87-90S

### JP2 format (needs openjpeg via conda)
- LDEM_85S_10M.JP2      → DEM elevation, 10m/px, 85-90S, 220MB
- LDEC_85S_10M.JP2      → pre-computed slope,  10m/px, 85-90S
- LDEM_80S_20M.JP2      → DEM elevation, 20m/px, 80-90S, 255MB
- LDEC_80S_20M.JP2      → pre-computed slope,  20m/px, 80-90S
- All JP2 files have companion .LBL metadata files

## CRS Information
- GeoTIFF files: Polar Stereographic Moon 2000 (NOT EPSG:4326)
- JP2 files: check .LBL files for projection info
- All internal computation in pixel coordinates
- Convert to lat/lon only for frontend display
- lon/lat queries need CRS reprojection


## Done
- preprocessing.py ✅
- terrain.py ✅
  load_terrain() → elevation, slope, roughness, profile
  Shape: 10133×10133, float32, 60m/px
  Elevation: -7297 to +7027m
  Slope: 0 to 70deg
  Roughness: 0 to 746m
  Quality mask: loaded from LDEC_80S_20M.JP2
  Helpers: pixel_to_latlon(), latlon_to_pixel(), 
           get_elevation_at(), crop_region()
  CRS: Moon 2000 Polar Stereographic
  Output: outputs/terrain_preview.png verified
  - landing_scorer.py ✅
  score_terrain(elevation, slope, roughness, profile, rover_profile)
  → safety_score, mission_score, final_score (10133x10133 float32)
  → top_sites: list of 10 dicts with rank, lon, lat, elevation_m,
    slope_deg, roughness_m, safety_score, mission_score, 
    final_score, reasoning
  Rover inputs: mission_type, power_source, max_slope_deg,
                min_flat_radius_m, priority
  Demo mode: synthetic 500x500 gaussian craters (no NASA files)
  ~370 lines, verified both profiles

  - pathfinder.py ✅
  find_path(slope, start, goal, rover_profile) 
  → path (list of row,col tuples), path_stats dict
  path_stats: total_distance_m, total_distance_km,
              max_slope_deg, mean_slope_deg, 
              estimated_time_hrs, waypoint_count
  generate_waypoints(top_sites, mission_type, n=3)
  → list of (row,col) tuples
  A* verified on 20x20 synthetic grid, 333 iterations
  max_iterations: 2_000_000 with progress prints
  Impassable: slope > max_slope OR NaN pixels

  - visualizer.py ✅
  create_mission_map(elevation, slope, final_score,
    top_sites, path, path_stats, profile) → html_string
  create_score_chart(top_sites) → html_string
  Dark theme, CDN plotly, toggleable layers
  Verified: outputs/map_preview.html opens in browser

  - main.py ✅
  FastAPI app, lifespan terrain loading (non-blocking)
  GET /  → index.html form
  GET /health → terrain load status
  GET /demo → full analysis hardcoded water_ice RTG
  POST /analyze → RoverProfile → full analysis JSON
  Response: top_sites, path_stats, map_html, 
            chart_html, mission_summary
  
- templates/index.html ✅ (basic, full frontend next)
  Form with 7 rover profile fields
  Injects map + chart on response
  Demo button works


  - terrain_classifier.py ✅
  train_classifier() → classifier, metrics dict
  classify_terrain() → class_map uint8 (10133x10133)
  load_classifier() → loads from models/terrain_classifier.pkl
  Classes: HAZARD_ZONE(2.2%), RISKY_LANDING(23.9%),
           TRAVERSE_CORRIDOR(40.2%), SAFE_LANDING(33.7%),
           SCIENCE_TARGET(0.001%)
  Accuracy: 99.17%, model: 13.7MB
  Integrated with landing_scorer (bonus/penalty system)
  Output: outputs/classification_preview.html

  - mission_advisor.py ✅
  generate_report(rover_profile, top_sites, 
                  path_stats, class_map=None)
  → report dict with 8 keys:
    executive_summary, landing_site_analysis,
    path_analysis, risk_assessment,
    science_objectives (list of 3),
    mission_feasibility (NOMINAL|MARGINAL|HIGH_RISK),
    feasibility_reasons (list),
    recommendations (list of 3)
  Integrated into main.py POST /analyze response

  - anomaly_detector.py ✅
  detect_anomalies(elevation, slope, roughness, profile)
  → anomalies: list of dicts
    {centroid_row, centroid_col, lat, lon,
     anomaly_type (THERMAL_PROXY|ELEVATION_ANOMALY|
     ROUGHNESS_ANOMALY|SLOPE_TRANSITION),
     anomaly_strength, pixel_count, recommended_for}
  100k subsample, StandardScaler, DBSCAN(eps=0.5, min_samples=50)
  Integrated: pathfinder waypoints + mission_advisor objectives
  Output: outputs/anomaly_preview.html

- main.py updated ✅
  anomalies passed to generate_waypoints() and generate_report()
  anomalies key added to JSON response

  - chandrayaan3_validation.py ✅
  validation/chandrayaan3_validation.py
  Result: COVERAGE_BOUNDARY_WEAK
  C3 at 69.37°S is outside our 80-90°S coverage grid
  System recommends 85-90°S (scientifically correct)
  Nearest recommended site: 526km from C3
  Scientific interpretation: system prioritises
  extreme polar science targets over sub-polar
  technology demonstration sites
  Outputs: chandrayaan3_validation.txt + .html
- Artemis III validation ✅ (added to chandrayaan3_validation.py)
  Shackleton Ridge: SAFE_LANDING, final=0.603 ✅ (NASA #1 target)
  Faustini Crater: safety=0.000, mission=0.643 ✅ (correct)
  Haworth Edge: RISKY_LANDING, final=0.505 (marginal, correct)
  Nobile Rim: TRAVERSE_CORRIDOR, final=0.501 (marginal, correct)
  Strong alignment with NASA mission planning consensus
  Goes into paper as Table 3
```


---

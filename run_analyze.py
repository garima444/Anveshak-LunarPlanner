"""Quick end-to-end test of /analyze endpoint."""
import json, time, requests

payload = {
    "rover_name": "Pragyan",
    "mission_name": "Test Mission",
    "agency": "ISRO",
    "mission_type": "geological",
    "battery_wh": 5000,
    "solar_panel_area_m2": 4.0,
    "max_slope_deg": 20.0,
    "abs_max_slope_deg": 25.0,
    "min_flat_radius_m": 300.0,
    "speed_ms": 0.01,
    "wheel_radius_m": 0.26,
    "rover_mass_kg": 26.0,
    "mission_day": 14,
    "mission_duration_days": 14,
    "dem_region": "south_pole_80_90",
    "n_results": 3,
    "target_lat": -89.0,
    "target_lon": 0.0,
    "science_experiments": ["geomorphology"],
}

print("Sending /analyze request ... (this may take 60-120 s for terrain load)")
t0 = time.time()
try:
    r = requests.post("http://127.0.0.1:8000/analyze", json=payload, timeout=300)
    elapsed = time.time() - t0
    print(f"Status: {r.status_code}  ({elapsed:.1f}s)")
    if r.status_code == 200:
        d = r.json()
        print(f"top_sites:       {len(d.get('top_sites', []))}")
        for i, s in enumerate(d.get('top_sites', [])[:3], 1):
            print(f"  #{i}: lat={s['lat']:.3f} lon={s['lon']:.3f} safety={s['safety_score']:.3f} final={s['final_score']:.3f}")
        print(f"map_html chars:  {len(d.get('map_html',''))}")
        print(f"chart_html chars:{len(d.get('chart_html',''))}")
        ms = d.get('mission_summary', '')
        print(f"mission_summary: {ms[:120]}")
        ps = d.get('path_stats', {})
        print(f"path_stats keys: {list(ps.keys())}")
        with open("analyze_result.json", "w") as f:
            json.dump({k: v for k, v in d.items() if k not in ('map_html','chart_html')}, f, indent=2)
        print("Saved analyze_result.json (without HTML blobs)")
    else:
        print("ERROR body:", r.text[:500])
except Exception as e:
    elapsed = time.time() - t0
    print(f"EXCEPTION after {elapsed:.1f}s: {e}")

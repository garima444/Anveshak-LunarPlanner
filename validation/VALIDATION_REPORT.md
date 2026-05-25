# Anveshak Validation Report
**Generated**: 2026-05-23 10:43 UTC
**Overall**: 8/14 PASS · 3 WARN · 2 FAIL · 1 SKIP
**Status**: 2 FAILURE(S)

---
## Executive Summary
| # | Test | Result | Key Metric |
|---|------|--------|------------|
| 1 | Chandrayaan-3 Landing Site Validation | ⏭️ SKIP | Failed to load region 'south_pole_75_90': Unable to allocate 394. MiB for an array with shape (10163, 10165) and data... |
| 2 | Artemis 3 Candidate Landing Regions Validation | ❌ FAIL | Exception: Unable to allocate 392. MiB for an array with shape (10133, 10133) and data type float32
Traceback (most r... |
| 3 | Scoring Weight Sensitivity Analysis | ⚠️ WARN | avg overlap=7.29/10, avg Spearman=0.9998. Spearman=0.9998: terrain-driven stability — top-10 sites span only 1.6° slo... |
| 4 | DBSCAN Parameter Validation — k-Distance Elbow Method | ✅ PASS | |suggested_eps - current_eps| = 0.0041 (pass <= 0.20). Clusters: current=7, suggested=7. Silhouette: current=0.218053... |
| 5 | Random Forest Classifier 5-Fold Cross-Validation | ✅ PASS | Mean accuracy=0.9977 ± 0.0004. Per-class F1 pass=True. Top features: ['slope_norm', 'local_mean_slope', 'roughness_no... |
| 6 | A* Pathfinder Validation | ✅ PASS | Sub-tests: 6a=PASS, 6b=PASS, 6c=PASS, 6d=PASS, 6e=PASS, 6f=PASS |
| 7 | Energy Model Validation | ✅ PASS | Sub-tests: 7a=PASS, 7b=PASS, 7c=PASS, 7d=PASS, 7e=PASS |
| 8 | Slope Computation Accuracy | ✅ PASS | Sub-tests: 8a=PASS, 8b=PASS, 8c=PASS, 8d=PASS, 8e=PASS, 8f=PASS |
| 9 | Roughness Computation Accuracy | ✅ PASS | Sub-tests: 9a=PASS, 9b=PASS, 9c=PASS, 9d=PASS |
| 10 | End-to-End Pipeline Smoke Test | ⚠️ WARN | Stages: S1=PASS, S2=PASS, S3=PASS, S4=PASS. Warnings: ['Worst top-site score 0.406 < passable mean 0.505 — ML refinem... |
| 11 | Historical & Planned Lunar Mission Validation | ⚠️ WARN | 2/3 missions MISSION_VALIDATED (traverse distance within 30% of published + goal in confirmed PSR >= 70%). Site predi... |
| 12 | Ancillary Layers Integrity | ❌ FAIL | Sub-tests: 12a_illumination=PASS, 12b_psr_mask=PASS, 12c_earth_visibility=PASS, 12d_psr_safety=FAIL, 12e_solar_rtg=FA... |
| 13 | Real DEM Terrain Sanity | ✅ PASS | DEM 10133×10133 px @ 60m/px. 13a_slope_dist=PASS, 13b_roughness_slope_corr=PASS, 13c_elevation_range=PASS, 13d_nan_fr... |
| 14 | Bekker-Wong Terramechanics Validation | ✅ PASS |  |

---

## Per-Test Details

### Test 1: Chandrayaan-3 Landing Site Validation — ⏭️ SKIP

**lat**: -69.373

**lon**: 32.348

**region**: south_pole_75_90

**skip_reason**: Failed to load region 'south_pole_75_90': Unable to allocate 394. MiB for an array with shape (10163, 10165) and data type float32

**_runtime_s**: 44.64

> **Notes**: Failed to load region 'south_pole_75_90': Unable to allocate 394. MiB for an array with shape (10163, 10165) and data type float32


### Test 2: Artemis 3 Candidate Landing Regions Validation — ❌ FAIL

**_runtime_s**: 314.71

> **Notes**: Exception: Unable to allocate 392. MiB for an array with shape (10133, 10133) and data type float32
Traceback (most recent call last):
  File "Z:\Anveshak\validation\test_artemis3.py", line 71, in run
    safety_score, mission_score, final_score, top_sites = score_terrain(
                                                          ~~~~~~~~~~~~~^
        elevation, slope, roughness, profile, ROVER_PROFILE
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "Z:\Anveshak\core\landing_scorer.py", line 1038, in score_terrain
    safety = _compute_safety_score(
        elevation, slope, roughness, quality_mask,
    ...<2 lines>...
        mobility_risk_map=mobility_risk_map,
    )
  File "Z:\Anveshak\core\landing_scorer.py", line 142, in _compute_safety_score
    np.float32(1.0) + np.exp(np.float32(8.0) * (slope_ratio - np.float32(0.75)))
                             ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
numpy._core._exceptions._ArrayMemoryError: Unable to allocate 392. MiB for an array with shape (10133, 10133) and data type float32



### Test 3: Scoring Weight Sensitivity Analysis — ⚠️ WARN

**crop_size**: [3000, 3000]

**baseline_top10_pixels**: [(657, 2181), (1051, 203), (763, 2167), (1067, 151), (681, 626), (960, 198), (1488, 2820), (2551, 2146), (2298, 254), (818, 2032)]

**per_variant**:
- `VARIANT_1`: {'weights': [0.45, 0.25, 0.2, 0.05, 0.05], 'top10_overlap_with_baseline': 7, 'spearman_correlation': 0.999821, 'top10_pixels': [(657, 2180), (681, 626), (1051, 203), (763, 2167), (180, 1350), (960, 198), (1311, 2799), (1488, 2820), (1067, 151), (2303, 910)]}
- `VARIANT_2`: {'weights': [0.25, 0.35, 0.2, 0.05, 0.15], 'top10_overlap_with_baseline': 9, 'spearman_correlation': 0.999766, 'top10_pixels': [(657, 2180), (1051, 203), (763, 2167), (1067, 151), (681, 626), (960, 198), (1488, 2820), (2298, 254), (818, 2032), (180, 1350)]}
- `VARIANT_3`: {'weights': [0.35, 0.25, 0.3, 0.05, 0.05], 'top10_overlap_with_baseline': 7, 'spearman_correlation': 0.999853, 'top10_pixels': [(681, 626), (657, 2180), (1051, 203), (763, 2167), (180, 1350), (960, 198), (1488, 2820), (1311, 2799), (1067, 151), (2303, 910)]}
- `VARIANT_4`: {'weights': [0.35, 0.15, 0.2, 0.15, 0.15], 'top10_overlap_with_baseline': 5, 'spearman_correlation': 0.999836, 'top10_pixels': [(659, 2224), (324, 1865), (1051, 203), (1482, 2504), (2565, 2365), (967, 179), (966, 431), (763, 2167), (1067, 151), (204, 2138)]}
- `VARIANT_5`: {'weights': [0.45, 0.25, 0.1, 0.05, 0.15], 'top10_overlap_with_baseline': 9, 'spearman_correlation': 0.999971, 'top10_pixels': [(657, 2181), (1051, 203), (1067, 151), (763, 2167), (960, 198), (2551, 2146), (2298, 254), (681, 626), (1488, 2820), (180, 1350)]}
- `VARIANT_6`: {'weights': [0.35, 0.35, 0.1, 0.05, 0.15], 'top10_overlap_with_baseline': 9, 'spearman_correlation': 0.999937, 'top10_pixels': [(657, 2181), (1051, 203), (763, 2167), (1067, 151), (681, 626), (960, 198), (1488, 2820), (2298, 254), (818, 2032), (180, 1350)]}
- `VARIANT_7`: {'weights': [0.25, 0.25, 0.2, 0.05, 0.25], 'top10_overlap_with_baseline': 5, 'spearman_correlation': 0.999661, 'top10_pixels': [(659, 2224), (1051, 203), (1067, 151), (1482, 2504), (324, 1865), (204, 2138), (967, 179), (763, 2167), (2565, 2365), (2413, 1832)]}

**average_overlap**: 7.2857

**average_spearman_correlation**: 0.999835

**spearman_diagnosis**: Spearman=0.9998: terrain-driven stability — top-10 sites span only 1.6° slope (all essentially flat); slope-weight saturation is expected correct behaviour near the south pole.

**_runtime_s**: 107.65

> **Notes**: avg overlap=7.29/10, avg Spearman=0.9998. Spearman=0.9998: terrain-driven stability — top-10 sites span only 1.6° slope (all essentially flat); slope-weight saturation is expected correct behaviour near the south pole.


### Test 4: DBSCAN Parameter Validation — k-Distance Elbow Method — ✅ PASS

**n_samples**: 20000

**current_eps**: 0.18

**suggested_eps**: 0.184114

**eps_difference**: 0.004114

**elbow_index**: 1761

**clusters_at_current_eps**: 7

**clusters_at_suggested_eps**: 7

**cluster_sizes_current_eps**:
- `0`: 18695
- `1`: 10
- `2`: 20
- `3`: 9
- `4`: 14
- `5`: 10
- `6`: 10

**cluster_sizes_suggested_eps**:
- `0`: 18754
- `1`: 13
- `2`: 16
- `3`: 21
- `4`: 10
- `5`: 8
- `6`: 10

**silhouette_current_eps**: 0.2181

**silhouette_suggested_eps**: 0.2145

**_runtime_s**: 109.66

> **Notes**: |suggested_eps - current_eps| = 0.0041 (pass <= 0.20). Clusters: current=7, suggested=7. Silhouette: current=0.21805386245250702, suggested=0.2145163118839264.


### Test 5: Random Forest Classifier 5-Fold Cross-Validation — ✅ PASS

**n_samples**: 50000

**class_sample_counts**:
- `HAZARD_ZONE`: 11215
- `RISKY_LANDING`: 17635
- `TRAVERSE_CORRIDOR`: 9001
- `SAFE_LANDING`: 12149
- `SCIENCE_TARGET`: 0

**fold_accuracies**: [0.9977, 0.997, 0.9977, 0.9983, 0.9979]

**mean_accuracy**: 0.99772

**std_accuracy**: 0.000421

**fold_f1_scores**: [[1.0, 0.996735273243435, 0.9994450610432852, 0.99568345323741, 0.0], [0.9997770345596433, 0.9960193346602217, 0.9980571745767416, 0.995079950799508, 0.0], [1.0, 0.9971623155505108, 0.9988882712618121, 0.995480690221857, 0.0], [1.0, 0.9978702257560699, 0.9994447529150472, 0.9965085233107415, 0.0], [1.0, 0.9973053467593249, 0.9991664351208669, 0.9958881578947368, 0.0]]

**per_class_f1**:
- `HAZARD_ZONE`: {'mean': 0.9999554069119286, 'std': 8.918617614268599e-05}
- `RISKY_LANDING`: {'mean': 0.9970184991939126, 'std': 0.0006175677309092498}
- `TRAVERSE_CORRIDOR`: {'mean': 0.9990003389835506, 'std': 0.000514779108410843}
- `SAFE_LANDING`: {'mean': 0.9957281550928506, 'std': 0.00047285967818564307}
- `SCIENCE_TARGET`: {'mean': 0.0, 'std': 0.0}

**per_class_f1_pass**: True

**low_f1_classes**: []

**fold_confusion_matrices**: [[[2243, 0, 0, 0, 0], [0, 3511, 2, 14, 0], [0, 0, 1801, 0, 0], [0, 7, 0, 2422, 0], [0, 0, 0, 0, 0]], [[2242, 1, 0, 0, 0], [0, 3503, 5, 19, 0], [0, 0, 1798, 2, 0], [0, 3, 0, 2427, 0], [0, 0, 0, 0, 0]], [[2243, 0, 0, 0, 0], [0, 3514, 1, 12, 0], [0, 0, 1797, 3, 0], [0, 7, 0, 2423, 0], [0, 0, 0, 0, 0]], [[2243, 0, 0, 0, 0], [0, 3514, 0, 13, 0], [0, 0, 1800, 0, 0], [0, 2, 2, 2426, 0], [0, 0, 0, 0, 0]], [[2243, 0, 0, 0, 0], [0, 3516, 0, 11, 0], [0, 1, 1798, 1, 0], [0, 7, 1, 2422, 0], [0, 0, 0, 0, 0]]]

**feature_importances**:
- `elevation_norm`: 0.075156
- `slope_norm`: 0.277863
- `roughness_norm`: 0.196049
- `quality_mask`: 0.0
- `local_mean_slope`: 0.228928
- `local_std_elevation`: 0.165704
- `slope_gradient`: 0.039138
- `lat_normalized`: 0.017161

**top3_features**: ['slope_norm', 'local_mean_slope', 'roughness_norm']

**_runtime_s**: 43.93

> **Notes**: Mean accuracy=0.9977 ± 0.0004. Per-class F1 pass=True. Top features: ['slope_norm', 'local_mean_slope', 'roughness_norm']


### Test 6: A* Pathfinder Validation — ✅ PASS

**sub_results**:
- `6a`: {'path_length': 33, 'all_in_bounds': True, 'all_passable': True, 'result': 'PASS', 'notes': 'len=33, all_in_bounds=True, all_passable=True'}
- `6b`: {'path_is_none': True, 'stats_is_none': True, 'result': 'PASS', 'notes': 'path=None, stats=None'}
- `6c`: {'path_returned': True, 'total_distance_m': 0.0, 'result': 'PASS', 'notes': 'No crash, distance=0.00m'}
- `6d`: {'total_distance_m': 8400.43, 'expected_distance_m': 8400.43, 'pct_error': 0.0, 'estimated_time_hrs': 16.8009, 'max_slope_deg': 5.0, 'mean_slope_deg': 5.0, 'result': 'PASS', 'notes': 'dist=8400.4m, expected≈8400.4m, err=0.00%'}
- `6e`: {'path': [[0, 0], [1, 1], [2, 2]], 'total_distance_m': 169.7056, 'expected_distance_m': 169.7056, 'pct_error': 0.0, 'result': 'PASS', 'notes': 'dist=169.7056m, expected=169.7056m, err=0.0000%'}
- `6f`: {'max_col_used': 0, 'stayed_in_shallow_corridor': True, 'max_slope_on_path_deg': 5.0, 'result': 'PASS', 'notes': 'max_col=0 (shallow zone: col<10), max_slope_on_path=5.0°. Proves slope is used in A* cost function.'}

**_runtime_s**: 0.23

> **Notes**: Sub-tests: 6a=PASS, 6b=PASS, 6c=PASS, 6d=PASS, 6e=PASS, 6f=PASS


### Test 7: Energy Model Validation — ✅ PASS

**sub_results**:
- `7a`: {'n_steps': 50, 'actual_energy_wh': 600.0, 'expected_energy_wh': 600.0, 'pct_error': 0.0, 'result': 'PASS', 'notes': 'actual=600.0000 Wh, expected=600.0000 Wh, err=0.0000%'}
- `7b`: {'flat_energy_wh': 120.0, 'uphill_energy_wh': 182.5133, 'actual_ratio': 1.5209, 'expected_ratio': 1.5209, 'pct_error': 0.0, 'result': 'PASS', 'notes': 'ratio=1.5209, expected=1.5209, err=0.00%'}
- `7c`: {'downhill_regen_wh': 9.3175, 'downhill_total_wh': 110.6825, 'flat_baseline_wh': 120.0, 'regen_positive': True, 'downhill_cheaper_than_flat': True, 'regen_fraction_model': 0.3, 'result': 'PASS', 'notes': 'regen=9.3175 Wh, down=110.6825 Wh < flat=120.0000 Wh. REGEN_FRACTION=0.30 (physical bounds: 0.40-0.85 is ideal; current model uses 0.30 — may be conservative).'}
- `7d`: {'energy_10steps_wh': 120.0, 'energy_20steps_wh': 240.0, 'ratio': 2.0, 'pct_error': 0.0, 'result': 'PASS', 'notes': 'ratio=2.0000, expected=2.0, err=0.0000%'}
- `7e`: {'low_pct': 36.0, 'low_risk': 'LOW', 'mod_pct': 60.0, 'mod_risk': 'MODERATE', 'high_pct': 96.0, 'high_risk': 'HIGH', 'result': 'PASS', 'notes': 'LOW=LOW/36.0%, MOD=MODERATE/60.0%, HIGH=HIGH/96.0%'}

**base_power_reference**: BASE_POWER_W=100.0 W (VIPER ref: ~100-130 W, Artemis ref: ~200 W)

**_runtime_s**: 0.02

> **Notes**: Sub-tests: 7a=PASS, 7b=PASS, 7c=PASS, 7d=PASS, 7e=PASS


### Test 8: Slope Computation Accuracy — ✅ PASS

**sub_results**:
- `8a`: {'max_interior_slope_deg': 0.0, 'tolerance_deg': 0.001, 'result': 'PASS', 'notes': 'max_slope=0.000000°, tolerance=0.001°'}
- `8b`: {'mean_interior_slope_deg': 45.0, 'expected_deg': 45.0, 'pct_error': 0.0, 'result': 'PASS', 'notes': 'mean_slope=45.0000°, expected=45.0°, err=0.0000%'}
- `8c`: {'mean_interior_slope_deg': 30.0, 'expected_deg': 30.0, 'abs_error_deg': 0.0, 'result': 'PASS', 'notes': 'mean_slope=30.0000°, expected=30.0°'}
- `8d`: {'mean_interior_slope_deg': 20.0, 'expected_deg': 20.0, 'abs_error_deg': 0.0, 'result': 'PASS', 'notes': 'mean_slope=20.0000°, expected=20.0°'}
- `8e`: {'slope_at_adjacent_49_50': None, 'adjacent_pixel_is_nan': True, 'slope_at_far_pixel_48_48_deg': 0.0, 'far_pixel_near_zero': True, 'result': 'PASS', 'notes': 'slope[49,50]=NaNdeg (adj to NaN), slope[48,48]=0.0000deg'}
- `8f`: {'slope_at_adjacent_0_1': None, 'adjacent_pixel_is_nan': True, 'slope_at_interior_5_5_deg': 0.0, 'interior_near_zero': True, 'result': 'PASS', 'notes': 'slope[0,1]=NaNdeg, interior[5,5]=0.0000deg'}

**_runtime_s**: 0.02

> **Notes**: Sub-tests: 8a=PASS, 8b=PASS, 8c=PASS, 8d=PASS, 8e=PASS, 8f=PASS


### Test 9: Roughness Computation Accuracy — ✅ PASS

**sub_results**:
- `9a`: {'max_roughness_m': 0.0, 'tolerance_m': 0.01, 'result': 'PASS', 'notes': 'max_roughness=0.000000m, tolerance=0.01m'}
- `9b`: {'mean_interior_roughness_m': 49.6904, 'min_interior_roughness_m': 49.6904, 'max_interior_roughness_m': 49.6904, 'theoretical_std_m': 49.6904, 'expected_range_m': [42.2, 57.1], 'roughness_window_size': 3, 'result': 'PASS', 'notes': 'mean_rough=49.6904m, expected in [42.2,57.1] (±15% of theoretical 49.7m)'}
- `9c`: {'nan_pixels_have_nan_roughness': True, 'sample_far_pixel': [0, 2], 'far_roughness_m': 0.0, 'far_pixel_near_zero': True, 'result': 'PASS', 'notes': 'NaN preserved=True, far_rough=0.0000m'}
- `9d`: {'patch_gradients': [0.0, 0.05, 0.1, 0.15, 0.2], 'mean_slopes_deg': [0.0, 2.8624, 5.7106, 8.5308, 11.3099], 'mean_roughness_m': [0.0, 2.4495, 4.899, 7.3485, 9.798], 'pearson_r': 1.0, 'result': 'PASS', 'notes': 'Pearson r=1.0000 between mean slope and mean roughness across 5 patches (expected >= 0.80)'}

**_runtime_s**: 0.25

> **Notes**: Sub-tests: 9a=PASS, 9b=PASS, 9c=PASS, 9d=PASS


### Test 10: End-to-End Pipeline Smoke Test — ⚠️ WARN

**checks**: {'terrain_shape': [300, 300], 'score_terrain_time_s': 0.757, 'safety_range': [0.0, 0.851], 'mission_range': [0.0, 0.9997], 'final_range': [0.0, 0.7015], 'final_score_std': 0.0999, 'impassable_safety_zero': True, 'mean_passable_score': 0.5047, 'worst_top_site_score': 0.4063, 'top_sites_above_mean': True, 'n_top_sites': 7, 'stage1': 'PASS', 'stage2': 'PASS', 'find_path_time_s': 0.055, 'path_length': 56, 'path_distance_m': 3623.09, 'site_separation_m': 3390.9, 'battery_feasible': True, 'battery_pct': 69.6, 'stage3': 'PASS', 'detect_anomalies_time_s': 2.825, 'n_anomalies': 19, 'stage4': 'PASS'}

**warnings**: ['Worst top-site score 0.406 < passable mean 0.505 — ML refinement may be over-penalising synthetic terrain; expected on non-real DEM runs.']

**failures**: []

**_runtime_s**: 7.99

> **Notes**: Stages: S1=PASS, S2=PASS, S3=PASS, S4=PASS. Warnings: ['Worst top-site score 0.406 < passable mean 0.505 — ML refinement may be over-penalising synthetic terrain; expected on non-real DEM runs.']


### Test 11: Historical & Planned Lunar Mission Validation — ⚠️ WARN

**missions**: [{'name': 'VIPER', 'agency': 'NASA', 'year': 2024, 'status_field': 'cancelled', 'psr_required': True, 'start_pixel': [7770, 4413], 'goal_pixel': [7574, 4460], 'path_status': 'FOUND', 'published_traverse_km': 20.0, 'computed_km': 13.501, 'time_hrs': 16.877, 'max_slope_deg': 9.06, 'mean_slope_deg': 4.29, 'energy_wh': 1710.7, 'battery_pct_used': 380.15, 'energy_risk': 'HIGH', 'battery_feasible': False, 'DISTANCE_VALIDATED': False, 'PSR_TARGET_CONFIRMED': False, 'MISSION_VALIDATED': False, 'landing_final_score': None, 'landing_percentile': None, 'LANDING_SITE_PREDICTED': None, 'dest_mission_score': None, 'dest_percentile': None, 'DESTINATION_PREDICTED': None, 'SITE_PREDICTION_VALIDATED': None}, {'name': "Chang'e-7", 'agency': 'CNSA', 'year': 2026, 'status_field': 'planned', 'psr_required': True, 'start_pixel': [4056, 5067], 'goal_pixel': [4055, 5067], 'path_status': 'FOUND', 'published_traverse_km': None, 'computed_km': 0.06, 'time_hrs': 0.12, 'max_slope_deg': 15.37, 'mean_slope_deg': 15.29, 'energy_wh': 11.06, 'battery_pct_used': 2.21, 'energy_risk': 'LOW', 'battery_feasible': True, 'DISTANCE_VALIDATED': None, 'PSR_TARGET_CONFIRMED': True, 'MISSION_VALIDATED': True, 'landing_final_score': None, 'landing_percentile': None, 'LANDING_SITE_PREDICTED': None, 'dest_mission_score': None, 'dest_percentile': None, 'DESTINATION_PREDICTED': None, 'SITE_PREDICTION_VALIDATED': None}, {'name': 'Artemis III', 'agency': 'NASA', 'year': 2026, 'status_field': 'planned', 'psr_required': False, 'start_pixel': [4814, 5067], 'goal_pixel': [4763, 5067], 'path_status': 'FOUND', 'published_traverse_km': 5.0, 'computed_km': 3.507, 'time_hrs': 2.338, 'max_slope_deg': 14.59, 'mean_slope_deg': 9.16, 'energy_wh': 236.56, 'battery_pct_used': 11.83, 'energy_risk': 'LOW', 'battery_feasible': True, 'DISTANCE_VALIDATED': True, 'PSR_TARGET_CONFIRMED': None, 'MISSION_VALIDATED': True, 'landing_final_score': None, 'landing_percentile': None, 'LANDING_SITE_PREDICTED': None, 'dest_mission_score': None, 'dest_percentile': None, 'DESTINATION_PREDICTED': None, 'SITE_PREDICTION_VALIDATED': None}]

**n_missions_validated**: 2

**n_predictions_validated**: 0

**landmarks**:
- `LCROSS_Cabeus`: {'pixel': [3298, 3053], 'in_bounds': True, 'LCROSS_VALIDATED': None, 'note': 'Part 2 score_terrain not available (OOM) — landmark check skipped.'}

**lcross_validated**: False

**pct70_final_threshold**: 1.0

**pct70_mission_threshold**: 1.0

**html_output**: Z:\Anveshak\outputs\historical_mission_validation.html

**_runtime_s**: 203.55

> **Notes**: 2/3 missions MISSION_VALIDATED (traverse distance within 30% of published + goal in confirmed PSR >= 70%). Site prediction skipped (OOM on full DEM). Site prediction skipped: out-of-memory during score_terrain (Unable to allocate 392. MiB for an array with shape (10133, 10133) and data type float32). The Random Forest classifier requires ~155 MB for the 10133×10133 DEM — increase system RAM or run on a downsampled DEM to enable this test. LCROSS Cabeus landmark: NOT VALIDATED. Verdict: WARN.


### Test 12: Ancillary Layers Integrity — ❌ FAIL

**checks**:
- `12a_illum_range`: [0.0, 0.9515]
- `12a_illum_shape`: [10133, 10133]
- `12a_coverage_frac`: 1.0
- `12a_illumination`: PASS
- `12b_psr_shape`: [10133, 10133]
- `12b_intermediate_frac`: 0.0
- `12b_psr_coverage_frac`: 0.0569
- `12b_psr_mask`: PASS
- `12c_earth_range`: [0.0, 1.0]
- `12c_earth_visibility`: PASS
- `12d_psr_safety`: FAIL
- `12e_solar_rtg`: FAIL

**warnings**: []

**failures**: ['12d: Unable to allocate 30.5 MiB for an array with shape (1000000, 1, 4) and data type float64', '12e: Unable to allocate 30.5 MiB for an array with shape (1000000, 1, 4) and data type float64']

**_runtime_s**: 274.45

> **Notes**: Sub-tests: 12a_illumination=PASS, 12b_psr_mask=PASS, 12c_earth_visibility=PASS, 12d_psr_safety=FAIL, 12e_solar_rtg=FAIL. Failures: ['12d: Unable to allocate 30.5 MiB for an array with shape (1000000, 1, 4) and data type float64', '12e: Unable to allocate 30.5 MiB for an array with shape (1000000, 1, 4) and data type float64']


### Test 13: Real DEM Terrain Sanity — ✅ PASS

**checks**: {'dem_shape': [10133, 10133], 'resolution_m': 60.0, 'total_pixels': 102677689, 'finite_pixels': 102672334, 'nan_fraction': 0.0001, '13a_pct_below_35deg': 99.99, '13a_slope_p50': 8.056, '13a_slope_p95': 21.639, '13a_slope_dist': 'PASS', '13b_roughness_slope_pearson_r': 0.6724, '13b_roughness_slope_corr': 'PASS', '13c_elevation_min_m': -7296.5, '13c_elevation_max_m': 7026.5, '13c_elevation_mean_m': -1500.5, '13c_elevation_range': 'PASS', '13d_nan_frac_pct': 0.01, '13d_nan_fraction': 'PASS', '13e_isolated_nan_count': 4952, '13e_isolated_nan_frac': 4.8e-05, '13e_nan_islands': 'PASS'}

**warnings**: []

**failures**: []

**_runtime_s**: 85.47

> **Notes**: DEM 10133×10133 px @ 60m/px. 13a_slope_dist=PASS, 13b_roughness_slope_corr=PASS, 13c_elevation_range=PASS, 13d_nan_fraction=PASS, 13e_nan_islands=PASS


### Test 14: Bekker-Wong Terramechanics Validation — ✅ PASS

**sub_results**:
- `12a`: {'sinkage_mm': 6.269, 'range': '2-15 mm', 'passed': True}
- `12b`: {'soft_indices': [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], 'sinkage_mm': [6.269, 6.826, 7.525, 8.437, 9.686, 11.531], 'monotone': True, 'passed': True}
- `12c`: {'mu_r_nominal': 0.07465, 'mu_r_soft': 0.09279, 'passed': True}
- `12d`: {'shape': [100, 100], 'min': 0.05015, 'max': 0.0707, 'bounded': True, 'correct_shape': True, 'passed': True}
- `12e`: {'risk_flat_terrain': 0.05015, 'risk_in_depression': 0.0597, 'depression_riskier': True, 'passed': True}
- `12f`: {'pragyan_sinkage_mm': 3.575, 'viper_sinkage_mm': 6.269, 'passed': True}
- `12g`: {'STUCK_SINKAGE_FRACTION': 0.5, 'passed': True}

**failures**: []

**n_pass**: 7

**n_total**: 7

**_runtime_s**: 0.48

---

## Limitations

- Test 1 (Chandrayaan-3 at 69.373°S) loads the 65–80°S DEM region independently. It will SKIP if LDEM_75S_30MPP_ADJ.tiff is missing from data/dem/.
- Classifier CV (Test 5) uses synthetic terrain (300×300) rather than the full NASA DEM to keep runtime under 2 minutes.
- Sensitivity analysis (Test 3) Spearman ≥ 0.999 is diagnosed as terrain-driven (all top sites are flat) vs slope dominance (varied slopes). See spearman_diagnosis field.
- Historical mission Test 11 uses 30% distance tolerance and 70% PSR confidence threshold. LCROSS Cabeus landmark check requires score_terrain to succeed (may be skipped on OOM).
- Energy model (Test 7) has no sensor-noise model — all slopes and elevations are exact synthetic values. BASE_POWER_W=100W (compare: VIPER ~100-130W, Artemis rover ~200W).
- No multi-session repeatability testing; all tests run once with deterministic seeds.
- Roughness-slope correlation (Test 9d) uses linear gradient patches; real crater terrain has non-linear roughness profiles not covered by this synthetic test.
- Diviner cold-trap temperature layer is a coarse RGB display image (~8 km/px). Science proxy (PSR+elevation) remains the primary ice-stability indicator at 60m scale.
- M3 OH-band not loaded (near-zero coverage below 80°S). DEM elevation-gradient proxy is used for mineralogy science maps.
- Crater density not loaded. Run scripts/generate_crater_density.py after downloading Robbins 2019 catalog from https://zenodo.org/record/3528686.


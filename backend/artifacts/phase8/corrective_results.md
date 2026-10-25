# SLA Guardian: Phase 8 Corrective Benchmark Results

- **Generated At:** 2026-10-23 13:11:28 UTC
- **Control Interval:** 100 ms Macro-Control Interval (MacroControlAdapter, 10 sub-steps/interval)
- **Frozen PPO Checkpoint SHA-256:** `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`
- **Candidate PPO Checkpoint SHA-256:** `ec903788b569e7c5ac612692e3979f4e8a6b90e2d8b7e2765e995c902ccc19bc`
- **Scenarios:** 5 (`normal, embb_surge, urllc_burst, murllc_storm, mixed_stress`)
- **Seeds per Scenario:** [42, 101, 202] (4 policies x 5 scenarios x 3 seeds = 60 trials)
- **Simulated Duration per Trial:** 5.0 seconds (50 macro-steps x 100 ms)

## Mean Performance Across Evaluated Scenarios

| Scenario | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Critical Cost | Churn (L1) | Breach Ratio |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| normal | Static | 27.71 | 50.60 | 0.6191 | 1.0000 | 0.9995 | 0.0003 | 0.0 | 1.00 |
| normal | Heuristic | 41.12 | 63.75 | 0.9152 | 0.9992 | 0.9831 | 0.0086 | 762.0 | 1.00 |
| normal | Frozen PPO | 38.88 | 61.58 | 0.8658 | 0.9999 | 0.9876 | 0.0060 | 43.7 | 1.00 |
| normal | **Candidate PPO** | 30.30 | 52.99 | 0.6771 | 1.0000 | 0.9870 | 0.0063 | 65.1 | 1.00 |
| embb_surge | Static | 24.01 | 46.99 | 0.2839 | 1.0000 | 0.9996 | 0.0002 | 0.0 | 1.00 |
| embb_surge | Heuristic | 40.82 | 62.83 | 0.4823 | 0.9977 | 0.9393 | 0.0304 | 272.2 | 1.00 |
| embb_surge | Frozen PPO | 34.29 | 56.99 | 0.4052 | 0.9998 | 0.9831 | 0.0083 | 34.0 | 1.00 |
| embb_surge | **Candidate PPO** | 27.01 | 49.67 | 0.3193 | 1.0000 | 0.9798 | 0.0097 | 68.0 | 1.00 |
| urllc_burst | Static | 27.83 | 68.68 | 0.6241 | 0.8107 | 0.9998 | 0.1531 | 0.0 | 1.00 |
| urllc_burst | Heuristic | 30.38 | 72.23 | 0.6808 | 0.8613 | 0.9612 | 0.1196 | 1497.6 | 1.00 |
| urllc_burst | Frozen PPO | 38.97 | 77.56 | 0.8705 | 0.7480 | 0.9853 | 0.2065 | 41.3 | 1.00 |
| urllc_burst | **Candidate PPO** | 30.67 | 72.62 | 0.6875 | 0.8529 | 0.9836 | 0.1221 | 66.3 | 1.00 |
| murllc_storm | Static | 27.81 | 55.39 | 0.6241 | 1.0000 | 0.4385 | 0.4117 | 0.0 | 1.00 |
| murllc_storm | Heuristic | 23.16 | 64.90 | 0.5199 | 0.9976 | 0.7553 | 0.1802 | 634.9 | 1.00 |
| murllc_storm | Frozen PPO | 39.17 | 61.72 | 0.8760 | 0.9998 | 0.3259 | 0.4942 | 39.3 | 1.00 |
| murllc_storm | **Candidate PPO** | 30.33 | 54.42 | 0.6805 | 1.0000 | 0.3605 | 0.4689 | 68.6 | 1.00 |
| mixed_stress | Static | 24.32 | 67.25 | 0.3076 | 0.8909 | 0.5922 | 0.2311 | 0.0 | 1.00 |
| mixed_stress | Heuristic | 29.71 | 70.50 | 0.3756 | 0.8417 | 0.5664 | 0.2706 | 694.6 | 1.00 |
| mixed_stress | Frozen PPO | 35.07 | 70.87 | 0.4434 | 0.8451 | 0.4209 | 0.3280 | 30.0 | 1.00 |
| mixed_stress | **Candidate PPO** | 27.31 | 66.16 | 0.3452 | 0.9289 | 0.4482 | 0.2677 | 65.7 | 1.00 |

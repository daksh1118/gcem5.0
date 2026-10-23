# 5G Slicing Demo: Full Build Guide

Audience: the Antigravity coding agent and the two team members. Read this whole file before writing code. Time budget: 12 hours. Target: a small, laptop-friendly demo.

## 0. Definition of Done (check at the end)

- [ ] `python sim_selftest.py` passes
- [ ] `python train.py` finishes in under 15 minutes on a laptop CPU and saves `models/agent.zip`
- [ ] `python evaluate.py` prints and saves a table comparing Static, Heuristic and Agent on 4 scenarios
- [ ] `uvicorn api:app` starts, and `static/index.html` shows 3 live side-by-side panels plus a Trigger Spike button
- [ ] During a spike, the Static panel shows URLLC violations and the Agent panel keeps them at or below the SLA
- [ ] README contains the architecture diagram, results table and demo steps

## 1. Context: the real-world problem

5G operators sell network slices to different customers: eMBB (video, broadband), URLLC (factory robots, remote surgery, needs about 1 ms latency and 99.999% reliability) and mURLLC (massive IoT sensors, huge device count, rare bursts). Today most deployments split radio spectrum (PRBs) into fixed percentages, for example 60/25/15. Problems:

1. **Stranded capacity.** When one slice surges, it drops packets while other slices sit idle.
2. **Compute is also a bottleneck.** More radio capacity pushes more packets into the edge User Plane Function (UPF). If CPU is not scaled with it, packets queue in CPU buffers and SLAs break even though the radio is free.
3. **URLLC vs eMBB conflict.** Permanently reserving radio for URLLC wastes spectrum; preempting eMBB hurts broadband throughput.
4. **Average-reward RL is unsafe.** Standard RL will sacrifice rare URLLC packets to gain eMBB throughput, which is unacceptable for carrier SLAs.
5. **Different timescales.** Radio scheduling runs at about 1 ms; resource orchestration at 100 ms to 1 s.

Who pays: operators (SLA penalty fees, wasted spectrum) and enterprise customers (factories, hospitals) who need guaranteed performance.

### Original problem statement (verbatim)

Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G: Develop an intelligent resource allocation system that dynamically assigns bandwidth, compute, and priority across eMBB, URLLC, and mURLLC slices in a 5G network under fluctuating demand. The solution should use reinforcement learning or optimization, be tested in a realistic network simulator, guarantee slice-level SLAs, and compare against static and heuristic baselines.

## 2. Solution overview

We build a safe-RL slicer with three ideas:

1. **Joint radio and compute allocation.** One agent sets PRB share and vCPU share per slice together.
2. **Constrained RL (CMDP, Lagrangian relaxation).** Maximize eMBB throughput subject to a cap on URLLC/mURLLC violations. A multiplier lambda grows automatically when violations exceed the cap.
3. **Safety shield plus two-level control.** A shield enforces minimum floors for URLLC/mURLLC so the SLA is guaranteed by construction. The agent acts every 100 ms step (macro tier); a simple proportional dispatcher inside the simulator stands in for the 1 ms MAC tier.

Claim wording for the pitch: 'SLA protected by a hard shield, efficiency optimized by constrained RL.' Do not claim zero delay or 100% guarantees.

### Out of scope (do NOT build)

ns-3 integration, HARQ mini-slot puncturing model, real 3GPP channel modelling, multi-cell, GPU training, user authentication, databases, Docker. These may be listed as future work in the README only.

## 3. Glossary

- **eMBB:** enhanced mobile broadband; high throughput, tolerant of some delay.
- **URLLC:** ultra-reliable low-latency communication; tiny packets, strict deadline, very high reliability.
- **mURLLC:** massive/ultra-reliable machine-type slice; many devices, occasional bursts, reliability target.
- **PRB:** physical resource block; the unit of radio capacity.
- **vCPU:** virtual CPU core at the edge UPF container.
- **SLA:** the per-slice performance promise.
- **CMDP:** constrained Markov decision process; RL with a cost constraint.
- **Lagrangian:** the method that folds the constraint into the reward using multiplier lambda.
- **Shield:** a rule layer that overrides unsafe actions before they reach the simulator.

## 4. Architecture

```
traffic generators -> SliceEnv (sim.py) <-> Policy (Static | Heuristic | PPO agent, wrapped by shield)
                           |
                      api.py (FastAPI): runs 3 env copies on identical traffic
                           |  WebSocket /ws + REST
                      static/index.html (Chart.js dashboard)
```

Key rule: the three policies are evaluated on the **same random seed and traffic**, so the comparison is fair.

## 5. Tech stack (pin in requirements.txt)

- Python 3.10 or 3.11
- numpy, pandas, matplotlib
- gymnasium
- stable-baselines3 (PPO), torch (CPU build)
- fastapi, uvicorn, websockets
- pyyaml
- Frontend: plain HTML + JavaScript + Chart.js from a CDN (no build step, no npm)

Decision: FastAPI instead of Django, because WebSocket streaming is simpler and setup is lighter. Do not add other dependencies without asking.

## 6. Interface contract (the single source of truth)

All constants live in `config.yaml`. Initial values (tunable):

```yaml
steps_per_episode: 200      # 1 step = 100 ms of simulated time
prb_total: 100
vcpu_total: 8
prb_rate: 12                # packets per PRB per step
cpu_rate: 200               # packets per vCPU per step
slices: [embb, urllc, murllc]
arrival_mean: {embb: 400, urllc: 30, murllc: 20}
spike_factor: {embb: 2.5, urllc: 3.0, murllc: 7.0}
queue_max: {embb: 2000, urllc: 0, murllc: 0}   # 0 means no queue: missed deadline = violation
shield_floor: {urllc: 0.15, murllc: 0.15}
cost_limit: 0.01            # max allowed average violation rate for urllc+murllc
lagrange_lr: 0.05
```

**Gymnasium environment** `SliceEnv(config, seed)`:

- `reset(seed=None) -> (obs, info)`
- `step(action) -> (obs, reward, terminated, truncated, info)`
- `info` must contain: `cost`, `violations` per slice, `throughput` per slice, `shares` per slice, `queue` per slice, `lambda` (if set).

**Observation (12 floats, all normalized to 0..1):** for each slice in order \[embb, urllc, murllc\]: queue / queue\_max (0 for no-queue slices), smoothed load (EMA of arrivals divided by capacity), current PRB share, current vCPU share.

**Action (6 floats in -1..1):** first 3 are PRB logits, last 3 are vCPU logits. Environment applies softmax to each group of 3, then the shield, to get shares that sum to 1.

**Reward:** served eMBB packets divided by eMBB arrivals plus queue (0..1). **Cost (per step):** (urllc\_violated + murllc\_violated) divided by (urllc\_arrivals + murllc\_arrivals), 0 if no arrivals.

**Training reward:** `reward - lambda * cost`. Lambda is updated once per episode: `lambda = max(0, lambda + lagrange_lr * (episode_mean_cost - cost_limit))`.

## 7. Simulator specification (sim.py)

Per step, for each slice i:

1. **Arrivals:** eMBB \~ Poisson(mean \* spike multiplier), with random bursts (about 5% chance per step of x1.5 for 5 steps). URLLC \~ Poisson with a periodic component (sinusoid of period 20 steps, amplitude 30%). mURLLC \~ Poisson baseline plus rare bursts (about 2% chance per step of a x7 burst lasting 3 steps).
2. **Capacities:** `radio_cap_i = prb_share_i * prb_total * prb_rate`; `cpu_cap_i = vcpu_share_i * vcpu_total * cpu_rate`.
3. **Served:** `served_i = min(queue_i + arrivals_i, radio_cap_i, cpu_cap_i)`. This is the radio-compute coupling: the lower of the two limits wins.
4. **eMBB queue:** leftover is carried over up to `queue_max`; overflow is dropped.
5. **URLLC/mURLLC:** no carryover. Any packet not served in the step missed its deadline and counts as a violation: `violations_i = max(0, arrivals_i - served_i)`.
6. **Spike control:** `env.set_spike(slice, factor, duration_steps)` multiplies that slice's arrival mean for the given duration.

Keep the simulator vectorized with numpy; one episode must run in under 20 ms.

**Self test (`sim_selftest.py`):** (a) shares always sum to 1; (b) with a static 60/25/15 split and a spike, eMBB drops packets while URLLC stays idle; (c) reducing vCPU share to near zero makes served drop even with full PRB share; (d) same seed gives identical traffic.

## 8. RL and shield specification

**Shield (`shield.py`):** `apply_shield(shares_prb, shares_cpu, recent_load) -> (shares_prb, shares_cpu)`.

- For urllc and murllc: `floor_i = max(config floor, 1.2 * recent_load_i)` where recent\_load\_i is the EMA load as a fraction of capacity.
- If a share is below its floor, raise it to the floor and take the difference proportionally from eMBB (and, if still short, from the other slices above their floors).
- Apply the same logic separately to PRB and vCPU.
- Unit-test: output sums to 1, floors respected, agent cannot go below floor under any input.

**Training (`train.py`):**

- Stable-Baselines3 PPO, MlpPolicy, network 2 x 64, `n_steps=1024`, `batch_size=256`, `gamma=0.95`, `learning_rate=3e-4`.
- Total timesteps 100k to 200k. Must finish in under 15 minutes on CPU.
- Callback updates lambda at every episode end (formula in section 6) and logs lambda, episode reward and episode cost to `runs/log.csv`.
- Train with randomized spikes (random slice, factor, start time) so the policy sees surges.
- Save to `models/agent.zip`. Save a training curve plot to `results/training.png`.
- Always run training with a fixed seed and also save the best checkpoint by (cost under limit, then highest reward).

**Ablation (only if time allows after hour 9):** train a second model with lambda fixed at 0 (unconstrained PPO) and without the shield, and report its URLLC violation rate to show why the constraint matters.

## 9. Baselines (baselines.py)

Each baseline is a function `policy(obs, info) -> action` or share vectors, usable by the same env.

1. **Static:** fixed shares 60/25/15 for both PRB and vCPU, never changes.
2. **Heuristic (proportional to demand with floors):** each step, share\_i = (queue\_i + smoothed\_load\_i) normalized across slices, with the same floors as the shield for URLLC and mURLLC. Smoothing factor 0.3.

## 10. API and dashboard (api.py, static/index.html)

**Backend behavior:** on startup, load `models/agent.zip`. Run three env copies (Static, Heuristic, Agent) in a background task with identical seed and traffic, advancing about 5 steps per second.

**Endpoints:**

- `GET /health` returns `{status: ok}`
- `WS /ws` streams one JSON per step: `{step, scenario, policies: {static: {...}, heuristic: {...}, agent: {...}}}` where each policy block holds `throughput`, `violations`, `violation_rate`, `shares` (prb and vcpu per slice) and `queue`.
- `POST /spike` body `{slice: 'embb'|'urllc'|'murllc', factor: float, duration: int}` triggers a surge on all three copies at once.
- `POST /reset` restarts all copies with the same seed.
- `GET /summary` returns cumulative violation rate and mean throughput per policy.

**Dashboard (single HTML file, Chart.js):**

- Three side-by-side columns: Static, Heuristic, Agent.
- Each column: a line chart of URLLC violation rate, a line chart of eMBB throughput, and a stacked bar of current PRB shares.
- Top bar: Trigger Spike buttons (eMBB surge, URLLC burst, mURLLC storm), Reset, and a live scoreboard of cumulative violations.
- Violations over the SLA turn the panel border red.
- Must work offline except for the Chart.js CDN (also keep a local copy of chart.min.js in `static/` as backup).

## 11. Build order with acceptance tests (12 hours)

| Step | Owner | Task | Acceptance test |
| --- | --- | --- | --- |
| 1 (0-1h) | Both | Repo, branches, `config.yaml`, this guide, interface stubs | `python -c 'import gymnasium, stable_baselines3, fastapi'` runs |
| 2 (1-3h) | A | `sim.py` plus `sim_selftest.py` | selftest passes |
| 3 (1-3h) | B | `shield.py` plus unit tests, `train.py` skeleton using a stub env | shield tests pass |
| 4 (3-4h) | A | `baselines.py` and `evaluate.py` for Static and Heuristic | table printed for 4 scenarios |
| 5 (3-6h) | B | PPO training with Lagrangian callback | `models/agent.zip` exists, cost trending down in `runs/log.csv` |
| 6 (4-7h) | A | `api.py` plus WebSocket stream (agent can be a random policy until the model is ready) | `wscat` or browser shows live JSON |
| 7 (5-8h) | A | `static/index.html` dashboard | three panels update live, spike button works |
| 8 (6-9h) | B | Tune reward, lambda, shield floors until Agent beats Static and Heuristic in spike scenarios | evaluate table shows Agent URLLC violation rate at or below limit |
| 9 (8-10h) | Both | Final evaluation, plots, headline number, optional ablation | `results/` has table and PNGs |
| 10 (10-11h) | Both | README, architecture diagram, code freeze at hour 10 | clean clone runs from README steps |
| 11 (11-12h) | Both | Demo rehearsal, backup screen recording | two full dry runs succeed |

Checkpoints: hour 4 (baselines run), hour 7 (agent already beats Static in a spike), hour 10 (code freeze).

## 12. Repo structure and ownership

```
config.yaml
sim.py                 # A
sim_selftest.py        # A
baselines.py           # A
evaluate.py            # A (calls B's model file)
api.py                 # A
static/index.html      # A
shield.py              # B
train.py               # B
models/agent.zip       # B
results/               # both
README.md  PROJECT_GUIDE.md  AGENT_RULES.md  requirements.txt
```

**Git rules:** `main` always runs. Work on branches `a/<topic>` and `b/<topic>`. Commit small. Pull `main` before starting each task. Merge through a Pull Request reviewed by the other person at hours 4, 7 and 10. `config.yaml` and the interface in section 6 change only after both agree. Commit `models/agent.zip` (it is small) so the demo laptop does not need to retrain.

## 13. Evaluation and demo script

**Scenarios (each 20 seeds x 200 steps):** (1) steady load, (2) eMBB surge (x2.5 for 30 steps), (3) URLLC burst (x3 for 20 steps), (4) mURLLC storm (x7 for 10 steps).

**Metrics per policy and slice:** violation rate, p99 of per-step violation rate, mean eMBB throughput ratio, mean resource utilization. Report mean and a confidence interval across seeds.

**Headline number:** 'Agent cuts URLLC+mURLLC violations by X% versus Static while serving Y% more eMBB traffic.' Compute X and Y from the surge scenarios only after the final model is frozen.

**Demo flow (3 minutes):**

1. 20 s: the real problem and the fixed-split failure.
2. 20 s: architecture in one picture (radio plus compute, CMDP, shield).
3. 90 s: live dashboard. Press eMBB surge, then mURLLC storm. Static panel turns red; Agent panel holds the SLA and borrows idle capacity.
4. 30 s: results table and the headline number.
5. 20 s: limitations and future work (ns-3 validation, HARQ puncturing, true 3GPP channel).

Honest limitation to state: the simulator is a slice-level abstraction, not a full radio-level model.

## 14. Rules for the agent (also copy into AGENT\_RULES.md)

1. Read this guide fully before coding. If something is ambiguous, ask instead of guessing.
2. Edit only the files owned by the person who invoked you. Never rewrite unrelated files.
3. Do not add dependencies or change `config.yaml` or the interface without asking.
4. Keep everything laptop-friendly: CPU only, no Docker, no heavy services.
5. After each task run its acceptance test, report the result, and stop if it fails. Do not move on with a failing test.
6. Keep functions small, add type hints and short docstrings, and no hidden global state.
7. Never train live in the demo; always load `models/agent.zip`.
8. Show a `git diff` summary before committing.

## 15. Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| PPO does not learn in time | Simplify the reward, shrink the action to PRB only, raise shield floors |
| Lambda oscillates | Lower `lagrange_lr` to 0.02 and clip lambda to a max of 20 |
| Agent only matches the heuristic | Emphasize the shield guarantee and the radio+compute coupling in the pitch; show eMBB gain separately |
| Dashboard breaks | Use the backup screen recording and `results/` plots |
| Slip of more than 2 hours | Cut in this order: ablation, mURLLC storm scenario, hierarchy wording in the pitch |

## 16. Decisions log

- Python slice-level simulator instead of ns-3 (12 h limit, laptop demo).
- FastAPI instead of Django.
- Constrained RL (Lagrangian PPO) plus hard shield for the SLA claim.
- 3 slices, 100 PRBs, 8 vCPUs, 100 ms steps.
- HARQ puncturing and ns-3 validation moved to future work.

## 17. Addendum: Phased agent plan (supersedes sections 2, 11 and 16 where they conflict)

**ns-3 is now IN scope** as an optional, time-boxed validation phase (Phase 8). The Python simulator stays the engine for training and the live demo. ns-3 must never block Phases 0 to 7.

### Working protocol for the agent

1. Work on ONE phase at a time. At the end of a phase: run its acceptance tests, print a short report (what was built, test output, how to run it), commit on the owner's branch, then STOP and wait for the word 'next'.
2. Ask the human BEFORE: installing system packages, installing ns-3, changing `config.yaml` or the interface contract, adding any dependency.
3. If an acceptance test fails twice, stop and report the error and your best two fixes instead of looping.
4. Never start the next phase on your own.

### Phase 0 questions the agent must ask (in one message)

1. Operating system (Windows, macOS, Linux)? If Windows, is WSL2 with Ubuntu available? (ns-3 needs Linux or WSL2.)
2. Python version installed? Is `git` installed? RAM size and free disk space?
3. Which person are you (A or B), and what is the GitHub repo URL?
4. Do you want to try the ns-3 phase, and who will own it?
5. Is there any internet restriction on the demo laptop?

### Phases

| Phase | Goal | Deliverables | Acceptance test |
| --- | --- | --- | --- |
| 0 | Environment and skeleton | venv, `requirements.txt`, folder structure, `config.yaml`, `.gitignore` | imports of gymnasium, stable\_baselines3, fastapi succeed |
| 1 | Simulator | `sim.py`, `sim_selftest.py`; tune config numbers so Static visibly fails in a spike | selftest passes; Static shows violations in a spike run |
| 2 | Baselines and evaluation harness | `baselines.py`, `evaluate.py` | results table for 4 scenarios printed and saved |
| 3 | Shield | `shield.py` plus unit tests | floors and sum-to-1 tests pass |
| 4 | Constrained RL | `train.py` with Lagrangian callback, `models/agent.zip`, training curve | cost trends under limit; model beats Static in spike scenarios |
| 5 | API | `api.py` with `/ws`, `/spike`, `/reset`, `/summary`, `/health` | browser or wscat shows live JSON for 3 policies |
| 6 | Dashboard UI and UX | `static/index.html` per the UX spec below | demo flow works end to end |
| 7 | Results and README | `results/` plots and table, README with architecture, headline number | clean clone runs from README steps |
| 8 (optional) | ns-3 validation | see below | one scenario runs in ns-3 and the trained policy is replayed |

### UX spec: how everything is visible in the UI (Phase 6)

- **Top bar:** project title, Trigger Spike buttons (eMBB surge, URLLC burst, mURLLC storm), Pause, Reset, scenario name, step counter.
- **Three columns:** Static, Heuristic, Agent, all on the same traffic.
- **Per column:** (1) URLLC and mURLLC violation-rate line chart with the SLA line drawn on it, (2) eMBB throughput line chart, (3) live stacked bars of PRB share and vCPU share per slice, (4) queue-length gauge for eMBB.
- **Status chip per column:** green 'SLA OK' or red 'SLA BREACH'.
- **Agent-only extras (this is the 'how it happens' part):** lambda gauge (shows the constraint pressure rising and falling), a 'Shield active' indicator that lights when the shield overrides the policy, and an auto-generated plain-English event log, for example 'Step 84: eMBB surge detected. Agent borrowed 18% PRB from idle slices; URLLC kept at floor.'
- **Scoreboard:** cumulative violations and mean eMBB throughput per policy, plus the headline comparison once enough steps have run.
- **Design:** dark theme, one accent colour per slice (consistent across all charts), readable from 2 metres on a projector, no scrolling during the demo.
- **Backup:** a 'Replay recorded run' button that plays a saved run from `results/` if the live loop fails.

### Phase 8: ns-3 (optional, time-boxed to 3 hours, runs in parallel by one person)

- Ask the human first. Do not install anything without a yes.
- Look up current compatible versions of ns-3, the 5G-LENA module and the Python bridge (ns3-ai or ns3-gym) from their official repositories at the time of install; do not rely on memory of version numbers.
- Install in Linux or WSL2, in a separate folder `ns3/`, never inside the Python demo environment.
- Goal: one 5G scenario with 3 UE groups (one per slice) and a traffic burst, logging per-slice throughput and delay to CSV. Then replay the trained policy's resource shares against it, or compare Static vs Agent shares there, and report the result as 'validation', not as the main demo.
- Hard stop: if a basic 5G-LENA example is not running after 3 hours, abandon this phase, record what failed in the README under future work, and continue the demo with the Python simulator.

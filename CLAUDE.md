# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A 2D physics simulation (pymunk + pygame) that drops a thin "bar" (短冊) onto a tilted stage (slanted floor + vertical wall) and judges whether the bar settles cleanly into the corner ("設置成功"). It sweeps release position, release angle, and stage angle to find which conditions succeed reliably. Documentation (README.md, SIMULATION_GUIDE.md) is in Japanese; keep new user-facing text and comments in Japanese to match.

## Commands

```bash
# Activate the venv first (deps live here, not in a requirements file)
source .venv/bin/activate

# Run via the Streamlit UI (recommended; does NOT edit main.py)
streamlit run streamlit_app.py
# On AWS/headless: streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501

# Run directly: edit the MODE constant at top of main.py, then
python main.py

# Run a single config headlessly (what the UI calls under the hood)
python sim_runner.py <config.json>
```

Dependencies (no requirements.txt): `pygame pymunk numpy pandas matplotlib seaborn psutil streamlit Pillow`. There is no test suite, linter, or build step. See `AWS_RUN_GUIDE.md` for the EC2 transfer/run workflow.

## Architecture

Three-layer design where **`main.py` is the engine and is never modified by the UI**:

- **`main.py`** (~2300 lines) — all simulation logic plus module-level global config (lines ~33–103: `MODE`, `OUTPUT_DIR`, physics constants, `SUCCESS_CRITERIA`, `BATCH_PARAM_RANGES`, etc.). Four entry points, one per mode:
  - `run_interactive_mode()` — live pygame window, keyboard/mouse parameter tuning (not used on AWS).
  - `run_single_condition_mode()` — one condition → PNG (and GIF if `GENERATE_GIF`).
  - `run_batch_mode()` — sequential sweep over `BATCH_PARAM_RANGES` → CSV + heatmaps.
  - `run_batch_mode_parallel()` — same sweep across cores via `multiprocessing.Pool`.
- **`sim_runner.py`** — thin runner. Loads a JSON config, **overwrites `main`'s module globals** (`main.OUTPUT_DIR = ...`, etc.) via `_apply_overrides()`, then calls the matching `run_*` function. Forces `matplotlib.use("Agg")` *before* importing main so batch `plt.show()` calls become no-ops and only PNGs are written.
- **`streamlit_app.py`** — UI. Builds a config dict, writes it to a temp JSON, and launches `sim_runner.py` as a `subprocess` (`sys.executable`). Never imports main directly.

### Critical gotcha: BATCH_PARALLEL ignores some overrides on spawn platforms
On Windows (and any `spawn` start-method), parallel worker processes **re-import `main.py` fresh**, so the globals `sim_runner` patched in the parent are lost. Variability (`RELEASE_*_VARIABILITY`), `SIMULATION_DURATION`, contact thresholds, and floor-fail validation fall back to `main.py`'s file defaults in workers. Only the param ranges and trial count survive (they're passed as args). To sweep those other settings, use sequential `BATCH`, or change the defaults in `main.py` itself.

### Coordinate system (important when touching geometry)
Micrometer scale: **1 pixel = 1 μm**, `PPM = 1_000_000`. Canvas is 4000×4000 px (= 4 mm²). Stage base `BASE = (2000, 2000)` is screen center. Release offsets are relative to the **ideal position** (`calculate_ideal_position`), not the screen origin: `offset=(0,0)` means release == ideal. When `ANGLE_LINKED_OFFSET=True`, the X (slope) / Y (wall) offset axes rotate with the stage tilt.

### Success / failure judging
`check_success()` returns success only if all of `SUCCESS_CRITERIA` pass (velocity, angular velocity, angle tolerance, settle time, position tolerance) AND the bar isn't touching the floor (when `ENABLE_FLOOR_FAIL_VALIDATION`). Multi-bar contact failures use `CONTACT_COUNT_THRESHOLD` / `CONTACT_DIFF_THRESHOLD`, with contacts within `IDEAL_NEIGHBORHOOD_RADIUS` of the ideal position ignored as normal settling.

## Outputs

CSV: `simulation_results.csv` (sequential) / `simulation_results_parallel.csv` (parallel). PNGs: `success_rate_heatmaps.png`, `heatmap_interactive_angle_*deg.png`, `single_condition_result.png`. Output dir is `OUTPUT_DIR` in main.py (default `results_err_aws_5`) or the UI's field (default `results_streamlit`). Many `results*/` dirs are committed snapshots of past runs.

## Notes

- `main_old.py` / `main_oldv2.py` are untracked backups — ignore them; edit `main.py`.
- `ipaexg.ttf` (committed) is the Japanese font for matplotlib/pygame text; don't remove it.

# -*- coding: utf-8 -*-
"""
Streamlit UI から呼び出される薄いランナー。

main.py のモジュールグローバルを JSON 設定で上書きしてから、
指定されたモードの実行関数を呼ぶだけ。main.py 本体には一切変更を加えない。

使い方:
    python sim_runner.py <config.json>

config.json のスキーマは streamlit_app.py の build_config() を参照。
"""
import sys
import os
import json

# matplotlib をヘッドレス(Agg)に固定する。
# - これにより BATCH モードの generate_heatmaps() 内の plt.show() が
#   ブロッキングせず no-op になり、PNG だけが保存される。
# - INTERACTIVE モードは pygame を使うため影響しない。
# main を import する前に設定する必要がある。
try:
    import matplotlib
    matplotlib.use("Agg")
except ImportError:
    pass

import main


def _apply_overrides(cfg):
    """cfg の内容を main モジュールのグローバルへ反映する。"""
    main.OUTPUT_DIR = cfg["output_dir"]

    if "simulation_duration" in cfg:
        main.SIMULATION_DURATION = float(cfg["simulation_duration"])
    if "contact_count_threshold" in cfg:
        main.CONTACT_COUNT_THRESHOLD = int(cfg["contact_count_threshold"])
    if "contact_diff_threshold" in cfg:
        main.CONTACT_DIFF_THRESHOLD = float(cfg["contact_diff_threshold"])
    if "ideal_neighborhood_radius" in cfg:
        main.IDEAL_NEIGHBORHOOD_RADIUS = float(cfg["ideal_neighborhood_radius"])
    if "enable_floor_fail" in cfg:
        main.ENABLE_FLOOR_FAIL_VALIDATION = bool(cfg["enable_floor_fail"])
    if "enable_no_contact_fail" in cfg:
        main.ENABLE_NO_CONTACT_FAIL = bool(cfg["enable_no_contact_fail"])
    if "generate_gif" in cfg:
        main.GENERATE_GIF = bool(cfg["generate_gif"])
    if "angle_linked_offset" in cfg:
        main.ANGLE_LINKED_OFFSET = bool(cfg["angle_linked_offset"])

    # 摩擦係数・反発係数（面ごと）。BATCH_PARALLEL でもワーカーへ引き継がれる
    # （main.collect_worker_settings() 経由でタスクに同梱される）。
    ph = cfg.get("physics")
    if ph:
        for key in ("BAR_FRICTION", "BAR_ELASTICITY",
                    "WALL_FRICTION", "WALL_ELASTICITY",
                    "FLOOR_FRICTION", "FLOOR_ELASTICITY",
                    "BOUNDARY_FRICTION", "BOUNDARY_ELASTICITY"):
            if key in ph:
                setattr(main, key, float(ph[key]))

    rv = cfg.get("release_velocity")
    if rv:
        main.RELEASE_VELOCITY_MPS = float(rv.get("mps", main.RELEASE_VELOCITY_MPS))
        main.RELEASE_VELOCITY_ANGLE_DEG = float(
            rv.get("angle_deg", main.RELEASE_VELOCITY_ANGLE_DEG)
        )
        main.RELEASE_VELOCITY_ANGLE_MODE = str(
            rv.get("angle_mode", main.RELEASE_VELOCITY_ANGLE_MODE)
        )

    ho = cfg.get("heatmap_overlay")
    if ho:
        main.HEATMAP_OVERLAY_OPTIONS.update(ho)

    var = cfg.get("variability")
    if var:
        main.RELEASE_X_VARIABILITY = float(var.get("x", main.RELEASE_X_VARIABILITY))
        main.RELEASE_Y_VARIABILITY = float(var.get("y", main.RELEASE_Y_VARIABILITY))
        main.RELATIVE_ANGLE_VARIABILITY = float(
            var.get("angle", main.RELATIVE_ANGLE_VARIABILITY)
        )

    if "single_params" in cfg and cfg["single_params"]:
        main.SINGLE_CONDITION_PARAMS = dict(cfg["single_params"])

    if "num_trials" in cfg:
        main.NUM_TRIALS_PER_CONDITION = int(cfg["num_trials"])

    if "batch_ranges" in cfg and cfg["batch_ranges"]:
        main.BATCH_PARAM_RANGES = _build_batch_ranges(cfg["batch_ranges"])


def _build_batch_ranges(br):
    """
    JSON で渡された範囲指定を main が期待する形へ変換する。
    angle / release_x_offset / release_y_offset は [start, stop, step] -> range()
    relative_angle はそのままリスト。
    """
    ranges = {}
    for key in ("angle", "release_x_offset", "release_y_offset"):
        if key in br:
            start, stop, step = br[key]
            ranges[key] = range(int(start), int(stop), int(step))
    ranges["relative_angle"] = list(br.get("relative_angle", [0]))
    return ranges


def main_entry():
    if len(sys.argv) < 2:
        print("ERROR: config JSON path required", file=sys.stderr)
        sys.exit(2)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)

    _apply_overrides(cfg)
    os.makedirs(main.OUTPUT_DIR, exist_ok=True)

    mode = cfg["mode"]
    print(f"=== sim_runner: mode={mode}, output_dir={main.OUTPUT_DIR} ===", flush=True)

    if mode == "SINGLE":
        main.run_single_condition_mode()
    elif mode == "BATCH":
        main.run_batch_mode()
    elif mode == "BATCH_PARALLEL":
        main.run_batch_mode_parallel()
    elif mode == "INTERACTIVE":
        main.run_interactive_mode()
    else:
        print(f"ERROR: unknown mode '{mode}'", file=sys.stderr)
        sys.exit(2)

    print("=== sim_runner: done ===", flush=True)


if __name__ == "__main__":
    main_entry()

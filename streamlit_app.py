# -*- coding: utf-8 -*-
"""
バーセットシミュレーション 操作UI (Streamlit)

モードを選択 → パラメータを入力 → 実行、を行うフロントエンド。
実行は sim_runner.py を subprocess として起動する形で行い、
pygame / matplotlib / multiprocessing の状態が Streamlit サーバ
プロセスに干渉しないようにしている。main.py 本体は変更しない。

起動方法:
    streamlit run streamlit_app.py
"""
import os
import sys
import json
import glob
import tempfile
import subprocess

import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(BASE_DIR, "sim_runner.py")
SETTINGS_FILE = os.path.join(BASE_DIR, ".streamlit_ui_settings.json")

st.set_page_config(page_title="バーセットシミュレーション", layout="wide")


# --------------------------------------------------------------------------
# UI設定の永続化（再起動をまたいで記憶する）
# --------------------------------------------------------------------------
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# 起動/再実行のたびにファイルから読み込む。各ウィジェットはこの値を初期値に使い、
# スクリプト末尾で現在値をマージ保存する（表示されていないモードの設定も保持される）。
S = load_settings()


# --------------------------------------------------------------------------
# subprocess 実行ユーティリティ
# --------------------------------------------------------------------------
def _child_env():
    env = os.environ.copy()
    # 子プロセスの標準出力を UTF-8 に固定（Windows の cp932 で文字化けしないように）
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def write_config(cfg):
    fd, path = tempfile.mkstemp(suffix=".json", prefix="barsim_cfg_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def run_blocking(cfg):
    """完了まで待つモード(SINGLE/BATCH/BATCH_PARALLEL)を実行し、ログをUIへ流す。"""
    cfg_path = write_config(cfg)
    log_box = st.empty()
    lines = []
    proc = subprocess.Popen(
        [sys.executable, RUNNER, cfg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=BASE_DIR,
        env=_child_env(),
    )
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        # 末尾200行だけ表示（長大なログでもUIが重くならないように）
        log_box.code("\n".join(lines[-200:]), language="text")
    proc.wait()
    return proc.returncode, lines


def run_interactive(cfg):
    """INTERACTIVE モードを別ウィンドウ(別コンソール)で起動。Streamlit はブロックしない。"""
    cfg_path = write_config(cfg)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # 専用コンソールを開く
    subprocess.Popen(
        [sys.executable, RUNNER, cfg_path],
        cwd=BASE_DIR,
        env=_child_env(),
        creationflags=creationflags,
    )


def show_results(mode, output_dir):
    """実行後に成果物(画像/CSV)を表示する。"""
    out = os.path.join(BASE_DIR, output_dir) if not os.path.isabs(output_dir) else output_dir
    if not os.path.isdir(out):
        st.warning(f"出力フォルダが見つかりません: {out}")
        return

    st.subheader("実行結果")

    if mode == "SINGLE":
        png = os.path.join(out, "single_condition_result.png")
        if os.path.exists(png):
            st.image(png, caption="single_condition_result.png", use_container_width=True)
        else:
            st.info("結果画像が見つかりませんでした。")
        return

    # BATCH / BATCH_PARALLEL
    # 並列モードは simulation_results_parallel.csv を出力するが、psutil 等が無く
    # 逐次版へフォールバックした場合は simulation_results.csv になる。両方を探す。
    candidates = (
        ["simulation_results_parallel.csv", "simulation_results.csv"]
        if mode == "BATCH_PARALLEL"
        else ["simulation_results.csv"]
    )
    csv_name, csv_path = None, None
    for name in candidates:
        p = os.path.join(out, name)
        if os.path.exists(p):
            csv_name, csv_path = name, p
            break
    if csv_path:
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            st.markdown(f"**CSV: `{csv_name}`** ({len(df)} 条件)")
            st.dataframe(df, use_container_width=True)
            with open(csv_path, "rb") as f:
                st.download_button("CSV をダウンロード", f, file_name=csv_name, mime="text/csv")
        except Exception as e:
            st.warning(f"CSV 読込に失敗: {e}")
    else:
        st.info(f"結果CSV ({' / '.join(candidates)}) が見つかりませんでした。")

    overview = os.path.join(out, "success_rate_heatmaps.png")
    if os.path.exists(overview):
        st.image(overview, caption="success_rate_heatmaps.png", use_container_width=True)

    per_angle = sorted(glob.glob(os.path.join(out, "heatmap_interactive_angle_*deg.png")))
    if per_angle:
        st.markdown("**角度別ヒートマップ**")
        for p in per_angle:
            st.image(p, caption=os.path.basename(p), use_container_width=True)


def show_deviation_metrics(log_lines):
    """SINGLE モードの標準出力から理想位置とのズレ(DEVIATION_*)を抽出して表示する。"""
    um = mm = None
    ok = None
    for line in log_lines:
        s = line.strip()
        if s.startswith("DEVIATION_UM:"):
            um = float(s.split(":", 1)[1])
        elif s.startswith("DEVIATION_MM:"):
            mm = float(s.split(":", 1)[1])
        elif s.startswith("DEVIATION_OK:"):
            ok = s.split(":", 1)[1].strip() == "1"
    if um is None:
        return
    st.subheader("理想位置とのズレ")
    c1, c2, c3 = st.columns(3)
    c1.metric("ズレ (μm)", f"{um:.2f}")
    c2.metric("ズレ (mm)", f"{mm:.4f}")
    c3.metric("許容判定", "OK" if ok else "NG")
    if ok:
        st.success("理想位置の許容誤差内に設置されました。")
    else:
        st.warning("理想位置の許容誤差を超えています。")


def show_contact_metrics(log_lines):
    """SINGLE モードの標準出力から短冊接触の集計(SHORT_*/LONG_*)を抽出して表示する。"""
    vals = {}
    for line in log_lines:
        s = line.strip()
        for key in ("SHORT_TOTAL", "SHORT_SLOPE", "SHORT_WALL",
                    "SHORT_COUNTED", "SHORT_EXCLUDED", "LONG_TOTAL"):
            if s.startswith(key + ":"):
                try:
                    vals[key] = int(s.split(":", 1)[1])
                except ValueError:
                    pass
    if "SHORT_TOTAL" not in vals:
        return
    st.subheader("短冊接触の集計（斜面+壁）")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("短冊接触 合計", vals.get("SHORT_TOTAL", 0),
              help="short_side と判定された接触の総数（斜面＋壁）")
    c2.metric("うち斜面 / 壁", f"{vals.get('SHORT_SLOPE', 0)} / {vals.get('SHORT_WALL', 0)}")
    c3.metric("有効カウント", vals.get("SHORT_COUNTED", 0),
              help="理想位置近傍で除外した分を引いた、複数回接触判定の対象数")
    c4.metric("近傍で除外", vals.get("SHORT_EXCLUDED", 0))
    st.caption(
        f"長手接触(long_side): {vals.get('LONG_TOTAL', 0)} 回 ／ "
        f"接触法線の向きで短冊(short_side)/長手(long_side)を判定しています。"
    )


# --------------------------------------------------------------------------
# サイドバー: モード選択 & 共通設定
# --------------------------------------------------------------------------
st.title("バーセットシミュレーション コントロールパネル")

MODE_LABELS = {
    "SINGLE": "SINGLE — 単一条件の結果画像を生成",
    "BATCH": "BATCH — パラメータ範囲を逐次探索 (CSV + ヒートマップ)",
    "BATCH_PARALLEL": "BATCH_PARALLEL — 並列探索 (高速)",
    "INTERACTIVE": "INTERACTIVE — リアルタイム操作 (別ウィンドウで起動)",
}

with st.sidebar:
    st.header("モード選択")
    _mode_keys = list(MODE_LABELS.keys())
    _saved_mode = S.get("mode", _mode_keys[0])
    _mode_index = _mode_keys.index(_saved_mode) if _saved_mode in _mode_keys else 0
    mode = st.radio(
        "実行モード",
        _mode_keys,
        index=_mode_index,
        format_func=lambda m: MODE_LABELS[m],
    )

    st.header("共通設定")
    output_dir = st.text_input("出力フォルダ", value=S.get("output_dir", "results_streamlit"))
    simulation_duration = st.number_input(
        "シミュレーション時間 (秒)", min_value=0.5, max_value=30.0,
        value=float(S.get("simulation_duration", 4.0)), step=0.5
    )
    enable_floor_fail = st.checkbox("床接触をNG扱いにする", value=bool(S.get("enable_floor_fail", True)))
    angle_linked_offset = st.checkbox(
        "オフセットをステージ角度に連動させる",
        value=bool(S.get("angle_linked_offset", False)),
        help="リリースオフセットの原点は常に『理想位置』です（offset=0 → リリース位置＝理想位置）。"
        "ON にすると、その軸がステージ傾斜に合わせて回転します（Xオフセット=斜面方向 / Yオフセット=壁方向）。",
    )
    with st.expander("接触判定の閾値", expanded=False):
        contact_count_threshold = st.number_input(
            "短冊方向 接触回数の閾値", min_value=1, max_value=50,
            value=int(S.get("contact_count_threshold", 5)), step=1
        )
        contact_diff_threshold = st.number_input(
            "接触位置 累積差分の閾値 (μm)", min_value=0.0, max_value=100.0,
            value=float(S.get("contact_diff_threshold", 1.0)), step=0.5
        )
        ideal_neighborhood_radius = st.number_input(
            "理想位置近傍の除外半径 (μm)",
            min_value=0.0, max_value=500.0,
            value=float(S.get("ideal_neighborhood_radius", 10.0)), step=1.0,
            help="バー重心が理想位置からこの半径以内のときに発生した短冊接触は"
            "「正常な収まり」とみなしてカウントから除外します。",
        )

    st.divider()
    st.caption("設定は自動保存され、次回起動時に復元されます。")
    if st.button("設定をデフォルトに戻す"):
        try:
            os.remove(SETTINGS_FILE)
        except OSError:
            pass
        st.rerun()


def common_cfg():
    return {
        "mode": mode,
        "output_dir": output_dir,
        "simulation_duration": simulation_duration,
        "enable_floor_fail": enable_floor_fail,
        "contact_count_threshold": contact_count_threshold,
        "contact_diff_threshold": contact_diff_threshold,
        "ideal_neighborhood_radius": ideal_neighborhood_radius,
        "angle_linked_offset": angle_linked_offset,
    }


# 共通設定の現在値を永続化用ディクショナリへ反映
S.update({
    "mode": mode,
    "output_dir": output_dir,
    "simulation_duration": float(simulation_duration),
    "enable_floor_fail": bool(enable_floor_fail),
    "angle_linked_offset": bool(angle_linked_offset),
    "contact_count_threshold": int(contact_count_threshold),
    "contact_diff_threshold": float(contact_diff_threshold),
    "ideal_neighborhood_radius": float(ideal_neighborhood_radius),
})


# --------------------------------------------------------------------------
# メインパネル: モード別パラメータ
# --------------------------------------------------------------------------
st.markdown(f"### モード: `{mode}`")

if mode in ("SINGLE", "INTERACTIVE"):
    st.markdown("単一条件のパラメータ（リリース位置・角度）を指定します。")
    st.caption("リリース X/Y オフセットは『理想位置』を原点(0,0)とした、ずらし量です（offset=0 → 理想位置からリリース）。")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        angle = st.number_input("ステージ角度 (°)", value=int(S.get("single_angle", 30)), step=1)
    with c2:
        rx = st.number_input("リリース X オフセット (μm)", value=int(S.get("single_rx", 0)), step=5)
    with c3:
        ry = st.number_input("リリース Y オフセット (μm)", value=int(S.get("single_ry", 600)), step=5)
    with c4:
        rel = st.number_input("相対リリース角度 (°)", value=int(S.get("single_rel", 0)), step=1)

    S.update({"single_angle": int(angle), "single_rx": int(rx),
              "single_ry": int(ry), "single_rel": int(rel)})

    cfg = common_cfg()
    cfg["single_params"] = {
        "angle": int(angle),
        "release_x_offset": int(rx),
        "release_y_offset": int(ry),
        "relative_angle": int(rel),
    }

    if mode == "SINGLE":
        if st.button("▶ 実行 (画像生成)", type="primary"):
            with st.spinner("シミュレーション実行中..."):
                rc, log_lines = run_blocking(cfg)
            if rc == 0:
                st.success("完了しました。")
            else:
                st.error(f"異常終了しました (exit={rc})。上のログを確認してください。")
            show_deviation_metrics(log_lines)
            show_contact_metrics(log_lines)
            show_results("SINGLE", output_dir)
    else:  # INTERACTIVE
        st.info(
            "INTERACTIVE モードは pygame の別ウィンドウで開きます（ブラウザ内には表示できません）。"
            "操作方法はウィンドウ内に表示されます（矢印キー/W,S/Q,E/R/+,-/クリック等）。"
        )
        if st.button("▶ 別ウィンドウで起動", type="primary"):
            run_interactive(cfg)
            st.success("別ウィンドウで起動しました。タスクバー/画面を確認してください。")

else:  # BATCH / BATCH_PARALLEL
    st.markdown("探索するパラメータ範囲（開始・終了・刻み）を指定します。`range()` と同様、終了値は含みません。")
    st.caption("リリース X/Y オフセットは『理想位置』を原点(0,0)とした、ずらし量です。")

    st.markdown("**ステージ角度 (°)**")
    a1, a2, a3 = st.columns(3)
    angle_start = a1.number_input("角度 開始", value=int(S.get("angle_start", 20)), step=1, key="as")
    angle_stop = a2.number_input("角度 終了(未満)", value=int(S.get("angle_stop", 31)), step=1, key="ae")
    angle_step = a3.number_input("角度 刻み", value=int(S.get("angle_step", 10)), min_value=1, step=1, key="ast")

    st.markdown("**リリース X オフセット (μm)**")
    x1, x2, x3 = st.columns(3)
    x_start = x1.number_input("X 開始", value=int(S.get("x_start", -300)), step=5, key="xs")
    x_stop = x2.number_input("X 終了(未満)", value=int(S.get("x_stop", 300)), step=5, key="xe")
    x_step = x3.number_input("X 刻み", value=int(S.get("x_step", 50)), min_value=1, step=5, key="xst")

    st.markdown("**リリース Y オフセット (μm)**")
    y1, y2, y3 = st.columns(3)
    y_start = y1.number_input("Y 開始", value=int(S.get("y_start", 400)), step=5, key="ys")
    y_stop = y2.number_input("Y 終了(未満)", value=int(S.get("y_stop", 1000)), step=5, key="ye")
    y_step = y3.number_input("Y 刻み", value=int(S.get("y_step", 50)), min_value=1, step=5, key="yst")

    rel_text = st.text_input("相対リリース角度のリスト (カンマ区切り)", value=str(S.get("rel_text", "0")))

    t1, t2 = st.columns(2)
    num_trials = t1.number_input("各条件の試行回数", min_value=1, value=int(S.get("num_trials", 10)), step=1)

    with st.expander("リリース位置・角度のバラツキ（標準偏差）", expanded=False):
        v1, v2, v3 = st.columns(3)
        var_x = v1.number_input("X バラツキ (μm)", min_value=0.0, value=float(S.get("var_x", 0.0)), step=1.0)
        var_y = v2.number_input("Y バラツキ (μm)", min_value=0.0, value=float(S.get("var_y", 0.0)), step=1.0)
        var_a = v3.number_input("角度 バラツキ (°)", min_value=0.0, value=float(S.get("var_a", 0.0)), step=0.1)

    # 試行数の概算を表示
    try:
        n_angle = len(range(int(angle_start), int(angle_stop), int(angle_step)))
        n_x = len(range(int(x_start), int(x_stop), int(x_step)))
        n_y = len(range(int(y_start), int(y_stop), int(y_step)))
        rel_list = [int(s) for s in rel_text.split(",") if s.strip() != ""]
        n_rel = max(1, len(rel_list))
        n_cond = n_angle * n_x * n_y * n_rel
        st.caption(
            f"条件数: {n_cond}（角度 {n_angle} × X {n_x} × Y {n_y} × 相対角 {n_rel}） "
            f"／ 総試行回数: {n_cond * int(num_trials)}"
        )
    except Exception:
        rel_list = [0]
        st.caption("範囲指定を確認してください。")

    if mode == "BATCH_PARALLEL":
        st.warning(
            "並列モードでは **バラツキ / シミュレーション時間 / 接触閾値 / 理想位置近傍除外 / 床接触判定 / オフセット角度連動** は "
            "main.py の既定値が使われます（パラメータ範囲と試行回数は反映されます）。"
            "これらを変更して探索したい場合は逐次 BATCH を使用してください。"
        )

    S.update({
        "angle_start": int(angle_start), "angle_stop": int(angle_stop), "angle_step": int(angle_step),
        "x_start": int(x_start), "x_stop": int(x_stop), "x_step": int(x_step),
        "y_start": int(y_start), "y_stop": int(y_stop), "y_step": int(y_step),
        "rel_text": rel_text, "num_trials": int(num_trials),
        "var_x": float(var_x), "var_y": float(var_y), "var_a": float(var_a),
    })

    cfg = common_cfg()
    cfg["num_trials"] = int(num_trials)
    cfg["variability"] = {"x": float(var_x), "y": float(var_y), "angle": float(var_a)}
    cfg["batch_ranges"] = {
        "angle": [int(angle_start), int(angle_stop), int(angle_step)],
        "release_x_offset": [int(x_start), int(x_stop), int(x_step)],
        "release_y_offset": [int(y_start), int(y_stop), int(y_step)],
        "relative_angle": rel_list,
    }

    label = "▶ 並列実行" if mode == "BATCH_PARALLEL" else "▶ 逐次実行"
    if st.button(label, type="primary"):
        with st.spinner("探索を実行中... (進捗は下のログに表示されます)"):
            rc, _ = run_blocking(cfg)
        if rc == 0:
            st.success("完了しました。")
        else:
            st.error(f"異常終了しました (exit={rc})。上のログを確認してください。")
        show_results(mode, output_dir)


# --------------------------------------------------------------------------
# 設定の永続化（毎回の実行末尾で現在値を保存。次回起動時に復元される）
# --------------------------------------------------------------------------
save_settings(S)

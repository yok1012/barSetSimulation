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
import math
import glob
import tempfile
import subprocess

import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(BASE_DIR, "sim_runner.py")
SETTINGS_FILE = os.path.join(BASE_DIR, ".streamlit_ui_settings.json")

st.set_page_config(page_title="バーセットシミュレーション", layout="wide")


# --------------------------------------------------------------------------
# 配置プレビュー用のジオメトリ（main.py の値を複製）
#   main.py を import すると pygame/pymunk が Streamlit サーバプロセスに
#   読み込まれてしまうため、座標計算に必要な定数・式だけをここに複製する。
#   値・式は main.py の compute_release_pos / calculate_ideal_position /
#   setup_space と一致させること。
# --------------------------------------------------------------------------
BASE_X, BASE_Y = 2000, 2000          # 台座（斜面と壁の角）座標 [μm]
SLOPE_LENGTH = 1500                   # 斜面長さ [μm]
WALL_HEIGHT = 1000                    # 壁の高さ [μm]
IDEAL_RADIUS = 508.069                # 理想位置の円弧半径 [μm]
IDEAL_ANGLE_BASE_DEG = 276.259234     # 理想位置角度 = この値 - ステージ角度
PPM = 1000000.0                       # 1 pixel = 1 μm
BAR_WIDTH_UM = 100                    # バー短辺 0.1mm（main.BAR_WIDTH * PPM）
BAR_HEIGHT_UM = 1000                  # バー長辺 1mm（main.BAR_HEIGHT * PPM）


def _rect_vertices(pos, size, angle):
    """中心 pos・寸法 size の矩形を angle 回転した4頂点（main.get_rect_vertices と同一）。"""
    w, h = size
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    pts = []
    for dw, dh in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append((pos[0] + dw * cos_a - dh * sin_a, pos[1] + dw * sin_a + dh * cos_a))
    return pts


def calc_ideal_position(angle_deg):
    """理想位置 (ideal_x, ideal_y) を計算（main.calculate_ideal_position と同一）。"""
    ideal_angle_rad = math.radians(IDEAL_ANGLE_BASE_DEG - abs(angle_deg))
    return (BASE_X + IDEAL_RADIUS * math.cos(ideal_angle_rad),
            BASE_Y + IDEAL_RADIUS * math.sin(ideal_angle_rad))


def compute_release_pos(angle_deg, x_offset, y_offset, angle_linked):
    """落下開始（リリース）位置を計算（main.compute_release_pos と同一）。"""
    stage_angle_rad = math.radians(-angle_deg)
    ideal_x, ideal_y = calc_ideal_position(angle_deg)
    if angle_linked:
        cos_t, sin_t = math.cos(stage_angle_rad), math.sin(stage_angle_rad)
        return (ideal_x + x_offset * cos_t + y_offset * sin_t,
                ideal_y + x_offset * sin_t - y_offset * cos_t)
    return ideal_x + x_offset, ideal_y - y_offset


def _setup_preview_font():
    """同梱の日本語フォント(ipaexg.ttf)を matplotlib に登録する。失敗時は None。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager, pyplot as plt
    font_path = os.path.join(BASE_DIR, "ipaexg.ttf")
    if os.path.exists(font_path):
        try:
            font_manager.fontManager.addfont(font_path)
            name = font_manager.FontProperties(fname=font_path).get_name()
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
        except Exception:
            pass
    return None


def build_layout_preview(angle_deg, rx, ry, angle_linked, rel_angle_deg=0):
    """台座・理想位置・落下開始位置を図示した matplotlib Figure と座標を返す。"""
    _setup_preview_font()
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    stage_angle_rad = math.radians(-angle_deg)
    ideal_x, ideal_y = calc_ideal_position(angle_deg)
    rel_x, rel_y = compute_release_pos(angle_deg, rx, ry, angle_linked)
    # 落下開始時のバー姿勢（main: actual_release_angle = stage_angle + relative_angle）
    release_angle_rad = stage_angle_rad + math.radians(-rel_angle_deg)
    bar_verts = _rect_vertices((rel_x, rel_y), (BAR_WIDTH_UM, BAR_HEIGHT_UM), release_angle_rad)

    slope_end = (BASE_X + SLOPE_LENGTH * math.cos(stage_angle_rad),
                 BASE_Y + SLOPE_LENGTH * math.sin(stage_angle_rad))
    wall_angle = stage_angle_rad - math.pi / 2
    wall_end = (BASE_X + WALL_HEIGHT * math.cos(wall_angle),
                BASE_Y + WALL_HEIGHT * math.sin(wall_angle))

    fig, ax = plt.subplots(figsize=(6, 6))

    # 斜面・壁
    ax.plot([BASE_X, slope_end[0]], [BASE_Y, slope_end[1]], color="#555555", lw=3, label="斜面")
    ax.plot([BASE_X, wall_end[0]], [BASE_Y, wall_end[1]], color="#aaaaaa", lw=3, label="壁")

    # オフセット基準軸（原点＝理想位置）
    axis_len = max(200, IDEAL_RADIUS * 0.5)
    if angle_linked:
        xdir = (math.cos(stage_angle_rad), math.sin(stage_angle_rad))   # +X=斜面方向
        ydir = (math.sin(stage_angle_rad), -math.cos(stage_angle_rad))  # +Z=壁方向
    else:
        xdir = (1.0, 0.0)    # +X→右
        ydir = (0.0, -1.0)   # +Z→上
    # +X/+Z オフセット軸（矢印）。ラベルは矢印の先端に白背景付きで少し離して置く。
    bbox = dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75)
    for d, color, lbl in ((xdir, "#8B4513", "+X"), (ydir, "#008080", "+Z")):
        tip = (ideal_x + d[0] * axis_len, ideal_y + d[1] * axis_len)
        ax.annotate("", xy=tip, xytext=(ideal_x, ideal_y),
                    arrowprops=dict(arrowstyle="->", color=color, lw=1.5))
        ax.text(ideal_x + d[0] * (axis_len + 60), ideal_y + d[1] * (axis_len + 60),
                lbl, color=color, fontsize=9, ha="center", va="center", bbox=bbox)

    # 理想位置 → 落下開始位置（オフセット量）
    if (rel_x, rel_y) != (ideal_x, ideal_y):
        ax.plot([ideal_x, rel_x], [ideal_y, rel_y], color="orange", ls="--", lw=1.3, zorder=3)

    # 落下開始時のバーの輪郭を点線で図示
    ax.add_patch(Polygon(bar_verts, closed=True, fill=False, ls="--", lw=1.5,
                         ec="#1e90ff", zorder=4, label="バー(落下開始姿勢)"))

    # マーカー（凡例にまとめ、図中への文字重なりを避ける）
    ax.scatter([BASE_X], [BASE_Y], c="red", marker="P", s=140, zorder=5, label="台座(BASE)")
    ax.scatter([ideal_x], [ideal_y], c="green", marker="+", s=240, linewidths=2.5,
               zorder=5, label="理想位置")
    ax.scatter([rel_x], [rel_y], facecolors="magenta", edgecolors="purple",
               marker="o", s=110, zorder=6, label="落下開始位置")

    # 表示範囲（バー輪郭を含む全点を含めて少し余白）
    xs = [BASE_X, slope_end[0], wall_end[0], ideal_x, rel_x] + [v[0] for v in bar_verts]
    ys = [BASE_Y, slope_end[1], wall_end[1], ideal_y, rel_y] + [v[1] for v in bar_verts]
    pad = max(200, (max(xs) - min(xs)) * 0.15, (max(ys) - min(ys)) * 0.15)
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.invert_yaxis()  # 画面座標に合わせて Z↓（下方向が正）
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X (μm)")
    ax.set_ylabel("Z (μm)  ↓")
    ax.set_title(
        f"配置プレビュー（角度 {int(angle_deg)}° / "
        f"{'角度連動' if angle_linked else '画面固定'}）"
    )
    ax.grid(True, ls=":", alpha=0.4)
    ax.legend(loc="best", fontsize=8, framealpha=0.85, markerscale=0.9)
    fig.tight_layout()

    coords = {
        "base": (float(BASE_X), float(BASE_Y)),
        "ideal": (ideal_x, ideal_y),
        "release": (rel_x, rel_y),
    }
    return fig, coords


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


def show_results(mode, output_dir, show_gif=True):
    """実行後に成果物(画像/CSV)を表示する。"""
    out = os.path.join(BASE_DIR, output_dir) if not os.path.isabs(output_dir) else output_dir
    if not os.path.isdir(out):
        st.warning(f"出力フォルダが見つかりません: {out}")
        return

    st.subheader("実行結果")

    if mode == "SINGLE":
        pngs = sorted(
            glob.glob(os.path.join(out, "single_result_*.png")),
            key=os.path.getmtime,
            reverse=True,
        )
        fallback_png = os.path.join(out, "single_condition_result.png")
        latest_png = pngs[0] if pngs else fallback_png if os.path.exists(fallback_png) else None

        st.markdown("**軌跡・最終状態画像**")
        if latest_png:
            st.image(latest_png, caption=os.path.basename(latest_png), use_container_width=True)
            with open(latest_png, "rb") as f:
                st.download_button(
                    "PNG をダウンロード",
                    f,
                    file_name=os.path.basename(latest_png),
                    mime="image/png",
                )
        else:
            st.info("結果画像が見つかりませんでした。")

        st.markdown("**動きのGIF**")
        if show_gif:
            gifs = sorted(
                glob.glob(os.path.join(out, "single_result_*.gif")),
                key=os.path.getmtime,
                reverse=True,
            )
            if gifs:
                latest_gif = gifs[0]
                st.image(latest_gif, caption=os.path.basename(latest_gif), use_container_width=True)
                with open(latest_gif, "rb") as f:
                    st.download_button(
                        "GIF をダウンロード",
                        f,
                        file_name=os.path.basename(latest_gif),
                        mime="image/gif",
                    )
            else:
                st.info("GIFが見つかりませんでした。")
        else:
            st.info("GIF生成はOFFです。")
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
    generate_gif = st.checkbox(
        "SINGLE実行時にGIFを生成する",
        value=bool(S.get("generate_gif", True)),
        help="ONの場合、単一条件実行後にバーの動きをGIFとして保存し、結果欄に表示します。",
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


def common_cfg(angle_linked_offset):
    # angle_linked_offset（オフセットをステージ角度に連動させるか）は各モードの
    # パネル側で指定する。SINGLE/INTERACTIVE/BATCH のUIから渡す。
    return {
        "mode": mode,
        "output_dir": output_dir,
        "simulation_duration": simulation_duration,
        "enable_floor_fail": enable_floor_fail,
        "contact_count_threshold": contact_count_threshold,
        "contact_diff_threshold": contact_diff_threshold,
        "ideal_neighborhood_radius": ideal_neighborhood_radius,
        "angle_linked_offset": bool(angle_linked_offset),
        "generate_gif": generate_gif,
    }


# 共通設定の現在値を永続化用ディクショナリへ反映
S.update({
    "mode": mode,
    "output_dir": output_dir,
    "simulation_duration": float(simulation_duration),
    "enable_floor_fail": bool(enable_floor_fail),
    "generate_gif": bool(generate_gif),
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
    st.caption("リリース X/Z オフセットは『理想位置』を原点(0,0)とした、ずらし量です（offset=0 → 理想位置からリリース）。")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        angle = st.number_input("ステージ角度 (°)", value=int(S.get("single_angle", 30)), step=1)
    with c2:
        rx = st.number_input("リリース X オフセット (μm)", value=int(S.get("single_rx", 0)), step=5)
    with c3:
        ry = st.number_input("リリース Z オフセット (μm)", value=int(S.get("single_ry", 600)), step=5)
    with c4:
        rel = st.number_input("相対リリース角度 (°)", value=int(S.get("single_rel", 0)), step=1)

    angle_linked_offset = st.checkbox(
        "オフセットをステージ角度に連動させる",
        value=bool(S.get("angle_linked_offset", False)),
        help="リリースオフセットの原点は常に『理想位置』です（offset=0 → リリース位置＝理想位置）。"
        "ON にすると、その軸がステージ傾斜に合わせて回転します（Xオフセット=斜面方向 / Zオフセット=壁方向）。",
    )

    S.update({"single_angle": int(angle), "single_rx": int(rx),
              "single_ry": int(ry), "single_rel": int(rel),
              "angle_linked_offset": bool(angle_linked_offset)})

    # --- 実行前プレビュー：台座・理想位置・落下開始位置を図示して確認する ---
    st.markdown("#### 実行前プレビュー（座標確認）")
    _ideal_x, _ideal_y = calc_ideal_position(int(angle))
    _rel_x, _rel_y = compute_release_pos(int(angle), int(rx), int(ry), bool(angle_linked_offset))
    pc1, pc2 = st.columns([3, 2])
    with pc1:
        try:
            _fig, _coords = build_layout_preview(int(angle), int(rx), int(ry),
                                                 bool(angle_linked_offset), int(rel))
            st.pyplot(_fig, use_container_width=True)
            import matplotlib.pyplot as _plt
            _plt.close(_fig)
        except Exception as _e:
            st.warning(f"プレビューの描画に失敗しました: {_e}")
    with pc2:
        st.markdown("**座標（画面座標系・X→右 / Z↓下, 単位 μm）**")
        # 横幅が狭いと1行では値が切れるため、点ごとに X / Y を2列×複数段で表示する。
        for _label, (_px, _py) in (
            ("台座(BASE)", (BASE_X, BASE_Y)),
            ("理想位置", (_ideal_x, _ideal_y)),
            ("落下開始位置", (_rel_x, _rel_y)),
        ):
            st.markdown(f"**{_label}**")
            _cx, _cy = st.columns(2)
            _cx.metric("X (μm)", f"{_px:.1f}")
            _cy.metric("Z (μm)", f"{_py:.1f}")
        _off_dist = math.hypot(_rel_x - _ideal_x, _rel_y - _ideal_y)
        st.caption(
            f"オフセット原点＝理想位置／"
            f"{'ステージ角度に連動' if angle_linked_offset else '画面固定軸'}。"
            f"理想位置→落下開始位置の距離: {_off_dist:.1f} μm（{_off_dist / PPM * 1000:.3f} mm）"
        )

    cfg = common_cfg(angle_linked_offset)
    cfg["single_params"] = {
        "angle": int(angle),
        "release_x_offset": int(rx),
        "release_y_offset": int(ry),
        "relative_angle": int(rel),
    }

    if mode == "SINGLE":
        st.info(f"GIF生成: {'ON（実行後にGIFも表示します）' if generate_gif else 'OFF（PNGのみ表示します）'}")
        if st.button("▶ 実行 (画像生成)", type="primary"):
            with st.spinner("シミュレーション実行中..."):
                rc, log_lines = run_blocking(cfg)
            if rc == 0:
                st.success("完了しました。")
            else:
                st.error(f"異常終了しました (exit={rc})。上のログを確認してください。")
            show_deviation_metrics(log_lines)
            show_contact_metrics(log_lines)
            show_results("SINGLE", output_dir, show_gif=generate_gif)
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
    st.caption("リリース X/Z オフセットは『理想位置』を原点(0,0)とした、ずらし量です。")

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

    st.markdown("**リリース Z オフセット (μm)**")
    y1, y2, y3 = st.columns(3)
    y_start = y1.number_input("Z 開始", value=int(S.get("y_start", 400)), step=5, key="ys")
    y_stop = y2.number_input("Z 終了(未満)", value=int(S.get("y_stop", 1000)), step=5, key="ye")
    y_step = y3.number_input("Z 刻み", value=int(S.get("y_step", 50)), min_value=1, step=5, key="yst")

    rel_text = st.text_input("相対リリース角度のリスト (カンマ区切り)", value=str(S.get("rel_text", "0")))

    angle_linked_offset = st.checkbox(
        "オフセットをステージ角度に連動させる",
        value=bool(S.get("angle_linked_offset", False)),
        help="リリースオフセットの原点は常に『理想位置』です（offset=0 → リリース位置＝理想位置）。"
        "ON にすると、その軸がステージ傾斜に合わせて回転します（Xオフセット=斜面方向 / Zオフセット=壁方向）。"
        "※ BATCH_PARALLEL では main.py の既定値が使われ、この指定は反映されません。",
    )
    S.update({"angle_linked_offset": bool(angle_linked_offset)})

    t1, t2 = st.columns(2)
    num_trials = t1.number_input("各条件の試行回数", min_value=1, value=int(S.get("num_trials", 10)), step=1)

    with st.expander("リリース位置・角度のバラツキ（標準偏差）", expanded=False):
        v1, v2, v3 = st.columns(3)
        var_x = v1.number_input("X バラツキ (μm)", min_value=0.0, value=float(S.get("var_x", 0.0)), step=1.0)
        var_y = v2.number_input("Z バラツキ (μm)", min_value=0.0, value=float(S.get("var_y", 0.0)), step=1.0)
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
            f"条件数: {n_cond}（角度 {n_angle} × X {n_x} × Z {n_y} × 相対角 {n_rel}） "
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

    cfg = common_cfg(angle_linked_offset)
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

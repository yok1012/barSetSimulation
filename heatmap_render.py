# -*- coding: utf-8 -*-
"""
BATCH ヒートマップの軸目盛り・オーバーレイ描画（共用モジュール）。

main.py の generate_heatmaps()（本番出力）と streamlit_app.py の
実行前プレビューの両方から使う。pygame に依存しない matplotlib 描画のみを置く。

ここの幾何定数は main.py（BASE_X/BASE_Y, SLOPE_LENGTH, 壁高さ,
BAR_WIDTH*PPM, BAR_HEIGHT*PPM, calculate_ideal_position）と
一致させること。
"""
import math

from matplotlib.patches import Polygon

# --- 幾何定数（main.py と一致させること） ---
BASE_X, BASE_Y = 2000, 2000          # 台座（斜面と壁の角）座標 [μm]
SLOPE_LENGTH = 1500                   # 斜面長さ [μm]
WALL_HEIGHT = 1000                    # 壁の高さ [μm]
IDEAL_RADIUS = 508.069                # 理想位置の円弧半径 [μm]
IDEAL_ANGLE_BASE_DEG = 276.259234     # 理想位置角度 = この値 - ステージ角度
BAR_W_UM = 100.0                      # バー短辺 [μm]（main.BAR_WIDTH * PPM）
BAR_H_UM = 1000.0                     # バー長辺 [μm]（main.BAR_HEIGHT * PPM）

# --- オーバーレイ表示の既定オプション ---
DEFAULT_OVERLAY_OPTIONS = {
    "show_stage": True,        # 壁・斜面・台座(BASE)の線と凡例
    "show_ideal_bar": True,    # 理想バーの輪郭・落下開始点・中心マーカー
    "show_dimensions": True,   # 寸法矢印（長さ・幅）
    "show_crosshair": True,    # 基準点(0,0)の点線と注記テキスト
    "show_cell_values": True,  # セル内の成功率数値（呼び出し側で使用）
    "max_ticks": 12,           # 軸目盛りの最大表示数
}

# セル数がこれを超える場合、成功率数値は表示しない（読めない上に描画が重いため）
CELL_VALUE_LIMIT = 2500


def calc_ideal_position(angle_deg):
    """理想位置（バー中心）[μm]。main.calculate_ideal_position と同一の式。"""
    rad = math.radians(IDEAL_ANGLE_BASE_DEG - angle_deg)
    return BASE_X + IDEAL_RADIUS * math.cos(rad), BASE_Y + IDEAL_RADIUS * math.sin(rad)


def rect_vertices(pos, size, angle):
    """中心 pos・寸法 size の矩形を angle 回転した4頂点（main.get_rect_vertices と同一）。"""
    w, h = size
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    pts = []
    for dw, dh in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append((pos[0] + dw * cos_a - dh * sin_a, pos[1] + dw * sin_a + dh * cos_a))
    return pts


def bar_lower_left(pos, size, angle):
    """バー中心・寸法・角度から、ローカル左下端の座標を返す。"""
    return rect_vertices(pos, size, angle)[3]


def offset_to_index(values, target):
    """実オフセット値を imshow のセル座標へ線形変換する。範囲外は端の間隔で外挿。"""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return None
    for i in range(len(vals) - 1):
        left, right = vals[i], vals[i + 1]
        if left <= target <= right and right != left:
            return i + (target - left) / (right - left)
    if target < vals[0]:
        step = vals[1] - vals[0]
    else:
        step = vals[-1] - vals[-2]
    if step == 0:
        return None
    if target < vals[0]:
        return (target - vals[0]) / step
    return (len(vals) - 1) + (target - vals[-1]) / step


def make_offset_mapper(angle_deg, angle_linked):
    """物理(画面)座標 → ヒートマップオフセット座標への変換関数などを返す。

    ヒートマップの各セルは「バー左下端（台座の角に接する点）」の位置として
    解釈する。基準点(0,0)は理想位置リリース時のバー左下端（≒台座BASEの角）。
    リリースオフセットとバー左下端の移動量は平行移動で一致するため、
    セル値と図形の位置関係がそのまま実際の位置関係になる。
    """
    stage_angle_rad = math.radians(-angle_deg)
    ideal = calc_ideal_position(angle_deg)
    ll_x, ll_y = bar_lower_left(ideal, (BAR_W_UM, BAR_H_UM), stage_angle_rad)
    cos_t, sin_t = math.cos(stage_angle_rad), math.sin(stage_angle_rad)

    def to_offset(px, py):
        dx, dy = px - ll_x, py - ll_y
        if angle_linked:
            return dx * cos_t + dy * sin_t, dx * sin_t - dy * cos_t
        return dx, -dy

    return to_offset, ideal, stage_angle_rad


def set_heatmap_ticks(ax, x_positions, y_positions, max_ticks=12):
    """軸目盛りを最大 max_ticks 個に間引いて読みやすくする。

    従来は全セルに目盛りラベルを付けていたため、刻みが細かいと
    ラベルが重なって判読不能になっていた。
    """
    max_ticks = max(2, int(max_ticks))

    def thin_indices(n):
        if n <= max_ticks:
            return list(range(n))
        step = max(1, math.ceil((n - 1) / (max_ticks - 1)))
        idx = list(range(0, n, step))
        if idx[-1] != n - 1:
            if (n - 1) - idx[-1] >= step / 2:
                idx.append(n - 1)
            else:
                idx[-1] = n - 1
        return idx

    xi = thin_indices(len(x_positions))
    yi = thin_indices(len(y_positions))
    ax.set_xticks(xi)
    ax.set_xticklabels([f"{float(x_positions[i]):g}" for i in xi], rotation=45)
    ax.set_yticks(yi)
    ax.set_yticklabels([f"{float(y_positions[i]):g}" for i in yi])


def cell_values_visible(x_positions, y_positions, options=None):
    """セル内の成功率数値を表示すべきか（オプションON かつ セル数が上限以下）。"""
    opts = dict(DEFAULT_OVERLAY_OPTIONS, **(options or {}))
    return (opts.get("show_cell_values", True)
            and len(x_positions) * len(y_positions) <= CELL_VALUE_LIMIT)


def draw_overlays(ax, x_positions, y_positions, angle_deg, angle_linked,
                  jp_font=None, options=None):
    """理想バー・壁・斜面・台座などのオーバーレイをオプションに応じて重ねる。

    座標基準は「バー左下端（台座の角に接する点）」のオフセット。
    原点(0,0)＝理想リリース時のバー左下端（≒台座BASEの角）。
    """
    opts = dict(DEFAULT_OVERLAY_OPTIONS, **(options or {}))
    if len(x_positions) < 2 or len(y_positions) < 2:
        return
    to_offset, ideal_center, stage_angle_rad = make_offset_mapper(angle_deg, angle_linked)
    if opts.get("show_ideal_bar") or opts.get("show_dimensions") or opts.get("show_crosshair"):
        _draw_ideal_bar(ax, x_positions, y_positions, to_offset, ideal_center,
                        stage_angle_rad, jp_font, opts)
    if opts.get("show_stage"):
        _draw_stage(ax, x_positions, y_positions, to_offset, stage_angle_rad, jp_font,
                    angle_linked)


def _draw_ideal_bar(ax, x_positions, y_positions, to_offset, ideal_center,
                    stage_angle_rad, jp_font, opts):
    """理想リリース時のバー輪郭・マーカー・寸法矢印・基準線を重ねる。"""
    bar_w, bar_h = BAR_W_UM, BAR_H_UM
    x_vals = [float(v) for v in x_positions]
    z_vals = [float(v) for v in y_positions]

    def in_view(ox, oz):
        return (x_vals[0] <= ox <= x_vals[-1]
                and z_vals[0] <= oz <= z_vals[-1])

    def map_offset(ox, oz):
        ix = offset_to_index(x_positions, ox)
        iy = offset_to_index(y_positions, oz)
        if ix is None or iy is None:
            return None
        return ix, iy

    def draw_dimension(start, end, label, label_t=0.5, label_shift_pts=(6, 6)):
        """物理座標2点間の寸法矢印。両端が表示範囲内のときだけ描く。

        label_t は矢印上のラベル位置（0=始点, 0.5=中点, 1=終点）。
        ラベルのずらし量はポイント単位（グリッドの細かさに依存しない）。
        """
        o0, o1 = to_offset(*start), to_offset(*end)
        if not (in_view(*o0) and in_view(*o1)):
            return False
        p0, p1 = map_offset(*o0), map_offset(*o1)
        if p0 is None or p1 is None:
            return False
        ax.annotate(
            "",
            xy=p1,
            xytext=p0,
            arrowprops=dict(
                arrowstyle="<->",
                color="black",
                linestyle="--",
                linewidth=1.4,
                shrinkA=0,
                shrinkB=0,
            ),
        )
        lx = p0[0] + (p1[0] - p0[0]) * label_t
        ly = p0[1] + (p1[1] - p0[1]) * label_t
        ax.annotate(
            label, xy=(lx, ly), xytext=label_shift_pts,
            textcoords="offset points",
            color="black", fontsize=8,
            bbox=dict(facecolor="white", alpha=0.8, edgecolor="none"),
            fontproperties=jp_font,
        )
        return True

    # 原点(0,0) = 理想リリース時のバー左下端（≒台座BASEの角）
    origin_idx = map_offset(0.0, 0.0)
    origin_visible = origin_idx is not None and in_view(0.0, 0.0)
    if opts.get("show_crosshair"):
        info_lines = [
            "基準点(0,0): バー左下端（理想リリース時）",
            f"寸法: 長さ {bar_h:.0f} μm / 幅 {bar_w:.0f} μm",
        ]
        if not origin_visible:
            info_lines.append("※基準点(0,0)は表示範囲外")
        ax.text(
            0.02, 0.98, "\n".join(info_lines),
            transform=ax.transAxes,
            ha="left", va="top",
            color="black", fontsize=8,
            bbox=dict(facecolor="white", alpha=0.78, edgecolor="none"),
            fontproperties=jp_font,
        )
        if origin_visible:
            ax.axvline(origin_idx[0], color="black", linestyle=":", linewidth=1.4, alpha=0.9)
            ax.axhline(origin_idx[1], color="black", linestyle=":", linewidth=1.4, alpha=0.9)

    verts_phys = rect_vertices(ideal_center, (bar_w, bar_h), stage_angle_rad)

    if opts.get("show_ideal_bar"):
        # 理想リリース時のバー輪郭（表示範囲外の部分は自動的にクリップされる）
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        verts_idx = [map_offset(*to_offset(vx, vy)) for vx, vy in verts_phys]
        if all(v is not None for v in verts_idx):
            ax.add_patch(Polygon(
                verts_idx,
                closed=True,
                fill=False,
                edgecolor="black",
                linestyle="--",
                linewidth=2.0,
                alpha=0.95,
            ))
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)

    if opts.get("show_dimensions"):
        # 寸法矢印: 対向する辺の中点どうしを結ぶ
        v0, v1, v2, v3 = verts_phys

        def mid(a, b):
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

        draw_dimension(mid(v0, v1), mid(v3, v2), f"長さ {bar_h:.0f} μm", label_t=0.25)
        draw_dimension(mid(v0, v3), mid(v1, v2), f"幅 {bar_w:.0f} μm",
                       label_shift_pts=(14, 14))

    if opts.get("show_ideal_bar"):
        # 落下開始点（バー左下端）= 原点(0,0)
        if origin_visible:
            ax.plot(
                origin_idx[0], origin_idx[1],
                marker="o", markersize=8,
                markerfacecolor="magenta",
                markeredgecolor="purple",
                markeredgewidth=1.3,
            )
            ax.annotate(
                "落下開始(左下端)", xy=origin_idx, xytext=(8, 8),
                textcoords="offset points",
                color="purple", fontsize=8,
                bbox=dict(facecolor="white", alpha=0.8, edgecolor="none"),
                fontproperties=jp_font,
            )

        # バー中心の位置
        center_off = to_offset(*ideal_center)
        if in_view(*center_off):
            center_idx = map_offset(*center_off)
            if center_idx is not None:
                ax.plot(center_idx[0], center_idx[1], marker="+", color="black",
                        markersize=9, markeredgewidth=1.6, alpha=0.75)
                ax.annotate(
                    "中心", xy=center_idx, xytext=(6, -18),
                    textcoords="offset points",
                    color="black", fontsize=8,
                    bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"),
                    fontproperties=jp_font,
                )


def _draw_stage(ax, x_positions, y_positions, to_offset, stage_angle_rad, jp_font,
                angle_linked=False):
    """Singleモードのプレビューと同じイメージで、壁・斜面（台座）・BASEマーカーを重ねる。

    angle_linked=True のときは軸自体がステージ傾斜に連動して回転するため、
    斜面は常に水平・壁は常に垂直に描かれる（どの角度でも見た目が同じになるのは仕様）。
    誤解を避けるため凡例にその旨を明記する。"""

    def map_point(px, py):
        ox, oz = to_offset(px, py)
        ix = offset_to_index(x_positions, ox)
        iy = offset_to_index(y_positions, oz)
        if ix is None or iy is None:
            return None
        return ix, iy

    slope_end = (BASE_X + SLOPE_LENGTH * math.cos(stage_angle_rad),
                 BASE_Y + SLOPE_LENGTH * math.sin(stage_angle_rad))
    wall_angle = stage_angle_rad - math.pi / 2
    wall_end = (BASE_X + WALL_HEIGHT * math.cos(wall_angle),
                BASE_Y + WALL_HEIGHT * math.sin(wall_angle))

    base_idx = map_point(BASE_X, BASE_Y)
    slope_idx = map_point(*slope_end)
    wall_idx = map_point(*wall_end)
    if base_idx is None:
        return

    # 線がヒートマップ範囲外へ伸びても表示範囲が広がらないよう、描画後に元へ戻す
    xlim, ylim = ax.get_xlim(), ax.get_ylim()

    def segment_in_view(p0, p1):
        """線分がヒートマップ表示範囲と交差するか（Liang-Barsky法）。"""
        x_lo, x_hi = min(xlim), max(xlim)
        y_lo, y_hi = min(ylim), max(ylim)
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, p0[0] - x_lo), (dx, x_hi - p0[0]),
                     (-dy, p0[1] - y_lo), (dy, y_hi - p0[1])):
            if p == 0:
                if q < 0:
                    return False
            else:
                t = q / p
                if p < 0:
                    t0 = max(t0, t)
                else:
                    t1 = min(t1, t)
                if t0 > t1:
                    return False
        return True

    def point_in_view(pt):
        return (min(xlim) <= pt[0] <= max(xlim)
                and min(ylim) <= pt[1] <= max(ylim))

    # 表示範囲外の要素は凡例に載せない（描画自体は matplotlib がクリップする）
    any_visible = False
    if slope_idx is not None:
        visible = segment_in_view(base_idx, slope_idx)
        any_visible = any_visible or visible
        ax.plot([base_idx[0], slope_idx[0]], [base_idx[1], slope_idx[1]],
                color="#555555", lw=3, zorder=3,
                label="斜面(台座)" if visible else "_nolegend_")
    if wall_idx is not None:
        visible = segment_in_view(base_idx, wall_idx)
        any_visible = any_visible or visible
        ax.plot([base_idx[0], wall_idx[0]], [base_idx[1], wall_idx[1]],
                color="#aaaaaa", lw=3, zorder=3,
                label="壁" if visible else "_nolegend_")
    base_visible = point_in_view(base_idx)
    any_visible = any_visible or base_visible
    ax.plot(base_idx[0], base_idx[1], marker="P", color="red",
            markersize=11, linestyle="none", zorder=4,
            label="台座(BASE)" if base_visible else "_nolegend_")
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    if any_visible:
        legend_kwargs = dict(loc="lower right", fontsize=8, framealpha=0.85)
        if angle_linked:
            legend_kwargs["title"] = "軸はステージ傾斜に連動\n（斜面=水平/壁=垂直 表示）"
        if jp_font:
            legend_font = jp_font.copy()
            legend_font.set_size(8)
            legend_kwargs["prop"] = legend_font
        legend = ax.legend(**legend_kwargs)
        if angle_linked and jp_font:
            legend.get_title().set_fontproperties(legend_font)

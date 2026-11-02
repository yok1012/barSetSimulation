"""落下終了時の位置・姿勢誤差を、成功判定とは独立に集計する。"""
import math


def pose_errors(position, angle, ideal_position, ideal_angle):
    dx, dy = position[0] - ideal_position[0], position[1] - ideal_position[1]
    # 長方形の軸方向を比較。180度反転は同じ姿勢とする。
    tilt = abs((math.degrees(angle - ideal_angle) + 90) % 180 - 90)
    return math.hypot(dx, dy), tilt


def summarize_pose(trials, ideal_position, ideal_angle):
    values = [pose_errors(t['final_pos'], t['final_angle'], ideal_position, ideal_angle)
              for t in trials if t.get('final_pos') is not None and t.get('final_angle') is not None]
    count = len(values)
    return dict(pose_samples=count,
                mean_position_error_um=sum(v[0] for v in values) / count if count else None,
                mean_alignment_error_deg=sum(v[1] for v in values) / count if count else None)


def edges(values):
    """実際の座標間隔を保つセル境界。単一点の場合の表示幅は1μm。"""
    if len(values) == 1:
        return [values[0] - .5, values[0] + .5]
    middle = [(a + b) / 2 for a, b in zip(values, values[1:])]
    return [values[0] - (middle[0] - values[0]), *middle,
            values[-1] + (values[-1] - middle[-1])]


def render_maps(frame, output_dir):
    """同一ステージ角・初期相対角ごとに2種類のPNGを保存する。"""
    from pathlib import Path
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    if frame.empty or 'mean_position_error_um' not in frame:
        return []
    # 条件リストは同一座標で物理係数が異なり得る。平均で潰さず対象外にする。
    if 'condition_index' in frame:
        return []
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for (angle, relative), part in frame.groupby(['angle', 'relative_angle']):
        xs = sorted(part.release_x_offset.unique())
        ys = sorted(part.release_y_offset.unique())
        if len(xs) * len(ys) > 2_000_000:
            raise ValueError('カラーマップは1枚200万セルまでです。角度や探索範囲を分割してください')
        for column, name, label in (
            ('mean_position_error_um', 'position_error', 'Mean position error (um)'),
            ('mean_alignment_error_deg', 'alignment_error', 'Mean axis alignment error (deg)'),
        ):
            grid = part.pivot(index='release_y_offset', columns='release_x_offset', values=column).reindex(index=ys, columns=xs)
            values = np.ma.masked_invalid(grid.to_numpy(dtype=float))
            vmax = (float(frame[column].max()) if frame[column].notna().any() else 1.0) if name == 'position_error' else 90.0
            cmap = plt.get_cmap('viridis').with_extremes(bad='#bdbdbd')
            fig, ax = plt.subplots(figsize=(9, 7))
            try:
                mesh = ax.pcolormesh(edges(xs), edges(ys), values, cmap=cmap, vmin=0, vmax=max(vmax, 1e-9), shading='flat')
                linked = bool(part.iloc[0].get('angle_linked_offset', False))
                ax.set_xlabel('Release X offset from ideal (um)' + (' [stage axis]' if linked else ''))
                ax.set_ylabel('Release Z offset from ideal (um)' + (' [wall axis]' if linked else ''))
                ax.set_title(f'{label}\nStage={angle:g} deg, initial relative={relative:g} deg; gray=no samples')
                fig.colorbar(mesh, ax=ax, label=label)
                fig.tight_layout()
                path = output / f'{name}_stage_{angle:g}_relative_{relative:g}.png'
                fig.savefig(path, dpi=150)
                paths.append(path)
            finally:
                plt.close(fig)
    return paths

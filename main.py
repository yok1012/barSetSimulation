import pygame
import pymunk
import pymunk.pygame_util
import math
import itertools
import os
import random

# --- ライブラリのインポートチェック ---
try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns

    LIBRARIES_INSTALLED = True
except ImportError:
    LIBRARIES_INSTALLED = False

# --- 並列処理ライブラリのインポート ---
try:
    import multiprocessing as mp
    from multiprocessing import Pool, cpu_count
    import time
    PARALLEL_AVAILABLE = True
except ImportError:
    PARALLEL_AVAILABLE = False

# --- モード設定 ---
# "INTERACTIVE": リアルタイムで条件変更・結果確認ができるモード
# "BATCH":       複数条件を自動で試行し、結果をファイル出力するモード
# "SINGLE":      単一条件の初期/最終状態を画像出力するモード
# "BATCH_PARALLEL" 並列処理
MODE = "INTERACTIVE"

# --- 出力フォルダ ---
OUTPUT_DIR = "results_err8"
JP_FONT_FILENAME = "ipaexg.ttf"

# --- シミュレーション基本設定 ---
BAR_FRICTION = 2.7
BAR_ELASTICITY = 0.6
WALL_FRICTION = 1.2
WALL_ELASTICITY = 0.6
INTERACTIVE_SUBSTEPS = 10
BAR_HEIGHT = 0.001      # 1mm = 0.001m → 1000 pixels
BAR_WIDTH = 0.0001      # 0.1mm = 0.0001m → 100 pixels
BAR_MASS = 0.00000001   # 10^-8 kg (体積が10^-6倍になるため質量も調整)
WIDTH, HEIGHT = 4000, 4000  # 4mm × 4mm (1 pixel = 1 μm)
PPM = 1000000.0         # 1,000,000 pixels/m = 1 pixel/μm
SIMULATION_DURATION = 4.0
ENABLE_FLOOR_FAIL_VALIDATION = True

# --- 判定閾値設定 ---
CONTACT_COUNT_THRESHOLD = 3      # 短冊方向の接触回数閾値（これ以上でNG判定対象）
CONTACT_DIFF_THRESHOLD = 100.0     # 接触位置の累積差分閾値（μm）（これを超えたらNG）

# --- 各モード用の設定 ---
BATCH_PARAM_RANGES = {'angle': range(20, 21, 1), 'release_x_offset': range(-600, 300, 10),
                      'release_y_offset': range(200, 1000, 10), 'relative_angle': [0]}  # 相対角度は固定
# バラツキ設定：X, Y位置、相対角度の標準偏差（1 pixel = 1 μm）
RELEASE_X_VARIABILITY = 20  # X位置のバラツキ 20μm
RELEASE_Y_VARIABILITY = 20  # Y位置のバラツキ 20μm
RELATIVE_ANGLE_VARIABILITY = 1.0  # 相対角度のバラツキ（度）
NUM_TRIALS_PER_CONDITION = 30  # 各条件での試行回数
SINGLE_CONDITION_PARAMS = {'angle': 30, 'release_x_offset': 0, 'release_y_offset': 600, 'relative_angle': 0}

# --- 衝突判定用の種別ID ---
BAR_COLLISION_TYPE = 1;
STAGE_COLLISION_TYPE = 2;
FLOOR_COLLISION_TYPE = 3;
WALL_COLLISION_TYPE = 4

# --- 判定基準 ---
SUCCESS_CRITERIA = {
    'max_velocity': 1.0,              # 最大線速度 1.0 m/s
    'max_angular_velocity': 0.5,      # 最大角速度 0.5 rad/s
    'angle_tolerance_rad': math.radians(1.0),  # 角度許容誤差 1度
    'min_settle_time': 1.0,           # 最小安定時間 1.0秒
    'position_tolerance': 10.0        # 理想位置からの許容誤差 10μm (10 pixels)
}
BASE_X, BASE_Y, SLOPE_LENGTH = 2000, 2000, 1500  # pixels = μm (画面中央, 斜面長さ1.5mm)


### --- ヘルパー関数群 ---
def setup_space(space, slope_angle_rad, is_visual):
    static_body = space.static_body;
    static_shapes = []
    slope_end_x = BASE_X + SLOPE_LENGTH * math.cos(slope_angle_rad);
    slope_end_y = BASE_Y + SLOPE_LENGTH * math.sin(slope_angle_rad)
    slope_segment = pymunk.Segment(static_body, (BASE_X, BASE_Y), (slope_end_x, slope_end_y), 5)
    slope_segment.friction = WALL_FRICTION;
    slope_segment.elasticity = WALL_ELASTICITY;
    slope_segment.collision_type = STAGE_COLLISION_TYPE
    static_shapes.append(slope_segment)
    wall_height = 1000;  # 1000μm = 1mm
    wall_angle = slope_angle_rad - math.pi / 2
    wall_end_x = BASE_X + wall_height * math.cos(wall_angle);
    wall_end_y = BASE_Y + wall_height * math.sin(wall_angle)
    wall_segment = pymunk.Segment(static_body, (BASE_X, BASE_Y), (wall_end_x, wall_end_y), 5)
    wall_segment.friction = WALL_FRICTION;
    wall_segment.elasticity = WALL_ELASTICITY;
    wall_segment.collision_type = WALL_COLLISION_TYPE
    static_shapes.append(wall_segment)
    if is_visual:
        for shape in static_shapes: shape.color = pygame.Color("darkgrey")
    space.add(*static_shapes)
    floor = pymunk.Segment(static_body, (0, HEIGHT - 2), (WIDTH, HEIGHT - 2), 5)
    floor.collision_type = FLOOR_COLLISION_TYPE;
    floor.friction = 0.9;
    floor.elasticity = 0.5
    other_walls = [pymunk.Segment(static_body, (0, 0), (WIDTH, 0), 5),
                   pymunk.Segment(static_body, (0, 0), (0, HEIGHT), 5),
                   pymunk.Segment(static_body, (WIDTH, 0), (WIDTH, HEIGHT), 5)]
    for wall in other_walls: wall.friction = 0.5; wall.elasticity = 0.5
    space.add(floor, *other_walls);
    static_shapes.extend([floor] + other_walls)
    return slope_segment, wall_segment, floor


def create_bar(space, pos, angle, is_visual):
    body = pymunk.Body(BAR_MASS, pymunk.moment_for_box(BAR_MASS, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM)))
    body.position = pos;
    body.angle = angle
    shape = pymunk.Poly.create_box(body, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM), 0.0)
    shape.friction = BAR_FRICTION;
    shape.elasticity = BAR_ELASTICITY;
    shape.collision_type = BAR_COLLISION_TYPE
    if is_visual: shape.color = pygame.Color("dodgerblue")
    space.add(body, shape)
    return shape


def check_success(bar_shape, slope_segment, wall_segment, slope_angle_rad, floor_was_hit, settle_time=None):
    """バーの成功判定を行う（より厳格な基準）"""
    if ENABLE_FLOOR_FAIL_VALIDATION and floor_was_hit: return False, "床に接触"
    body = bar_shape.body
    
    # 速度・角速度の安定性チェック
    is_stable = (body.velocity.length < SUCCESS_CRITERIA['max_velocity'] and 
                 abs(body.angular_velocity) < SUCCESS_CRITERIA['max_angular_velocity'])
    if not is_stable: return False, "不安定"
    
    # 角度の正確性チェック
    is_angle_correct = abs(body.angle - slope_angle_rad) < SUCCESS_CRITERIA['angle_tolerance_rad']
    if not is_angle_correct: return False, "角度不正"
    
    # 安定時間チェック（新規追加）
    if settle_time is not None and settle_time < SUCCESS_CRITERIA['min_settle_time']:
        return False, "安定時間不足"
    
    # 理想位置からの誤差チェック（新規追加）
    if 'position_tolerance' in SUCCESS_CRITERIA:
        ideal_x, ideal_y = calculate_ideal_position(slope_angle_rad)
        actual_x, actual_y = body.position.x, body.position.y
        position_error = math.sqrt((ideal_x - actual_x)**2 + (ideal_y - actual_y)**2)
        if position_error > SUCCESS_CRITERIA['position_tolerance']:
            return False, "位置誤差大"
    
    if slope_segment is None or wall_segment is None: return False, "ステージ未定義"

    touching_slope = False

    # 別の方法で接触判定を行う - space.shape_queryを使用
    space = bar_shape.space
    if space:
        # バーと接触している全てのシェイプを取得
        contacts = space.shape_query(bar_shape)
        for contact_info in contacts:
            other_shape = contact_info.shape
            if other_shape == slope_segment: touching_slope = True

    # 未接触判定を緩和：斜面接触のみで成功とする
    if not touching_slope: return False, "未接触"
    # 壁面接触は必須ではない（より緩い条件）
    return True, "成功"


def check_initial_position(space, pos, angle):
    temp_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC);
    temp_body.position = pos;
    temp_body.angle = angle
    temp_shape = pymunk.Poly.create_box(temp_body, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM))
    static_collisions = [i for i in space.shape_query(temp_shape) if
                         i.shape and i.shape.body.body_type == pymunk.Body.STATIC]
    return not static_collisions


def calculate_ideal_position(stage_angle_rad):
    """
    バーが壁と斜面の両方に接触している理想的な位置を計算
    実測データに正確に合わせた計算（符号修正済み）
    """
    # stage_angle_radは負の値なので、絶対値を取ってUI表示角度と合わせる
    stage_angle_deg = abs(math.degrees(stage_angle_rad))

    # ステージの基点(2000,2000)を中心とした円弧運動
    center_x = BASE_X  # 2000μm
    center_y = BASE_Y  # 2000μm

    # 実測値から計算した半径（1 pixel = 1 μm）
    # 実測データ（30度）から逆算: sqrt(204.548^2 + 465.074^2) = 508.069 μm
    radius = 508.069  # 508.069μm = 0.508mm

    # 実測データに基づく角度関係
    # 実測データ（30度）から逆算: atan2(-465.074, -204.548) + 30 = 276.259234°
    # 理想位置角度 = 276.259234° - ステージ角度
    # (新スケール: 1 pixel = 1 μm)
    ideal_angle_deg = 276.259234 - stage_angle_deg
    ideal_angle_rad = math.radians(ideal_angle_deg)
    
    # 円弧上の位置を計算
    ideal_x = center_x + radius * math.cos(ideal_angle_rad)
    ideal_y = center_y + radius * math.sin(ideal_angle_rad)
    
    return ideal_x, ideal_y


def get_rect_vertices(pos, size, angle):
    w, h = size;
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    vertices = []
    for dw, dh in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
        rx, ry = dw * cos_a - dh * sin_a, dw * sin_a + dh * cos_a
        vertices.append((pos[0] + rx, pos[1] + ry))
    return vertices


def check_bar_contact_side(bar_body, wall_segment, contact_point):
    """
    バーのどの面（長手方向か短手方向）が壁に接触しているかを判定する
    複数面の同時接触も適切に検知する
    
    Args:
        bar_body: バーの物理ボディ
        wall_segment: 壁のセグメント
        contact_point: 接触点の座標
    
    Returns:
        str: "long_side" (長手方向), "short_side" (短手方向), "both" (両方), "unknown" (不明)
    """
    if not contact_point:
        return "unknown"
    
    bar_pos = bar_body.position
    bar_angle = bar_body.angle
    
    # バーの中心から接触点への相対位置を計算
    rel_x = contact_point[0] - bar_pos.x
    rel_y = contact_point[1] - bar_pos.y
    
    # バーのローカル座標系に変換
    cos_a, sin_a = math.cos(-bar_angle), math.sin(-bar_angle)
    local_x = rel_x * cos_a - rel_y * sin_a
    local_y = rel_x * sin_a + rel_y * cos_a
    
    # バーのサイズ（幅と高さ）
    bar_width_px = BAR_WIDTH * PPM
    bar_height_px = BAR_HEIGHT * PPM
    
    # 閾値を調整（より厳密な判定）
    width_threshold = bar_width_px * 0.25   # 幅の25%
    height_threshold = bar_height_px * 0.25  # 高さの25%
    
    # 各面への接触を個別に判定
    long_side_contact = abs(local_x) > width_threshold
    short_side_contact = abs(local_y) > height_threshold
    
    # 両方の面に接触している場合
    if long_side_contact and short_side_contact:
        return "both"
    # 長手方向の面（左右の面）のみ接触
    elif long_side_contact:
        return "long_side"
    # 短手方向の面（上下の面）のみ接触
    elif short_side_contact:
        return "short_side"
    else:
        return "unknown"



def draw_coordinates(surface, font):
    grid_color = pygame.Color("lightgray");
    label_color = pygame.Color("gray")
    for x in range(0, WIDTH, 100):
        pygame.draw.line(surface, grid_color, (x, 0), (x, HEIGHT))
        surface.blit(font.render(str(x), True, label_color), (x + 5, 5))
    for y in range(0, HEIGHT, 100):
        pygame.draw.line(surface, grid_color, (0, y), (WIDTH, y))
        surface.blit(font.render(str(y), True, label_color), (5, y + 5))


### --- モード別実行関数 ---
def run_interactive_mode():
    pygame.init()
    pygame.key.set_repeat(400, 30)
    try:
        font = pygame.font.Font(JP_FONT_FILENAME, 20); font_large = pygame.font.Font(JP_FONT_FILENAME,
                                                                                     48); font_small = pygame.font.Font(
            JP_FONT_FILENAME, 18); font_coords = pygame.font.Font(JP_FONT_FILENAME, 16)
    except pygame.error:
        font = pygame.font.Font(None, 24); font_large = pygame.font.Font(None, 60); font_small = pygame.font.Font(None,
                                                                                                                  20); font_coords = pygame.font.Font(
            None, 20)

    # 表示倍率機能を追加 - 画面サイズに合わせて自動調整
    display_info = pygame.display.Info()
    screen_width = display_info.current_w
    screen_height = display_info.current_h

    # 画面サイズの90%に収まるように初期倍率を計算（タスクバーやウィンドウ装飾を考慮）
    max_scale_x = (screen_width * 0.9) / WIDTH
    max_scale_y = (screen_height * 0.9) / HEIGHT
    display_scale = min(max_scale_x, max_scale_y, 1.0)  # 最大100%

    display_width = int(WIDTH * display_scale)
    display_height = int(HEIGHT * display_scale)

    # 画面はリサイズ可能な縮小サイズで作成
    screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)
    # 描画用は実サイズのサーフェス
    draw_surface = pygame.Surface((WIDTH, HEIGHT))

    clock = pygame.time.Clock()
    pygame.display.set_caption("インタラクティブ・シミュレーション (拡大縮小対応)")
    draw_options = pymunk.pygame_util.DrawOptions(draw_surface)

    space = pymunk.Space();
    space.gravity = (0, 981)
    params = SINGLE_CONDITION_PARAMS.copy()
    dynamic_bars, static_shapes = [], []
    editing_param, input_buffer = None, "";
    param_rects = {}
    last_result, result_color, last_diff = None, (0, 0, 0), None
    settle_frames_count, bar_is_settled = 0, False
    initial_pos_ok, floor_hit_flag = True, [False]
    floor_hit_alert_timer = 0  # 床接触アラートの表示タイマー
    floor_hit_position = None  # 床接触時のバーの位置
    floor_hit_angle = None  # 床接触時のバーの角度
    enable_sound_alert = True  # 音声アラートのオン/オフ
    wall_hit_flag = [False]  # 壁面早期接触フラグ
    wall_hit_alert_timer = 0  # 壁面接触アラートの表示タイマー
    wall_hit_position = None  # 壁面接触時のバーの位置
    wall_hit_angle = None  # 壁面接触時のバーの角度
    short_side_contact_count = 0  # 短冊方向の接触回数
    accumulated_contact_diff = 0.0 # 接触位置の累積差分
    multiple_contact_alert_timer = 0  # 複数回接触アラートの表示タイマー
    contact_history = []  # 接触履歴を記録

    def floor_contact_handler(arbiter, space, data):
        data["hit_flag"][0] = True
        # 床接触時のバーの位置と角度を記録
        if dynamic_bars:
            data["hit_position"] = dynamic_bars[0].body.position.x, dynamic_bars[0].body.position.y
            data["hit_angle"] = dynamic_bars[0].body.angle
        return True

    handler = space.add_collision_handler(BAR_COLLISION_TYPE, FLOOR_COLLISION_TYPE);
    handler.begin = floor_contact_handler;
    handler.data["hit_flag"] = floor_hit_flag
    handler.data["hit_position"] = None
    handler.data["hit_angle"] = None
    
    def wall_contact_handler(arbiter, space, data):
        nonlocal short_side_contact_count, contact_history, accumulated_contact_diff
        
        # バーがまだ安定していない場合のみチェック
        if not bar_is_settled and dynamic_bars:
            # 接触点を取得
            contact_points = arbiter.contact_point_set.points
            if contact_points:
                contact_point = contact_points[0].point_a  # 最初の接触点を使用
                
                # バーのどの面が接触しているかを判定
                contact_side = check_bar_contact_side(dynamic_bars[0].body, None, contact_point)
                
                # 短冊方向の接触を処理（"short_side" または "both"）
                if contact_side in ["short_side", "both"]:
                    # 以前の接触点との距離を計算
                    diff = 0.0
                    if contact_history:
                        last_time, last_point = contact_history[-1]
                        diff = math.sqrt((contact_point[0] - last_point[0])**2 + (contact_point[1] - last_point[1])**2)
                    
                    # 差分を積算
                    accumulated_contact_diff += diff
                    
                    # カウントと履歴を更新
                    short_side_contact_count += 1
                    contact_history.append((pygame.time.get_ticks(), contact_point))
                    
                    # デバッグ情報を追加
                    print(f"短冊接触検出: {contact_side}, 回数: {short_side_contact_count}, 位置: ({contact_point[0]:.1f}, {contact_point[1]:.1f}), 差分: {diff:.3f}, 累積: {accumulated_contact_diff:.3f}")
                    
                    data["contact_count"] = short_side_contact_count
                    
                    # 2回以上の短冊方向接触 かつ 累積差分が閾値を超えたらNG
                    if short_side_contact_count >= CONTACT_COUNT_THRESHOLD and accumulated_contact_diff > CONTACT_DIFF_THRESHOLD:
                        data["hit_flag"][0] = True
                        data["hit_position"] = dynamic_bars[0].body.position.x, dynamic_bars[0].body.position.y
                        data["hit_angle"] = dynamic_bars[0].body.angle
                        data["contact_side"] = "multiple_short_side"
                        data["contact_point"] = contact_point
        return True
    
    wall_handler = space.add_collision_handler(BAR_COLLISION_TYPE, WALL_COLLISION_TYPE);
    wall_handler.begin = wall_contact_handler;
    wall_handler.data["hit_flag"] = wall_hit_flag
    wall_handler.data["hit_position"] = None
    wall_handler.data["hit_angle"] = None
    wall_handler.data["contact_side"] = None
    wall_handler.data["contact_point"] = None
    wall_handler.data["contact_count"] = 0

    def get_release_angles():
        stage_angle_rad = math.radians(-params['angle']);
        relative_angle_rad = math.radians(-params.get('relative_angle', 0))
        return stage_angle_rad, stage_angle_rad + relative_angle_rad

    def reset_simulation(full_reset=True, check_pos=True):
        nonlocal last_result, settle_frames_count, bar_is_settled, static_shapes, initial_pos_ok, last_diff
        nonlocal floor_hit_alert_timer, floor_hit_position, floor_hit_angle
        nonlocal short_side_contact_count, accumulated_contact_diff, multiple_contact_alert_timer, contact_history
        stage_angle_rad, actual_release_angle_rad = get_release_angles()
        if full_reset:
            for shape in dynamic_bars: space.remove(shape, shape.body)
            dynamic_bars.clear();
            for shape in static_shapes: space.remove(shape)
            static_shapes.clear();
            static_shapes = list(setup_space(space, stage_angle_rad, is_visual=True))
        release_pos = (BASE_X + params['release_x_offset'], BASE_Y - params['release_y_offset'])
        if check_pos: initial_pos_ok = check_initial_position(space, release_pos, actual_release_angle_rad)
        if not full_reset or not check_pos:
            for shape in dynamic_bars: space.remove(shape, shape.body)
            dynamic_bars.clear()
        if initial_pos_ok: dynamic_bars.append(create_bar(space, release_pos, actual_release_angle_rad, is_visual=True))
        last_result, settle_frames_count, bar_is_settled, last_diff = None, 0, False, None;
        floor_hit_flag[0] = False
        floor_hit_alert_timer = 0
        floor_hit_position = None
        floor_hit_angle = None
        handler.data["hit_position"] = None
        wall_hit_flag[0] = False
        wall_handler.data["hit_position"] = None
        wall_handler.data["hit_angle"] = None
        wall_handler.data["contact_side"] = None
        wall_handler.data["contact_point"] = None
        wall_handler.data["contact_count"] = 0
        # 接触回数をリセット
        short_side_contact_count = 0
        accumulated_contact_diff = 0.0
        multiple_contact_alert_timer = 0
        contact_history.clear()
        handler.data["hit_angle"] = None

    reset_simulation(full_reset=True)
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if editing_param:
                        editing_param, input_buffer = None, ""
                    else:
                        running = False
                elif event.key == pygame.K_r:
                    reset_simulation(full_reset=False)
                elif editing_param:
                    if event.key == pygame.K_RETURN:
                        try:
                            params[editing_param] = int(input_buffer)
                            reset_simulation(full_reset=True) if editing_param == 'angle' else reset_simulation(
                                full_reset=False, check_pos=True)
                        except ValueError:
                            pass
                        editing_param, input_buffer = None, ""
                    elif event.key == pygame.K_BACKSPACE:
                        input_buffer = input_buffer[:-1]
                    elif event.unicode.isdigit() or (event.unicode == '-' and not input_buffer):
                        input_buffer += event.unicode
                else:
                    shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[
                        pygame.K_RSHIFT]
                    increment = 5 if shift_pressed else 1
                    config_changed, angle_changed = False, False
                    if event.key == pygame.K_w: params[
                        'angle'] += increment; config_changed = True; angle_changed = True
                    if event.key == pygame.K_s: params[
                        'angle'] -= increment; config_changed = True; angle_changed = True
                    if event.key == pygame.K_UP: params['release_y_offset'] += increment; config_changed = True
                    if event.key == pygame.K_DOWN: params['release_y_offset'] -= increment; config_changed = True
                    if event.key == pygame.K_RIGHT: params['release_x_offset'] += increment; config_changed = True
                    if event.key == pygame.K_LEFT: params['release_x_offset'] -= increment; config_changed = True
                    if event.key == pygame.K_e: params['relative_angle'] -= increment; config_changed = True
                    if event.key == pygame.K_q: params['relative_angle'] += increment; config_changed = True
                    if event.key == pygame.K_m: enable_sound_alert = not enable_sound_alert  # M キーで音声アラートのオン/オフ

                    # 表示倍率の変更（+/-キー、またはテンキー）
                    if event.key in [pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS]:
                        display_scale = min(1.0, display_scale + 0.1)  # 最大100%
                        display_width = int(WIDTH * display_scale)
                        display_height = int(HEIGHT * display_scale)
                        screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)
                    if event.key in [pygame.K_MINUS, pygame.K_KP_MINUS]:
                        display_scale = max(0.2, display_scale - 0.1)  # 最小20%
                        display_width = int(WIDTH * display_scale)
                        display_height = int(HEIGHT * display_scale)
                        screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)

                    if config_changed: reset_simulation(full_reset=angle_changed)
            if event.type == pygame.MOUSEWHEEL:
                # マウスホイールでズーム操作
                if event.y > 0:  # 上にスクロール = ズームイン
                    display_scale = min(1.0, display_scale + 0.1)
                    display_width = int(WIDTH * display_scale)
                    display_height = int(HEIGHT * display_scale)
                    screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)
                elif event.y < 0:  # 下にスクロール = ズームアウト
                    display_scale = max(0.2, display_scale - 0.1)
                    display_width = int(WIDTH * display_scale)
                    display_height = int(HEIGHT * display_scale)
                    screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)
            if event.type == pygame.VIDEORESIZE:
                # ウィンドウがリサイズされたときの処理
                display_width = event.w
                display_height = event.h
                # アスペクト比を維持しながら表示倍率を計算
                scale_x = display_width / WIDTH
                scale_y = display_height / HEIGHT
                display_scale = min(scale_x, scale_y)  # 小さい方を採用してアスペクト比を維持
                # 実際のウィンドウサイズを倍率に合わせて調整
                display_width = int(WIDTH * display_scale)
                display_height = int(HEIGHT * display_scale)
                screen = pygame.display.set_mode((display_width, display_height), pygame.RESIZABLE)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # UI要素のクリック判定（screen座標系をそのまま使用）
                mouse_pos = event.pos
                if editing_param and not param_rects.get(editing_param, pygame.Rect(0, 0, 0, 0)).collidepoint(mouse_pos):
                    editing_param, input_buffer = None, ""
                for p_name, rect in param_rects.items():
                    if rect.collidepoint(mouse_pos): editing_param, input_buffer = p_name, ""; break

        # 短冊方向複数回接触の処理
        if wall_hit_flag[0] and not bar_is_settled:
            # 複数回短冊方向接触の場合
            if wall_handler.data.get("contact_side") == "multiple_short_side":
                multiple_contact_alert_timer = 120  # 2秒間表示（60FPS）
                # 音声アラート
                if enable_sound_alert and LIBRARIES_INSTALLED:
                    try:
                        # ビープ音を生成（660Hz, 0.2秒 - 複数回接触は中音域）
                        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                        beep = pygame.sndarray.make_sound(np.array(
                            [int(32767.0 * np.sin(2.0 * np.pi * 660.0 * i / 22050.0)) 
                             for i in range(int(22050 * 0.2))], dtype=np.int16
                        ).repeat(2).reshape(-1, 2))
                        beep.play()
                    except:
                        pass  # 音声が使えない場合は無視
        
        if ENABLE_FLOOR_FAIL_VALIDATION and floor_hit_flag[0] and not bar_is_settled:
            bar_is_settled = True;
            last_result, result_color = "床に接触", (220, 0, 0)
            floor_hit_alert_timer = 120  # 2秒間表示（60FPS）
            # 床接触時の位置を記録
            if handler.data["hit_position"]:
                floor_hit_position = handler.data["hit_position"]
                floor_hit_angle = handler.data["hit_angle"]
            # 音声アラート（pygame.mixerとnumpyが使用可能な場合）
            if enable_sound_alert and LIBRARIES_INSTALLED:
                try:
                    # ビープ音を生成（440Hz, 0.2秒）
                    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                    beep = pygame.sndarray.make_sound(np.array(
                        [int(32767.0 * np.sin(2.0 * np.pi * 440.0 * i / 22050.0)) 
                         for i in range(int(22050 * 0.2))], dtype=np.int16
                    ).repeat(2).reshape(-1, 2))
                    beep.play()
                except:
                    pass  # 音声が使えない場合は無視
        if dynamic_bars and not bar_is_settled:
            bar_body = dynamic_bars[0].body
            if bar_body.velocity.length < 0.5 and abs(bar_body.angular_velocity) < 0.5:
                settle_frames_count += 1
            else:
                settle_frames_count = 0
            if settle_frames_count > 30:
                bar_is_settled = True;
                stage_angle_rad, _ = get_release_angles()
                slope_seg, wall_seg, _ = static_shapes[0], static_shapes[1], static_shapes[2]
                is_success, reason = check_success(dynamic_bars[0], slope_seg, wall_seg, stage_angle_rad,
                                                   floor_hit_flag[0])
                last_result, result_color = reason, (0, 180, 0) if is_success else (220, 0, 0)

                # 詳細情報を出力
                ideal_x, ideal_y = calculate_ideal_position(stage_angle_rad)
                actual_x, actual_y = bar_body.position.x, bar_body.position.y
                diff = math.sqrt((ideal_x - actual_x) ** 2 + (ideal_y - actual_y) ** 2)
                dist_base_to_bar = math.sqrt((actual_x - BASE_X)**2 + (actual_y - BASE_Y)**2)
                dist_base_to_ideal = math.sqrt((ideal_x - BASE_X)**2 + (ideal_y - BASE_Y)**2)

                # 接触状態の確認
                touching_slope = False
                touching_wall = False
                contact_points_slope = []
                contact_points_wall = []

                space = dynamic_bars[0].space
                if space:
                    contacts = space.shape_query(dynamic_bars[0])
                    for contact_info in contacts:
                        other_shape = contact_info.shape
                        if other_shape == slope_seg:
                            touching_slope = True
                            # 接触点を取得
                            try:
                                if hasattr(contact_info, 'contact_point_set'):
                                    for point in contact_info.contact_point_set.points:
                                        contact_points_slope.append((point.point_a.x, point.point_a.y))
                            except:
                                pass
                        if other_shape == wall_seg:
                            touching_wall = True
                            # 接触点を取得
                            try:
                                if hasattr(contact_info, 'contact_point_set'):
                                    for point in contact_info.contact_point_set.points:
                                        contact_points_wall.append((point.point_a.x, point.point_a.y))
                            except:
                                pass

                print("\n" + "="*80)
                print("バー安定時の詳細情報")
                print("="*80)
                print(f"【結果】 {reason} (成功: {is_success})")
                print()
                print("--- 基本設定 ---")
                print(f"PPM (Pixels Per Meter): {PPM}")
                print(f"1 pixel = {1000000/PPM:.3f} μm")
                print(f"ステージ基点 BASE: ({BASE_X}, {BASE_Y}) μm")
                print()
                print("--- ステージ情報 ---")
                print(f"ステージ角度: {math.degrees(stage_angle_rad):.3f}° (rad: {stage_angle_rad:.6f})")
                print(f"斜面長さ (SLOPE_LENGTH): {SLOPE_LENGTH} μm")
                print(f"壁の高さ: 1000 μm")
                print(f"セグメント半径（厚み）: 5 μm（直径10 μm）")
                print()
                print("--- バー情報 ---")
                print(f"バーサイズ: {BAR_HEIGHT*1000000:.1f} × {BAR_WIDTH*1000000:.1f} μm ({BAR_HEIGHT*1000:.3f} × {BAR_WIDTH*1000:.3f} mm)")
                print(f"バー質量: {BAR_MASS} kg")
                print(f"バー重心位置: ({actual_x:.3f}, {actual_y:.3f}) μm")
                print(f"バーの角度: {math.degrees(bar_body.angle):.3f}° (rad: {bar_body.angle:.6f})")
                print(f"バーの速度: {bar_body.velocity.length:.6f} (基準: {SUCCESS_CRITERIA['max_velocity']})")
                print(f"バーの角速度: {abs(bar_body.angular_velocity):.6f} (基準: {SUCCESS_CRITERIA['max_angular_velocity']})")
                print()
                print("--- 理想位置情報 ---")
                print(f"理想位置の計算半径 (radius): {570.0} μm")
                print(f"理想位置の角度: {285.0 - abs(math.degrees(stage_angle_rad)):.3f}°")
                print(f"理想位置: ({ideal_x:.3f}, {ideal_y:.3f}) μm")
                print()
                print("--- 距離計算 ---")
                print(f"BASE → バー重心: {dist_base_to_bar:.3f} μm")
                print(f"BASE → 理想位置: {dist_base_to_ideal:.3f} μm")
                print(f"理想位置 → バー重心（位置誤差）: {diff:.3f} μm")
                print(f"位置誤差の許容範囲: {SUCCESS_CRITERIA['position_tolerance']:.1f} μm")
                print()
                print("--- 位置差分（成分別） ---")
                print(f"X方向差分: {actual_x - ideal_x:.3f} μm")
                print(f"Y方向差分: {actual_y - ideal_y:.3f} μm")
                print(f"BASE からの X差分: {actual_x - BASE_X:.3f} μm")
                print(f"BASE からの Y差分: {actual_y - BASE_Y:.3f} μm")
                print()
                print("--- 接触状態 ---")
                print(f"斜面接触: {touching_slope}")
                print(f"壁面接触: {touching_wall}")
                if contact_points_slope:
                    print(f"斜面接触点数: {len(contact_points_slope)}")
                    for i, (cx, cy) in enumerate(contact_points_slope):
                        print(f"  接触点{i+1}: ({cx:.3f}, {cy:.3f}) μm")
                if contact_points_wall:
                    print(f"壁面接触点数: {len(contact_points_wall)}")
                    for i, (cx, cy) in enumerate(contact_points_wall):
                        print(f"  接触点{i+1}: ({cx:.3f}, {cy:.3f}) μm")
                print()
                print("--- バーの形状（コーナー位置） ---")
                bar_vertices = get_rect_vertices(bar_body.position, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM), bar_body.angle)
                for i, (vx, vy) in enumerate(bar_vertices):
                    print(f"  コーナー{i+1}: ({vx:.3f}, {vy:.3f}) μm")
                print()
                print("--- 成功判定基準 ---")
                print(f"最大線速度: {SUCCESS_CRITERIA['max_velocity']} m/s")
                print(f"最大角速度: {SUCCESS_CRITERIA['max_angular_velocity']} rad/s")
                print(f"角度許容誤差: {math.degrees(SUCCESS_CRITERIA['angle_tolerance_rad']):.3f}°")
                print(f"最小安定時間: {SUCCESS_CRITERIA['min_settle_time']} s")
                print(f"位置許容誤差: {SUCCESS_CRITERIA['position_tolerance']} μm")
                print("="*80)
                print()

                if is_success:
                    last_diff = f"理想位置との差分: {diff / PPM:.3f} mm"

        # ===== 物理オブジェクトの描画（スケール変換される） =====
        draw_surface.fill(pygame.Color("white"));
        draw_coordinates(draw_surface, font_coords);


        # 床接触時のバーを赤くハイライト表示
        if floor_hit_position and floor_hit_angle is not None and floor_hit_alert_timer > 0:
            # 半透明の赤いバーを描画
            hit_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            hit_vertices = get_rect_vertices(floor_hit_position, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM), floor_hit_angle)
            # 点滅効果（アラートタイマーに基づいて透明度を変更）
            if LIBRARIES_INSTALLED:
                alpha = 180 + int(75 * np.sin(floor_hit_alert_timer * 0.3))
            else:
                # numpy不使用時は単純な点滅
                alpha = 255 if (floor_hit_alert_timer // 10) % 2 == 0 else 180
            pygame.draw.polygon(hit_surf, (255, 0, 0, alpha), hit_vertices)
            pygame.draw.polygon(hit_surf, (200, 0, 0, 255), hit_vertices, 3)  # 赤い枠線
            draw_surface.blit(hit_surf, (0, 0))

        space.debug_draw(draw_options)
        release_pos = (BASE_X + params['release_x_offset'], BASE_Y - params['release_y_offset'])
        marker_color = (128, 0, 128) if not initial_pos_ok else (255, 0, 0)
        pygame.draw.line(draw_surface, marker_color, (release_pos[0] - 10, release_pos[1]),
                         (release_pos[0] + 10, release_pos[1]), 2)
        pygame.draw.line(draw_surface, marker_color, (release_pos[0], release_pos[1] - 10),
                         (release_pos[0], release_pos[1] + 10), 2)
        _, actual_release_angle_rad = get_release_angles()
        line_end_x = release_pos[0] + 25 * math.cos(actual_release_angle_rad);
        line_end_y = release_pos[1] + 25 * math.sin(actual_release_angle_rad)
        pygame.draw.line(draw_surface, marker_color, release_pos, (line_end_x, line_end_y), 2)
        # 物理空間のマーカーとラベルを描画（スケール変換される）
        # データの計算と物理空間マーカーの描画
        position_error = 0
        error_color = (220, 100, 0)
        debug_texts = []
        if dynamic_bars:
            stage_angle_rad, _ = get_release_angles()
            ideal_x, ideal_y = calculate_ideal_position(stage_angle_rad)
            bar_body = dynamic_bars[0].body
            actual_x, actual_y = bar_body.position.x, bar_body.position.y
            position_error = math.sqrt((ideal_x - actual_x)**2 + (ideal_y - actual_y)**2)
            error_color = (0, 150, 0) if position_error <= SUCCESS_CRITERIA['position_tolerance'] else (220, 100, 0)

            # デバッグ情報を準備（後でUI描画で使用）
            stage_angle_deg = math.degrees(stage_angle_rad)
            dist_base_to_bar = math.sqrt((actual_x - BASE_X)**2 + (actual_y - BASE_Y)**2)
            dist_base_to_ideal = math.sqrt((ideal_x - BASE_X)**2 + (ideal_y - BASE_Y)**2)
            debug_texts = [
                f"ステージ角度: {-stage_angle_deg:.1f}°",
                f"理想位置: ({ideal_x:.1f}, {ideal_y:.1f}) μm",
                f"実際位置: ({actual_x:.1f}, {actual_y:.1f}) μm",
                f"差分: X={actual_x-ideal_x:.1f}, Y={actual_y-ideal_y:.1f} μm",
                f"BASE: ({BASE_X}, {BASE_Y}) μm",
                f"BASE→Bar距離: {dist_base_to_bar:.1f} μm",
                f"BASE→Ideal距離: {dist_base_to_ideal:.1f} μm"
            ]

            # ゼロ点から理想位置・バー重心への線
            pygame.draw.line(draw_surface, (100, 200, 100), (int(BASE_X), int(BASE_Y)), (int(ideal_x), int(ideal_y)), 1)
            pygame.draw.line(draw_surface, (150, 150, 150), (int(BASE_X), int(BASE_Y)), (int(actual_x), int(actual_y)), 1)
            pygame.draw.line(draw_surface, error_color, (int(ideal_x), int(ideal_y)), (int(actual_x), int(actual_y)), 2)

            # ゼロ点（ステージ基点）をマーカーで表示（赤色）
            pygame.draw.circle(draw_surface, (255, 0, 0), (int(BASE_X), int(BASE_Y)), 8, 2)
            pygame.draw.line(draw_surface, (255, 0, 0), (int(BASE_X)-12, int(BASE_Y)), (int(BASE_X)+12, int(BASE_Y)), 2)
            pygame.draw.line(draw_surface, (255, 0, 0), (int(BASE_X), int(BASE_Y)-12), (int(BASE_X), int(BASE_Y)+12), 2)
            base_label = font_small.render("BASE(0,0)", True, (255, 0, 0))
            draw_surface.blit(base_label, (int(BASE_X) + 15, int(BASE_Y) - 10))

            # バーの重心位置をマーカーで表示（青色）
            pygame.draw.circle(draw_surface, (0, 0, 255), (int(actual_x), int(actual_y)), 6, 2)
            pygame.draw.line(draw_surface, (0, 0, 255), (int(actual_x)-10, int(actual_y)), (int(actual_x)+10, int(actual_y)), 2)
            pygame.draw.line(draw_surface, (0, 0, 255), (int(actual_x), int(actual_y)-10), (int(actual_x), int(actual_y)+10), 2)
            bar_label = font_small.render("Bar Center", True, (0, 0, 255))
            draw_surface.blit(bar_label, (int(actual_x) + 15, int(actual_y) - 10))

            # 理想位置をマーカーで表示（緑色）
            pygame.draw.circle(draw_surface, (0, 255, 0), (int(ideal_x), int(ideal_y)), 5, 2)
            pygame.draw.line(draw_surface, (0, 255, 0), (int(ideal_x)-10, int(ideal_y)), (int(ideal_x)+10, int(ideal_y)), 1)
            pygame.draw.line(draw_surface, (0, 255, 0), (int(ideal_x), int(ideal_y)-10), (int(ideal_x), int(ideal_y)+10), 1)
            ideal_label = font_small.render("Ideal Pos", True, (0, 255, 0))
            draw_surface.blit(ideal_label, (int(ideal_x) + 15, int(ideal_y) - 10))

        # ===== スケール変換 =====
        scaled_surface = pygame.transform.scale(draw_surface, (display_width, display_height))
        screen.blit(scaled_surface, (0, 0))

        # ===== UI要素の描画（固定サイズ、スケール変換されない） =====
        # パラメータ表示（左上）
        param_labels = {"angle": "ステージ角度", "relative_angle": "相対リリース角度", "release_x_offset": "リリース X",
                        "release_y_offset": "リリース Y"}
        y_offset = 10
        for p_name, label in param_labels.items():
            color = (0, 0, 200) if editing_param == p_name else (0, 0, 0)
            text = f"{label}: {input_buffer if editing_param == p_name else params.get(p_name, 0)}"
            if editing_param == p_name and pygame.time.get_ticks() % 1000 < 500: text += "_"
            img = font.render(text, True, color)
            rect = screen.blit(img, (10, y_offset))
            # param_rectsはクリック判定用（screen座標系）
            param_rects[p_name] = rect
            y_offset += 25
        y_offset += 5
        pygame.draw.line(screen, (100, 100, 100), (10, y_offset), (300, y_offset), 1)
        y_offset += 5

        # ヘルプテキスト
        help_texts = ["操作方法:", "矢印キー: リリース位置", "W/S: ステージ角度", "Q/E: 相対リリース角度",
                      "Shift+キー: 高速変更", "+/-/ホイール: 表示倍率", "R: 再落下", "M: 音声 " + ("ON" if enable_sound_alert else "OFF"), "クリック: 数値入力",
                      f"短冊方向接触回数: {short_side_contact_count} (2回以上でアラート)", f"表示倍率: {int(display_scale*100)}%"]
        for text in help_texts:
            screen.blit(font.render(text, True, (0, 0, 0)), (10, y_offset))
            y_offset += 22
        if not initial_pos_ok:
            screen.blit(font.render("初期位置が不正です！", True, (128, 0, 128)), (10, y_offset))

        # マーカーの凡例を表示
        y_offset += 10
        pygame.draw.line(screen, (100, 100, 100), (10, y_offset), (300, y_offset), 1)
        y_offset += 10
        screen.blit(font_small.render("マーカー凡例:", True, (0, 0, 0)), (10, y_offset))
        y_offset += 20
        pygame.draw.circle(screen, (255, 0, 0), (25, y_offset), 6, 2)
        screen.blit(font_small.render("BASE(0,0) - ステージ基点", True, (255, 0, 0)), (40, y_offset - 8))
        y_offset += 20
        pygame.draw.circle(screen, (0, 0, 255), (25, y_offset), 6, 2)
        screen.blit(font_small.render("Bar Center - バー重心位置", True, (0, 0, 255)), (40, y_offset - 8))
        y_offset += 20
        pygame.draw.circle(screen, (0, 255, 0), (25, y_offset), 6, 2)
        screen.blit(font_small.render("Ideal Pos - 理想位置", True, (0, 255, 0)), (40, y_offset - 8))

        # 位置誤差の表示（右上）
        if dynamic_bars:
            error_text = f"位置誤差: {position_error:.1f} μm"
            error_surf = font.render(error_text, True, error_color)
            screen.blit(error_surf, (display_width - error_surf.get_width() - 20, 110))

            # 許容誤差の表示
            tolerance_text = f"許容誤差: {SUCCESS_CRITERIA['position_tolerance']:.0f} μm"
            tolerance_surf = font_small.render(tolerance_text, True, (100, 100, 100))
            screen.blit(tolerance_surf, (display_width - tolerance_surf.get_width() - 20, 135))

            # デバッグ情報（右側）
            debug_colors = [(200, 0, 0), (50, 50, 50), (50, 50, 50), (50, 50, 50), (100, 100, 100), (0, 0, 200), (0, 200, 0)]
            for i, (text, color) in enumerate(zip(debug_texts, debug_colors)):
                screen.blit(font_small.render(text, True, color), (display_width - 350, 140 + i * 20))

        # 結果表示（右上）
        if last_result:
            img = font_large.render(last_result, True, result_color)
            screen.blit(img, (display_width - img.get_width() - 20, 20))
            if last_diff:
                screen.blit(font_small.render(last_diff, True, (0, 0, 0)),
                           (display_width - font_small.size(last_diff)[0] - 20, 80))

        # 複数回短冊方向接触アラート（中央）
        if multiple_contact_alert_timer > 0:
            alert_text = "短冊方向複数回接触！"
            alert_surf = font_large.render(alert_text, True, (255, 0, 100))
            alert_rect = alert_surf.get_rect(center=(display_width // 2, display_height // 2 - 100))

            bg_surf = pygame.Surface((alert_rect.width + 80, alert_rect.height + 20), pygame.SRCALPHA)
            if LIBRARIES_INSTALLED:
                bg_alpha = 200 + int(55 * np.sin(multiple_contact_alert_timer * 0.4))
            else:
                bg_alpha = 255 if (multiple_contact_alert_timer // 10) % 2 == 0 else 200
            bg_surf.fill((255, 0, 100, bg_alpha))
            screen.blit(bg_surf, (alert_rect.x - 40, alert_rect.y - 10))
            screen.blit(alert_surf, alert_rect)

            detail_text = f"短冊方向の壁面接触が{short_side_contact_count}回発生しました"
            detail_surf = font_small.render(detail_text, True, (255, 255, 255))
            detail_rect = detail_surf.get_rect(center=(display_width // 2, display_height // 2 - 60))
            screen.blit(detail_surf, detail_rect)

            multiple_contact_alert_timer -= 1

        # 床接触アラート（中央）
        if floor_hit_alert_timer > 0:
            alert_text = "床接触！"
            alert_surf = font_large.render(alert_text, True, (255, 0, 0))
            alert_rect = alert_surf.get_rect(center=(display_width // 2, display_height // 2))

            bg_surf = pygame.Surface((alert_rect.width + 40, alert_rect.height + 20), pygame.SRCALPHA)
            if LIBRARIES_INSTALLED:
                bg_alpha = 200 + int(55 * np.sin(floor_hit_alert_timer * 0.3))
            else:
                bg_alpha = 255 if (floor_hit_alert_timer // 10) % 2 == 0 else 200
            bg_surf.fill((255, 50, 50, bg_alpha))
            screen.blit(bg_surf, (alert_rect.x - 20, alert_rect.y - 10))
            screen.blit(alert_surf, alert_rect)

            detail_text = "バーが床に接触しました"
            detail_surf = font_small.render(detail_text, True, (255, 255, 255))
            detail_rect = detail_surf.get_rect(center=(display_width // 2, display_height // 2 + 40))
            screen.blit(detail_surf, detail_rect)

            floor_hit_alert_timer -= 1

        pygame.display.flip()
        dt = 1.0 / 60.0
        for _ in range(INTERACTIVE_SUBSTEPS): space.step(dt / INTERACTIVE_SUBSTEPS)
        clock.tick(60)
    pygame.quit()


def run_single_condition_mode():
    print(f"単一条件モードを実行します。パラメータ: {SINGLE_CONDITION_PARAMS}")
    os.environ['SDL_VIDEODRIVER'] = 'dummy';
    pygame.init()
    surface = pygame.Surface((WIDTH, HEIGHT));
    draw_options = pymunk.pygame_util.DrawOptions(surface)
    try:
        font_coords = pygame.font.Font(JP_FONT_FILENAME, 16)
    except pygame.error:
        font_coords = pygame.font.Font(None, 20)
    params = SINGLE_CONDITION_PARAMS;
    stage_angle_rad = math.radians(-params['angle']);
    relative_angle_rad = math.radians(-params.get('relative_angle', 0))
    actual_release_angle_rad = stage_angle_rad + relative_angle_rad
    release_pos = (BASE_X + params['release_x_offset'], BASE_Y - params['release_y_offset'])
    space = pymunk.Space();
    space.gravity = (0, 981)
    setup_space(space, stage_angle_rad, is_visual=True)
    if not check_initial_position(space, release_pos, actual_release_angle_rad):
        print("警告: 指定された初期位置は壁やステージにめり込んでいます。")
    bar = create_bar(space, release_pos, actual_release_angle_rad, is_visual=True)
    for _ in range(int(SIMULATION_DURATION / (1.0 / 60.0))): space.step(1.0 / 60.0)
    surface.fill(pygame.Color("white"));
    draw_coordinates(surface, font_coords)
    space.debug_draw(draw_options)
    initial_vertices = get_rect_vertices(release_pos, (BAR_WIDTH * PPM, BAR_HEIGHT * PPM), actual_release_angle_rad)
    initial_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.polygon(initial_surf, (30, 144, 255, 128), initial_vertices)
    surface.blit(initial_surf, (0, 0))
    filepath = os.path.join(OUTPUT_DIR, "single_condition_result.png")
    pygame.image.save(surface, filepath);
    pygame.quit()
    print(f"- 結果を '{filepath}' に保存しました。")


def generate_heatmaps(df):
    """
    角度ごとにX,Y位置の成功率ヒートマップを生成する
    インタラクティブ機能付き（カーソルでX,Y,成功率を表示）
    """
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm
    from matplotlib.font_manager import FontProperties
    
    # 日本語フォントの設定
    try:
        jp_font = FontProperties(fname=JP_FONT_FILENAME)
    except:
        jp_font = None
    
    # 角度のユニーク値を取得
    angles = sorted(df['angle'].unique())
    
    # 図のサイズを計算（3列にする）
    n_angles = len(angles)
    n_cols = 3
    n_rows = (n_angles + n_cols - 1) // n_cols
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 5 * n_rows))
    if n_rows == 1:
        axes = axes.reshape(1, -1)
    
    # 各角度についてヒートマップを作成
    for idx, angle in enumerate(angles):
        row = idx // n_cols
        col = idx % n_cols
        ax = axes[row, col]
        
        # 該当角度のデータを抽出
        angle_data = df[df['angle'] == angle]
        
        # X,Y位置のユニーク値を取得
        x_positions = sorted(angle_data['release_x_offset'].unique())
        y_positions = sorted(angle_data['release_y_offset'].unique())
        
        # 成功率マトリックスを作成
        success_matrix = np.zeros((len(y_positions), len(x_positions)))
        
        for i, y_pos in enumerate(y_positions):
            for j, x_pos in enumerate(x_positions):
                # 該当する条件のデータを取得
                condition_data = angle_data[
                    (angle_data['release_x_offset'] == x_pos) & 
                    (angle_data['release_y_offset'] == y_pos)
                ]
                
                if len(condition_data) > 0:
                    success_matrix[i, j] = condition_data['success_rate'].values[0]
                else:
                    success_matrix[i, j] = np.nan
        
        # ヒートマップを描画
        im = ax.imshow(success_matrix, cmap='RdYlGn', vmin=0, vmax=100, 
                      aspect='auto', origin='lower')
        
        # 軸の設定
        ax.set_xticks(range(len(x_positions)))
        ax.set_yticks(range(len(y_positions)))
        ax.set_xticklabels(x_positions, rotation=45)
        ax.set_yticklabels(y_positions)
        
        # 成功率の値を各セルに表示
        for i in range(len(y_positions)):
            for j in range(len(x_positions)):
                if not np.isnan(success_matrix[i, j]):
                    text = ax.text(j, i, f'{success_matrix[i, j]:.0f}',
                                 ha="center", va="center", color="black", fontsize=8)
        
        # タイトルとラベル
        if jp_font:
            ax.set_title(f'ステージ角度: {angle}°', fontproperties=jp_font, fontsize=14)
            ax.set_xlabel('リリース X位置', fontproperties=jp_font)
            ax.set_ylabel('リリース Y位置', fontproperties=jp_font)
        else:
            ax.set_title(f'Stage Angle: {angle}°', fontsize=14)
            ax.set_xlabel('Release X Position')
            ax.set_ylabel('Release Y Position')
        
        # カラーバーを追加
        cbar = plt.colorbar(im, ax=ax)
        if jp_font:
            cbar.set_label('成功率 (%)', fontproperties=jp_font)
        else:
            cbar.set_label('Success Rate (%)')
    
    # 余分な軸を非表示
    for idx in range(n_angles, n_rows * n_cols):
        row = idx // n_cols
        col = idx % n_cols
        axes[row, col].axis('off')
    
    # レイアウトの調整
    plt.tight_layout()
    
    # 保存
    heatmap_filepath = os.path.join(OUTPUT_DIR, "success_rate_heatmaps.png")
    plt.savefig(heatmap_filepath, dpi=150, bbox_inches='tight')
    plt.close()
    
    # インタラクティブな個別ヒートマップを生成
    for angle in angles:
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # 該当角度のデータを抽出
        angle_data = df[df['angle'] == angle]
        x_positions = sorted(angle_data['release_x_offset'].unique())
        y_positions = sorted(angle_data['release_y_offset'].unique())
        
        # 成功率マトリックスを作成
        success_matrix = np.zeros((len(y_positions), len(x_positions)))
        
        for i, y_pos in enumerate(y_positions):
            for j, x_pos in enumerate(x_positions):
                condition_data = angle_data[
                    (angle_data['release_x_offset'] == x_pos) & 
                    (angle_data['release_y_offset'] == y_pos)
                ]
                
                if len(condition_data) > 0:
                    success_matrix[i, j] = condition_data['success_rate'].values[0]
                else:
                    success_matrix[i, j] = np.nan
        
        # ヒートマップを描画
        im = ax.imshow(success_matrix, cmap='RdYlGn', vmin=0, vmax=100, 
                      aspect='auto', origin='lower')
        
        # 軸の設定
        ax.set_xticks(range(len(x_positions)))
        ax.set_yticks(range(len(y_positions)))
        ax.set_xticklabels(x_positions, rotation=45)
        ax.set_yticklabels(y_positions)
        
        # タイトルとラベル
        if jp_font:
            ax.set_title(f'ステージ角度 {angle}° の成功率分布（インタラクティブ）', fontproperties=jp_font, fontsize=16)
            ax.set_xlabel('リリース X位置', fontproperties=jp_font, fontsize=12)
            ax.set_ylabel('リリース Y位置', fontproperties=jp_font, fontsize=12)
        else:
            ax.set_title(f'Success Rate Distribution for Stage Angle {angle}° (Interactive)', fontsize=16)
            ax.set_xlabel('Release X Position', fontsize=12)
            ax.set_ylabel('Release Y Position', fontsize=12)
        
        # カラーバー
        cbar = plt.colorbar(im, ax=ax)
        if jp_font:
            cbar.set_label('成功率 (%)', fontproperties=jp_font, fontsize=12)
        else:
            cbar.set_label('Success Rate (%)', fontsize=12)
        
        # インタラクティブ機能：マウスカーソルで値を表示
        def on_hover(event):
            if event.inaxes == ax:
                # マウス位置をマトリックス座標に変換
                x_idx = int(round(event.xdata)) if event.xdata is not None else None
                y_idx = int(round(event.ydata)) if event.ydata is not None else None
                
                if (x_idx is not None and y_idx is not None and 
                    0 <= x_idx < len(x_positions) and 0 <= y_idx < len(y_positions)):
                    
                    x_pos = x_positions[x_idx]
                    y_pos = y_positions[y_idx]
                    success_rate = success_matrix[y_idx, x_idx]
                    
                    if not np.isnan(success_rate):
                        # タイトルを更新してマウス位置の情報を表示
                        title_text = f'角度: {angle}° | X: {x_pos}, Y: {y_pos} | 成功率: {success_rate:.1f}%'
                        if jp_font:
                            ax.set_title(title_text, fontproperties=jp_font, fontsize=14)
                        else:
                            ax.set_title(title_text, fontsize=14)
                        fig.canvas.draw_idle()
        
        # マウスイベントを接続
        fig.canvas.mpl_connect('motion_notify_event', on_hover)
        
        plt.tight_layout()
        
        # 保存
        individual_filepath = os.path.join(OUTPUT_DIR, f"heatmap_interactive_angle_{angle}deg.png")
        plt.savefig(individual_filepath, dpi=150, bbox_inches='tight')
        
        # インタラクティブ表示
        plt.show()
        plt.close()
    
    print(f"  - 全体ヒートマップ: {heatmap_filepath}")
    print(f"  - インタラクティブヒートマップ: {OUTPUT_DIR}/heatmap_interactive_angle_*deg.png")
    print(f"  - ※インタラクティブウィンドウでマウスを動かすとX,Y座標と成功率が表示されます")


def run_single_condition_parallel(params_data):
    """
    単一条件を並列処理で実行する関数
    """
    current_params, trial_range = params_data
    angle_deg = current_params['angle']
    rx_offset = current_params['release_x_offset']
    ry_offset = current_params['release_y_offset']
    rel_angle_deg = current_params.get('relative_angle', 0)
    
    stage_angle_rad = math.radians(-angle_deg)
    relative_angle_rad = math.radians(-rel_angle_deg)
    actual_release_angle_rad = stage_angle_rad + relative_angle_rad
    
    successful_runs_data = []
    trial_results = []
    
    for trial_num in trial_range:
        try:
            # Pygame初期化（各プロセスで必要）
            os.environ['SDL_VIDEODRIVER'] = 'dummy'
            import pygame
            pygame.init()
            
            space = pymunk.Space()
            space.gravity = (0, 981)
            floor_hit_flag = [False]
            wall_hit_flag = [False]
            short_side_contact_count = 0
            accumulated_contact_diff = 0.0
            contact_history = []
            
            # 衝突ハンドラーは簡単な実装を使用
            wall_handler_data = {"bar_body": None}
            use_new_api = None  # 並列処理では代替手段を使用
            
            slope_seg, wall_seg, _ = setup_space(space, stage_angle_rad, is_visual=False)
            
            # X, Y, 角度にバラツキを追加
            random_x_offset = random.uniform(-RELEASE_X_VARIABILITY, RELEASE_X_VARIABILITY)
            random_y_offset = random.uniform(-RELEASE_Y_VARIABILITY, RELEASE_Y_VARIABILITY)
            random_angle_offset = random.uniform(-RELATIVE_ANGLE_VARIABILITY, RELATIVE_ANGLE_VARIABILITY)
            
            release_pos_x = BASE_X + rx_offset + random_x_offset
            release_pos_y = BASE_Y - ry_offset + random_y_offset
            trial_release_angle = actual_release_angle_rad + math.radians(random_angle_offset)
            
            if not check_initial_position(space, (release_pos_x, release_pos_y), trial_release_angle):
                trial_results.append({
                    'trial': trial_num,
                    'success': False,
                    'reason': 'invalid_initial_position',
                    'short_contacts': 0,
                    'x_offset': random_x_offset,
                    'y_offset': random_y_offset,
                    'angle_offset': random_angle_offset
                })
                continue
                
            bar = create_bar(space, (release_pos_x, release_pos_y), trial_release_angle, is_visual=False)
            wall_handler_data["bar_body"] = bar.body
            
            # 衝突ハンドラーの設定
            def parallel_wall_handler(arbiter, space, data):
                nonlocal short_side_contact_count, contact_history, accumulated_contact_diff
                try:
                    contact_points = arbiter.contact_point_set.points
                    if contact_points:
                        contact_point = contact_points[0].point_a
                        contact_side = check_bar_contact_side(bar.body, None, contact_point)
                        
                        if contact_side in ["short_side", "both"]:
                            diff = 0.0
                            if contact_history:
                                _, last_point = contact_history[-1]
                                diff = math.sqrt((contact_point[0] - last_point[0])**2 + (contact_point[1] - last_point[1])**2)
                            
                            accumulated_contact_diff += diff
                            short_side_contact_count += 1
                            contact_history.append((0, contact_point)) # Time is not strictly needed for logic now
                            
                            if short_side_contact_count >= CONTACT_COUNT_THRESHOLD and accumulated_contact_diff > CONTACT_DIFF_THRESHOLD:
                                wall_hit_flag[0] = True
                except:
                    pass
                return True

            def parallel_floor_handler(arbiter, space, data):
                floor_hit_flag[0] = True
                return True

            try:
                wh = space.add_collision_handler(BAR_COLLISION_TYPE, WALL_COLLISION_TYPE)
                wh.begin = parallel_wall_handler
                fh = space.add_collision_handler(BAR_COLLISION_TYPE, FLOOR_COLLISION_TYPE)
                fh.begin = parallel_floor_handler
            except:
                pass

            # シミュレーション実行
            for step in range(int(SIMULATION_DURATION * 60)):
                space.step(1.0 / 60.0)
                
                # 床接触の簡易判定（ハンドラーが動作しない場合のバックアップ）
                if bar.body.position.y >= HEIGHT - 10:
                    floor_hit_flag[0] = True
                
                if (floor_hit_flag[0] and ENABLE_FLOOR_FAIL_VALIDATION) or wall_hit_flag[0]:
                    break
            
            # 失敗理由の判定
            fail_reason = None
            if floor_hit_flag[0]:
                fail_reason = 'floor_contact'
            elif wall_hit_flag[0]:
                fail_reason = 'multiple_short_contacts'
            
            is_success, reason = check_success(bar, slope_seg, wall_seg, stage_angle_rad, floor_hit_flag[0])
            if not is_success and not fail_reason:
                fail_reason = reason
            
            trial_results.append({
                'trial': trial_num,
                'success': is_success,
                'reason': fail_reason if not is_success else 'success',
                'short_contacts': short_side_contact_count,
                'x_offset': random_x_offset,
                'y_offset': random_y_offset,
                'angle_offset': random_angle_offset,
                'final_pos': (bar.body.position.x, bar.body.position.y) if is_success else None,
                'final_angle': bar.body.angle if is_success else None
            })
            
            if is_success:
                successful_runs_data.append({'pos': bar.body.position, 'angle': bar.body.angle})
                
            pygame.quit()
            
        except Exception as e:
            trial_results.append({
                'trial': trial_num,
                'success': False,
                'reason': f'error: {str(e)}',
                'short_contacts': 0,
                'x_offset': 0,
                'y_offset': 0,
                'angle_offset': 0
            })
    
    return current_params, successful_runs_data, trial_results


def run_batch_mode_parallel():
    """
    並列処理版のBATCHモード
    """
    if not LIBRARIES_INSTALLED:
        print("エラー: BATCHモードに必要なライブラリがありません。")
        return
    
    if not PARALLEL_AVAILABLE:
        print("警告: 並列処理ライブラリが利用できません。通常のBATCHモードを実行します。")
        return run_batch_mode()
    
    print("=== 高速並列処理モードを開始します ===")
    
    # CPU数を取得
    cpu_cores = cpu_count()
    max_workers = min(cpu_cores, 8)  # 最大8プロセスに制限
    print(f"利用可能CPU数: {cpu_cores}, 使用プロセス数: {max_workers}")
    
    param_names = list(BATCH_PARAM_RANGES.keys())
    param_combinations = list(itertools.product(*BATCH_PARAM_RANGES.values()))
    total_combinations = len(param_combinations)
    
    print(f"合計 {total_combinations} 通りのパラメータを、各{NUM_TRIALS_PER_CONDITION}回試行します。")
    print(f"総試行回数: {total_combinations * NUM_TRIALS_PER_CONDITION}")
    
    # 各条件とその試行範囲をタスクとして準備
    tasks = []
    for params_tuple in param_combinations:
        current_params = dict(zip(param_names, params_tuple))
        
        # 試行を分割して並列処理
        trials_per_chunk = max(1, NUM_TRIALS_PER_CONDITION // max_workers)
        trial_chunks = []
        
        for i in range(0, NUM_TRIALS_PER_CONDITION, trials_per_chunk):
            end_trial = min(i + trials_per_chunk, NUM_TRIALS_PER_CONDITION)
            trial_range = list(range(i + 1, end_trial + 1))
            trial_chunks.append(trial_range)
        
        # 各チャンクをタスクとして追加
        for chunk in trial_chunks:
            tasks.append((current_params, chunk))
    
    print(f"並列タスク数: {len(tasks)}")
    
    # 結果を格納するリスト
    all_results = []
    completed_tasks = 0
    start_time = time.time()
    
    # 並列処理実行
    with Pool(processes=max_workers) as pool:
        # 非同期でタスクを投入
        async_results = []
        for task in tasks:
            async_result = pool.apply_async(run_single_condition_parallel, (task,))
            async_results.append(async_result)
        
        # 結果を順次取得（進捗表示付き）
        for i, async_result in enumerate(async_results):
            try:
                result = async_result.get(timeout=120)  # 2分のタイムアウト
                all_results.append(result)
                completed_tasks += 1
                
                # 進捗表示
                progress = (completed_tasks / len(async_results)) * 100
                elapsed = time.time() - start_time
                estimated_total = elapsed / (completed_tasks / len(async_results))
                remaining = estimated_total - elapsed
                
                print(f"\r進捗: {completed_tasks}/{len(async_results)} ({progress:.1f}%) "
                      f"経過時間: {elapsed:.1f}s 残り時間: {remaining:.1f}s", end="", flush=True)
                
            except Exception as e:
                print(f"\nタスク {i+1} でエラーが発生しました: {e}")
                completed_tasks += 1
    
    print(f"\n\n=== 並列処理完了 ===")
    print(f"総実行時間: {time.time() - start_time:.1f}秒")
    
    # 結果を統合
    print("結果を統合中...")
    condition_results = {}
    
    for params, successful_runs, trial_results in all_results:
        # パラメータをキーとして結果を統合
        key = tuple(sorted(params.items()))
        
        if key not in condition_results:
            condition_results[key] = {
                'params': params,
                'successful_runs': [],
                'trial_results': []
            }
        
        condition_results[key]['successful_runs'].extend(successful_runs)
        condition_results[key]['trial_results'].extend(trial_results)
    
    # 最終的な結果データを作成
    results_data = []
    
    for key, data in condition_results.items():
        params = data['params']
        successful_runs = data['successful_runs']
        trial_results = data['trial_results']
        
        success_rate = (len(successful_runs) / len(trial_results)) * 100 if trial_results else 0
        
        # 統計計算
        stage_angle_rad = math.radians(-params['angle'])
        
        # 失敗理由の集計
        failure_reasons = {}
        for result in trial_results:
            if not result['success']:
                reason = result['reason']
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        
        # 短冊方向接触の統計
        short_contact_counts = [result['short_contacts'] for result in trial_results]
        avg_short_contacts = np.mean(short_contact_counts) if short_contact_counts else 0
        max_short_contacts = max(short_contact_counts) if short_contact_counts else 0
        
        ideal_x, ideal_y = calculate_ideal_position(stage_angle_rad)
        avg_final_x = np.mean([run['pos'].x for run in successful_runs]) if successful_runs else None
        avg_final_y = np.mean([run['pos'].y for run in successful_runs]) if successful_runs else None
        diff = math.sqrt((ideal_x - avg_final_x) ** 2 + (ideal_y - avg_final_y) ** 2) if avg_final_x is not None else None
        
        # バラツキの統計
        x_offsets = [result['x_offset'] for result in trial_results]
        y_offsets = [result['y_offset'] for result in trial_results]
        angle_offsets = [result['angle_offset'] for result in trial_results]
        
        condition_result = {
            **params,
            'success_rate': success_rate,
            'ideal_x': ideal_x, 'ideal_y': ideal_y,
            'avg_final_x': avg_final_x, 'avg_final_y': avg_final_y,
            'difference_from_ideal_px': diff,
            'avg_short_contacts': avg_short_contacts,
            'max_short_contacts': max_short_contacts,
            'failures_floor': failure_reasons.get('floor_contact', 0),
            'failures_multi_short': failure_reasons.get('multiple_short_contacts', 0),
            'failures_unstable': failure_reasons.get('不安定', 0),
            'failures_angle': failure_reasons.get('角度不正', 0),
            'failures_no_contact': failure_reasons.get('未接触', 0),
            'failures_invalid_pos': failure_reasons.get('invalid_initial_position', 0),
            'x_offset_std': np.std(x_offsets),
            'y_offset_std': np.std(y_offsets),
            'angle_offset_std': np.std(angle_offsets)
        }
        
        results_data.append(condition_result)
    
    # 結果を表示・保存（通常のBATCHモードと同じ）
    if not results_data:
        print("試行結果がありません。")
        return
    
    df = pd.DataFrame(results_data)
    if 'difference_from_ideal_px' in df.columns:
        df['difference_from_ideal_mm'] = df['difference_from_ideal_px'] / PPM
    
    # 結果の概要を表示
    print(f"\n=== 高速BATCH実行結果概要 ===")
    print(f"総パラメータ条件数: {len(df)}")
    print(f"各条件の試行回数: {NUM_TRIALS_PER_CONDITION}")
    print(f"総試行回数: {len(df) * NUM_TRIALS_PER_CONDITION}")
    print(f"")
    print(f"全体成功率: {df['success_rate'].mean():.1f}% (範囲: {df['success_rate'].min():.1f}%-{df['success_rate'].max():.1f}%)")
    print(f"平均短冊接触回数: {df['avg_short_contacts'].mean():.2f}回")
    print(f"最大短冊接触回数: {df['max_short_contacts'].max():.0f}回")
    print(f"")
    print(f"失敗原因別統計:")
    print(f"  床接触: {df['failures_floor'].sum()}回")
    print(f"  複数短冊接触: {df['failures_multi_short'].sum()}回")
    print(f"  不安定: {df['failures_unstable'].sum()}回")
    print(f"  角度不正: {df['failures_angle'].sum()}回")
    print(f"  未接触: {df['failures_no_contact'].sum()}回")
    print(f"  不正初期位置: {df['failures_invalid_pos'].sum()}回")
    
    # 最高成功率の条件を表示
    best_condition = df.loc[df['success_rate'].idxmax()]
    print(f"\n最高成功率の条件:")
    print(f"  角度: {best_condition['angle']}°")
    print(f"  相対角度: {best_condition['relative_angle']}°")
    print(f"  リリース位置: X={best_condition['release_x_offset']}, Y={best_condition['release_y_offset']}")
    print(f"  成功率: {best_condition['success_rate']:.1f}%")
    print(f"  平均短冊接触: {best_condition['avg_short_contacts']:.2f}回")
    
    csv_filepath = os.path.join(OUTPUT_DIR, "simulation_results_parallel.csv")
    df.to_csv(csv_filepath, index=False, float_format='%.3f')
    print(f"\n詳細結果を '{csv_filepath}' に保存しました。")
    
    # ヒートマップの生成
    if LIBRARIES_INSTALLED:
        print("\nヒートマップを生成中...")
        generate_heatmaps(df)
        print("ヒートマップの生成が完了しました。")


def run_batch_mode():
    if not LIBRARIES_INSTALLED: print("エラー: BATCHモードに必要なライブラリがありません。"); return
    print("自動パラメータ探索モードを開始します...")
    param_names = list(BATCH_PARAM_RANGES.keys())
    param_combinations = list(itertools.product(*BATCH_PARAM_RANGES.values()))
    results_data = [];
    total_combinations = len(param_combinations)
    print(f"合計 {total_combinations} 通りのパラメータを、各{NUM_TRIALS_PER_CONDITION}回試行します。")
    for i, params_tuple in enumerate(param_combinations):
        current_params = dict(zip(param_names, params_tuple))
        angle_deg = current_params['angle'];
        rx_offset = current_params['release_x_offset'];
        ry_offset = current_params['release_y_offset'];
        rel_angle_deg = current_params.get('relative_angle', 0)
        stage_angle_rad = math.radians(-angle_deg);
        relative_angle_rad = math.radians(-rel_angle_deg);
        actual_release_angle_rad = stage_angle_rad + relative_angle_rad
        print(
            f"[{i + 1}/{total_combinations}] 角度:{angle_deg}°, 相対:{rel_angle_deg}°, リリース(x,y):({rx_offset}, {ry_offset})... ",
            end="", flush=True)
        successful_runs_data = []
        trial_results = []  # 全試行の詳細結果
        
        for trial_num in range(NUM_TRIALS_PER_CONDITION):
            space = pymunk.Space();
            space.gravity = (0, 981)
            floor_hit_flag = [False]
            wall_hit_flag = [False]
            short_side_contact_count = 0
            accumulated_contact_diff = 0.0
            contact_history = []

            def floor_contact_handler(arbiter, space, data):
                data["hit_flag"][0] = True; return True

            def wall_contact_handler(arbiter, space, data):
                nonlocal short_side_contact_count, contact_history
                current_time = pygame.time.get_ticks()
                
                contact_points = arbiter.contact_point_set.points
                if contact_points:
                    contact_point = contact_points[0].point_a
                    contact_side = check_bar_contact_side(data["bar_body"], None, contact_point)
                    
                    if contact_side in ["short_side", "both"]:
                        # 過去の接触と重複していないかチェック
                        is_new_contact = True
                        for prev_time, prev_point in contact_history:
                            time_diff = current_time - prev_time
                            if time_diff < 2000:  # 2秒以内
                                point_dist = math.sqrt((contact_point[0] - prev_point[0])**2 + (contact_point[1] - prev_point[1])**2)
                                if point_dist < 5:  # 5ピクセル以内
                                    is_new_contact = False
                                    break
                        
                        if is_new_contact:
                            short_side_contact_count += 1
                            contact_history.append((current_time, contact_point))
                            contact_history = [(t, p) for t, p in contact_history if current_time - t < 5000]
                            
                            if short_side_contact_count >= 2:
                                data["hit_flag"][0] = True
                return True

            # pymunkの古いバージョンに対応（set_collision_handlerまたは単純な衝突判定）
            wall_handler_data = {"bar_body": None}
            
            def collision_handler_floor(arbiter, space, data):
                floor_hit_flag[0] = True
                return True
                
            def collision_handler_wall(arbiter, space, data):
                nonlocal short_side_contact_count, contact_history, accumulated_contact_diff
                current_time = pygame.time.get_ticks()
                
                try:
                    contact_points = arbiter.contact_point_set.points
                    if contact_points and wall_handler_data.get("bar_body"):
                        contact_point = contact_points[0].point_a
                        contact_side = check_bar_contact_side(wall_handler_data["bar_body"], None, contact_point)
                        
                        if contact_side in ["short_side", "both"]:
                            # 以前の接触点との距離を計算
                            diff = 0.0
                            if contact_history:
                                last_time, last_point = contact_history[-1]
                                diff = math.sqrt((contact_point[0] - last_point[0])**2 + (contact_point[1] - last_point[1])**2)
                            
                            # 差分を積算
                            accumulated_contact_diff += diff
                            
                            short_side_contact_count += 1
                            contact_history.append((current_time, contact_point))
                            
                            if short_side_contact_count >= CONTACT_COUNT_THRESHOLD and accumulated_contact_diff > CONTACT_DIFF_THRESHOLD:
                                wall_hit_flag[0] = True
                except:
                    # 衝突点情報が取得できない場合はスキップ
                    pass
                return True
            
            # 衝突ハンドラーの設定を試行
            try:
                # 新しいAPIを試行
                handler = space.add_collision_handler(BAR_COLLISION_TYPE, FLOOR_COLLISION_TYPE)
                handler.begin = collision_handler_floor
                
                wall_handler = space.add_collision_handler(BAR_COLLISION_TYPE, WALL_COLLISION_TYPE)
                wall_handler.begin = collision_handler_wall
                use_new_api = True
            except AttributeError:
                try:
                    # 中間のAPIを試行
                    space.set_collision_handler(BAR_COLLISION_TYPE, FLOOR_COLLISION_TYPE, 
                                               begin=collision_handler_floor)
                    space.set_collision_handler(BAR_COLLISION_TYPE, WALL_COLLISION_TYPE, 
                                               begin=collision_handler_wall)
                    use_new_api = False
                except (AttributeError, TypeError):
                    # 古いAPIまたは衝突ハンドラーなしで実行
                    use_new_api = None
            
            slope_seg, wall_seg, _ = setup_space(space, stage_angle_rad, is_visual=False)
            
            # X, Y, 角度にバラツキを追加
            random_x_offset = random.uniform(-RELEASE_X_VARIABILITY, RELEASE_X_VARIABILITY)
            random_y_offset = random.uniform(-RELEASE_Y_VARIABILITY, RELEASE_Y_VARIABILITY)
            random_angle_offset = random.uniform(-RELATIVE_ANGLE_VARIABILITY, RELATIVE_ANGLE_VARIABILITY)
            
            release_pos_x = BASE_X + rx_offset + random_x_offset
            release_pos_y = BASE_Y - ry_offset + random_y_offset
            trial_release_angle = actual_release_angle_rad + math.radians(random_angle_offset)
            
            # データ初期化
            wall_handler_data["bar_body"] = None
            
            if not check_initial_position(space, (release_pos_x, release_pos_y), trial_release_angle): 
                trial_results.append({
                    'trial': trial_num + 1,
                    'success': False,
                    'reason': 'invalid_initial_position',
                    'short_contacts': 0,
                    'x_offset': random_x_offset,
                    'y_offset': random_y_offset,
                    'angle_offset': random_angle_offset
                })
                continue
                
            bar = create_bar(space, (release_pos_x, release_pos_y), trial_release_angle, is_visual=False)
            
            # バーのボディを衝突ハンドラーに設定
            wall_handler_data["bar_body"] = bar.body
            
            # シミュレーション実行
            for step in range(int(SIMULATION_DURATION * 60)):
                space.step(1.0 / 60.0)
                
                # 衝突ハンドラーが使えない場合の代替判定
                if use_new_api is None:
                    # 手動で衝突判定を行う
                    if bar.body.position.y >= HEIGHT - 10:  # 床接触の簡易判定
                        floor_hit_flag[0] = True
                    
                    # 壁面接触の簡易判定（space.shape_queryを使用）
                    try:
                        contacts = space.shape_query(bar)
                        for contact_info in contacts:
                            if contact_info.shape.collision_type == WALL_COLLISION_TYPE:
                                # 簡易的な短冊方向判定
                                bar_angle = bar.body.angle
                                if abs(math.sin(bar_angle)) > 0.7:  # バーが垂直に近い場合
                                    short_side_contact_count += 1
                                    if short_side_contact_count >= CONTACT_COUNT_THRESHOLD:
                                        wall_hit_flag[0] = True
                                        break
                    except:
                        pass
                
                if (floor_hit_flag[0] and ENABLE_FLOOR_FAIL_VALIDATION) or wall_hit_flag[0]: 
                    break
            
            # 失敗理由の判定
            fail_reason = None
            if floor_hit_flag[0]:
                fail_reason = 'floor_contact'
            elif wall_hit_flag[0]:
                fail_reason = 'multiple_short_contacts'
            
            is_success, reason = check_success(bar, slope_seg, wall_seg, stage_angle_rad, floor_hit_flag[0])
            if not is_success and not fail_reason:
                fail_reason = reason
            
            trial_results.append({
                'trial': trial_num + 1,
                'success': is_success,
                'reason': fail_reason if not is_success else 'success',
                'short_contacts': short_side_contact_count,
                'x_offset': random_x_offset,
                'y_offset': random_y_offset,
                'angle_offset': random_angle_offset,
                'final_pos': (bar.body.position.x, bar.body.position.y) if is_success else None,
                'final_angle': bar.body.angle if is_success else None
            })
            
            if is_success: 
                successful_runs_data.append({'pos': bar.body.position, 'angle': bar.body.angle})

        success_rate = (len(successful_runs_data) / NUM_TRIALS_PER_CONDITION) * 100 if NUM_TRIALS_PER_CONDITION > 0 else 0
        
        # 失敗理由の集計
        failure_reasons = {}
        for result in trial_results:
            if not result['success']:
                reason = result['reason']
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        
        # 短冊方向接触の統計
        short_contact_counts = [result['short_contacts'] for result in trial_results]
        avg_short_contacts = np.mean(short_contact_counts) if short_contact_counts else 0
        max_short_contacts = max(short_contact_counts) if short_contact_counts else 0
        
        ideal_x, ideal_y = calculate_ideal_position(stage_angle_rad)
        avg_final_x = np.mean([run['pos'].x for run in successful_runs_data]) if successful_runs_data else None
        avg_final_y = np.mean([run['pos'].y for run in successful_runs_data]) if successful_runs_data else None
        diff = math.sqrt((ideal_x - avg_final_x) ** 2 + (ideal_y - avg_final_y) ** 2) if avg_final_x is not None else None
        
        # バラツキの統計
        x_offsets = [result['x_offset'] for result in trial_results]
        y_offsets = [result['y_offset'] for result in trial_results] 
        angle_offsets = [result['angle_offset'] for result in trial_results]
        
        condition_result = {
            **current_params,
            'success_rate': success_rate,
            'ideal_x': ideal_x, 'ideal_y': ideal_y,
            'avg_final_x': avg_final_x, 'avg_final_y': avg_final_y,
            'difference_from_ideal_px': diff,
            'avg_short_contacts': avg_short_contacts,
            'max_short_contacts': max_short_contacts,
            'failures_floor': failure_reasons.get('floor_contact', 0),
            'failures_multi_short': failure_reasons.get('multiple_short_contacts', 0),
            'failures_unstable': failure_reasons.get('不安定', 0),
            'failures_angle': failure_reasons.get('角度不正', 0),
            'failures_no_contact': failure_reasons.get('未接触', 0),
            'failures_invalid_pos': failure_reasons.get('invalid_initial_position', 0),
            'x_offset_std': np.std(x_offsets),
            'y_offset_std': np.std(y_offsets),
            'angle_offset_std': np.std(angle_offsets)
        }
        
        results_data.append(condition_result)
        print(f"{success_rate:.0f}% (短冊接触: {avg_short_contacts:.1f}回)")
    print("\n--- 全試行完了。結果を集計中... ---")
    if not results_data: print("試行結果がありません。"); return
    
    df = pd.DataFrame(results_data)
    if 'difference_from_ideal_px' in df.columns: 
        df['difference_from_ideal_mm'] = df['difference_from_ideal_px'] / PPM
    
    # 結果の概要を表示
    print(f"\n=== BATCH実行結果概要 ===")
    print(f"総パラメータ条件数: {len(df)}")
    print(f"各条件の試行回数: {NUM_TRIALS_PER_CONDITION}")
    print(f"総試行回数: {len(df) * NUM_TRIALS_PER_CONDITION}")
    print(f"")
    print(f"全体成功率: {df['success_rate'].mean():.1f}% (範囲: {df['success_rate'].min():.1f}%-{df['success_rate'].max():.1f}%)")
    print(f"平均短冊接触回数: {df['avg_short_contacts'].mean():.2f}回")
    print(f"最大短冊接触回数: {df['max_short_contacts'].max():.0f}回")
    print(f"")
    print(f"失敗原因別統計:")
    print(f"  床接触: {df['failures_floor'].sum()}回")
    print(f"  複数短冊接触: {df['failures_multi_short'].sum()}回") 
    print(f"  不安定: {df['failures_unstable'].sum()}回")
    print(f"  角度不正: {df['failures_angle'].sum()}回")
    print(f"  未接触: {df['failures_no_contact'].sum()}回")
    print(f"  不正初期位置: {df['failures_invalid_pos'].sum()}回")
    
    # 最高成功率の条件を表示
    best_condition = df.loc[df['success_rate'].idxmax()]
    print(f"\n最高成功率の条件:")
    print(f"  角度: {best_condition['angle']}°")
    print(f"  相対角度: {best_condition['relative_angle']}°") 
    print(f"  リリース位置: X={best_condition['release_x_offset']}, Y={best_condition['release_y_offset']}")
    print(f"  成功率: {best_condition['success_rate']:.1f}%")
    print(f"  平均短冊接触: {best_condition['avg_short_contacts']:.2f}回")
    
    csv_filepath = os.path.join(OUTPUT_DIR, "simulation_results.csv")
    df.to_csv(csv_filepath, index=False, float_format='%.3f')
    print(f"\n詳細結果を '{csv_filepath}' に保存しました。")
    
    # ヒートマップの生成
    if LIBRARIES_INSTALLED:
        print("\nヒートマップを生成中...")
        generate_heatmaps(df)
        print("ヒートマップの生成が完了しました。")


if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    if MODE == "INTERACTIVE":
        run_interactive_mode()
    elif MODE == "BATCH":
        run_batch_mode()
    elif MODE == "BATCH_PARALLEL":
        run_batch_mode_parallel()
    elif MODE == "SINGLE":
        run_single_condition_mode()
    else:
        print(f"エラー: 無効なモード '{MODE}'")
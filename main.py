#!/usr/bin/env python3
"""
バー設置シミュレーション - メインプログラム
AWS最適化バージョン: 並列処理とCPU効率の改善
"""

import os
import sys
import math
import multiprocessing as mp
from functools import partial
from itertools import product
import time
import signal

# 必須パッケージ
import pymunk
import numpy as np
import pandas as pd

# 可視化パッケージ（ヒートマップ生成用）
try:
    import matplotlib
    matplotlib.use('Agg')  # GUI不要のバックエンド
    import matplotlib.pyplot as plt
    import seaborn as sns
    from matplotlib import font_manager
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("警告: matplotlib/seabornがインストールされていません。ヒートマップは生成されません。")

# pygame（ヘッドレスモードでは不要）
try:
    import pygame
    import pymunk.pygame_util
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False
    print("警告: pygameがインストールされていません。インタラクティブモードは使用できません。")

# システム情報取得パッケージ
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("警告: psutilがインストールされていません。CPU affinityなどの最適化機能は無効になります。")

# ===== 設定 =====
# 実行モード: INTERACTIVE, BATCH, BATCH_PARALLEL, SINGLE
MODE = os.environ.get('MODE', 'BATCH_PARALLEL')

# 画面設定
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
PPM = 100.0  # Pixels per meter

# 物理パラメータ
BAR_FRICTION = 1.8
BAR_ELASTICITY = 0.6
WALL_FRICTION = 1.8
WALL_ELASTICITY = 0.6
BAR_HEIGHT = 1.0  # m
BAR_WIDTH = 0.2   # m
BAR_MASS = 0.01   # kg

# ステージ設定
BASE_X = 400
BASE_Y = 400
STAGE_LENGTH = 400  # pixels
WALL_HEIGHT = 100   # pixels

# シミュレーション設定
FPS = 60
TIME_STEP = 1.0 / FPS
MAX_SIMULATION_TIME = 10.0  # seconds

# 成功判定基準
MAX_VELOCITY = 1.0      # m/s
MAX_ANGULAR_VELOCITY = 0.5  # rad/s
ANGLE_TOLERANCE = 2.0   # degrees
STABLE_TIME = 1.0       # seconds
POSITION_TOLERANCE = 3.0  # pixels

# バッチ処理設定
NUM_TRIALS_PER_CONDITION = 20
RELEASE_X_VARIABILITY = 1.0
RELEASE_Y_VARIABILITY = 1.0
RELATIVE_ANGLE_VARIABILITY = 1.0

# バッチパラメータ範囲
BATCH_PARAM_RANGES = {
    'angle': range(15, 51, 5),
    'release_x_offset': range(-70, 11, 2),  # Reduced step for faster testing
    'release_y_offset': range(40, 111, 2),  # Reduced step for faster testing
    'relative_angle': [0]
}

# AWS最適化設定
AWS_OPTIMIZATIONS = {
    'use_cpu_affinity': True,  # CPUコアへのプロセス固定
    'chunk_size': 'auto',  # 自動チャンクサイズ決定
    'use_shared_memory': False,  # 共有メモリ使用（大規模データ向け）
    'progress_interval': 10,  # 進捗表示間隔（秒）
    'set_process_priority': False,  # プロセス優先度設定
    'use_numa_binding': False,  # NUMA対応（高性能インスタンス向け）
}

# 出力設定
OUTPUT_DIR = 'results'
os.makedirs(OUTPUT_DIR, exist_ok=True)


def init_worker(worker_id, total_workers):
    """
    ワーカープロセスの初期化（AWS最適化）
    
    Args:
        worker_id: ワーカーID
        total_workers: 総ワーカー数
    """
    # シグナルハンドラをデフォルトに設定（親プロセスから継承しない）
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    
    # CPUアフィニティ設定（psutilが利用可能な場合のみ）
    if HAS_PSUTIL and AWS_OPTIMIZATIONS['use_cpu_affinity']:
        try:
            p = psutil.Process()
            cpu_count = psutil.cpu_count(logical=True)
            # ワーカーIDに基づいて特定のCPUコアに割り当て
            cpu_id = worker_id % cpu_count
            p.cpu_affinity([cpu_id])
        except Exception as e:
            # CPU affinity設定失敗は警告のみ（動作は継続）
            pass
    
    # プロセス優先度設定（psutilが利用可能な場合のみ）
    if HAS_PSUTIL and AWS_OPTIMIZATIONS['set_process_priority']:
        try:
            p = psutil.Process()
            # 高優先度に設定（-5から-10の範囲推奨）
            p.nice(-5)
        except Exception:
            pass


class BarSimulation:
    """バー設置シミュレーションクラス"""
    
    def __init__(self, angle, release_x_offset, release_y_offset, relative_angle, 
                 headless=False):
        """
        初期化
        
        Args:
            angle: ステージ角度 (degrees)
            release_x_offset: リリース位置Xオフセット (pixels)
            release_y_offset: リリース位置Yオフセット (pixels)
            relative_angle: バー相対角度 (degrees)
            headless: GUIなしモード
        """
        self.angle = angle
        self.release_x_offset = release_x_offset
        self.release_y_offset = release_y_offset
        self.relative_angle = relative_angle
        self.headless = headless
        
        # Pygame初期化（ヘッドレスモードでは不要）
        if not headless and HAS_PYGAME:
            pygame.init()
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
            pygame.display.set_caption('Bar Set Simulation')
            self.clock = pygame.time.Clock()
            self.draw_options = pymunk.pygame_util.DrawOptions(self.screen)
        elif not headless and not HAS_PYGAME:
            print("警告: pygameがないため、描画は無効化されました")
            self.headless = True
        
        # 物理空間初期化
        self.space = pymunk.Space()
        self.space.gravity = (0, 9.8 * PPM)  # 重力
        
        # ステージ作成
        self._create_stage()
        
        # バー作成
        self._create_bar()
        
        # シミュレーション状態
        self.simulation_time = 0
        self.stable_time = 0
        self.is_stable = False
        self.floor_contact = False
        self.short_contacts = 0
        
    def _create_stage(self):
        """ステージを作成"""
        angle_rad = math.radians(self.angle)
        
        # ステージの斜面部分
        stage_end_x = BASE_X + STAGE_LENGTH * math.cos(angle_rad)
        stage_end_y = BASE_Y + STAGE_LENGTH * math.sin(angle_rad)
        
        stage_body = pymunk.Body(body_type=pymunk.Body.STATIC)
        stage_shape = pymunk.Segment(stage_body, 
                                     (BASE_X, BASE_Y),
                                     (stage_end_x, stage_end_y),
                                     5)
        stage_shape.friction = WALL_FRICTION
        stage_shape.elasticity = WALL_ELASTICITY
        self.space.add(stage_body, stage_shape)
        
        # 壁面部分
        wall_end_x = stage_end_x - WALL_HEIGHT * math.sin(angle_rad)
        wall_end_y = stage_end_y - WALL_HEIGHT * math.cos(angle_rad)
        
        wall_body = pymunk.Body(body_type=pymunk.Body.STATIC)
        wall_shape = pymunk.Segment(wall_body,
                                    (stage_end_x, stage_end_y),
                                    (wall_end_x, wall_end_y),
                                    5)
        wall_shape.friction = WALL_FRICTION
        wall_shape.elasticity = WALL_ELASTICITY
        self.space.add(wall_body, wall_shape)
        
        # 床（失敗判定用）
        floor_body = pymunk.Body(body_type=pymunk.Body.STATIC)
        floor_shape = pymunk.Segment(floor_body,
                                     (0, SCREEN_HEIGHT),
                                     (SCREEN_WIDTH, SCREEN_HEIGHT),
                                     5)
        floor_shape.collision_type = 1  # 床用コリジョンタイプ
        self.space.add(floor_body, floor_shape)
        
        self.stage_angle_rad = angle_rad
        self.stage_end_x = stage_end_x
        self.stage_end_y = stage_end_y
        
    def _create_bar(self):
        """バーを作成"""
        # リリース位置計算
        release_x = BASE_X + self.release_x_offset
        release_y = BASE_Y - self.release_y_offset
        
        # バーの角度（ステージ角度 + 相対角度）
        bar_angle_rad = self.stage_angle_rad + math.radians(self.relative_angle)
        
        # バーの物理ボディ作成
        moment = pymunk.moment_for_box(BAR_MASS, 
                                       (BAR_WIDTH * PPM, BAR_HEIGHT * PPM))
        self.bar_body = pymunk.Body(BAR_MASS, moment)
        self.bar_body.position = (release_x, release_y)
        self.bar_body.angle = bar_angle_rad
        
        # バーの形状
        self.bar_shape = pymunk.Poly.create_box(self.bar_body,
                                                (BAR_WIDTH * PPM, BAR_HEIGHT * PPM))
        self.bar_shape.friction = BAR_FRICTION
        self.bar_shape.elasticity = BAR_ELASTICITY
        self.bar_shape.collision_type = 2  # バー用コリジョンタイプ
        
        self.space.add(self.bar_body, self.bar_shape)
        
    def run(self):
        """シミュレーション実行"""
        running = True
        
        while running and self.simulation_time < MAX_SIMULATION_TIME:
            if not self.headless:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        
            # 物理シミュレーション更新
            self.space.step(TIME_STEP)
            self.simulation_time += TIME_STEP
            
            # 安定性チェック
            self._check_stability()
            
            # 床接触チェック
            self._check_floor_contact()
            
            # 描画（ヘッドレスモードでは不要）
            if not self.headless:
                self._draw()
                self.clock.tick(FPS)
                
            # 安定状態が一定時間続いたら終了
            if self.is_stable and self.stable_time >= STABLE_TIME:
                running = False
                
        return self._get_result()
        
    def _check_stability(self):
        """安定性チェック"""
        velocity = self.bar_body.velocity.length / PPM
        angular_velocity = abs(self.bar_body.angular_velocity)
        
        if velocity < MAX_VELOCITY and angular_velocity < MAX_ANGULAR_VELOCITY:
            self.stable_time += TIME_STEP
            self.is_stable = True
        else:
            self.stable_time = 0
            self.is_stable = False
            
    def _check_floor_contact(self):
        """床接触チェック"""
        for contact in self.bar_shape.shapes_collide(self.space.shapes[2]):
            if contact.points:
                self.floor_contact = True
                break
                
    def _draw(self):
        """描画"""
        self.screen.fill((255, 255, 255))
        self.space.debug_draw(self.draw_options)
        pygame.display.flip()
        
    def _get_result(self):
        """結果を取得"""
        final_x, final_y = self.bar_body.position
        final_angle = math.degrees(self.bar_body.angle)
        
        # 成功判定
        success = (self.is_stable and 
                  not self.floor_contact and
                  self.stable_time >= STABLE_TIME)
        
        return {
            'success': success,
            'final_x': final_x,
            'final_y': final_y,
            'final_angle': final_angle,
            'floor_contact': self.floor_contact,
            'short_contacts': self.short_contacts,
            'simulation_time': self.simulation_time
        }
        
    def cleanup(self):
        """クリーンアップ"""
        if not self.headless and HAS_PYGAME:
            pygame.quit()


def run_single_trial(params):
    """
    単一の試行を実行（並列処理用）
    
    Args:
        params: (angle, release_x_offset, release_y_offset, relative_angle, trial_num)
        
    Returns:
        result: シミュレーション結果辞書
    """
    angle, release_x_offset, release_y_offset, relative_angle, trial_num = params
    
    # バラツキを追加
    x_offset = release_x_offset + np.random.normal(0, RELEASE_X_VARIABILITY)
    y_offset = release_y_offset + np.random.normal(0, RELEASE_Y_VARIABILITY)
    rel_angle = relative_angle + np.random.normal(0, RELATIVE_ANGLE_VARIABILITY)
    
    # シミュレーション実行
    sim = BarSimulation(angle, x_offset, y_offset, rel_angle, headless=True)
    result = sim.run()
    sim.cleanup()
    
    return result


def run_condition_batch(condition_params):
    """
    1つの条件で複数試行を実行
    
    Args:
        condition_params: (angle, release_x_offset, release_y_offset, relative_angle)
        
    Returns:
        condition_result: 条件の集計結果
    """
    angle, release_x_offset, release_y_offset, relative_angle = condition_params
    
    # 各試行のパラメータ作成
    trial_params = [
        (angle, release_x_offset, release_y_offset, relative_angle, i)
        for i in range(NUM_TRIALS_PER_CONDITION)
    ]
    
    # 試行実行
    results = [run_single_trial(p) for p in trial_params]
    
    # 集計
    successes = sum(1 for r in results if r['success'])
    success_rate = (successes / NUM_TRIALS_PER_CONDITION) * 100
    
    avg_final_x = np.mean([r['final_x'] for r in results])
    avg_final_y = np.mean([r['final_y'] for r in results])
    
    floor_contacts = sum(1 for r in results if r['floor_contact'])
    
    return {
        'angle': angle,
        'release_x_offset': release_x_offset,
        'release_y_offset': release_y_offset,
        'relative_angle': relative_angle,
        'success_rate': success_rate,
        'avg_final_x': avg_final_x,
        'avg_final_y': avg_final_y,
        'failures_floor': floor_contacts,
        'num_trials': NUM_TRIALS_PER_CONDITION
    }


def calculate_optimal_chunk_size(total_tasks, num_workers):
    """
    最適なチャンクサイズを計算（AWS最適化版）
    
    Args:
        total_tasks: 総タスク数
        num_workers: ワーカー数
        
    Returns:
        chunk_size: 最適なチャンクサイズ
    """
    # 基本方針：各ワーカーが複数のチャンクを処理してロードバランシング
    # チャンクが大きすぎる：ロードバランシングが悪化
    # チャンクが小さすぎる：オーバーヘッドが増加
    
    # タスク数が少ない場合
    if total_tasks <= num_workers * 2:
        return 1
    
    # 各ワーカーが最低でも4つのチャンクを処理
    min_chunks_per_worker = 4
    chunk_size = max(1, total_tasks // (num_workers * min_chunks_per_worker))
    
    # チャンクサイズの上限を設定（1つのチャンクが長時間実行されないように）
    max_chunk_size = 100
    chunk_size = min(chunk_size, max_chunk_size)
    
    return chunk_size


def get_system_info():
    """
    システム情報を取得
    
    Returns:
        info: システム情報辞書
    """
    if HAS_PSUTIL:
        info = {
            'cpu_count': psutil.cpu_count(logical=True),
            'cpu_count_physical': psutil.cpu_count(logical=False),
            'memory_total_gb': psutil.virtual_memory().total / (1024**3),
            'memory_available_gb': psutil.virtual_memory().available / (1024**3),
        }
    else:
        # psutilがない場合はmultiprocessingのみ使用
        info = {
            'cpu_count': mp.cpu_count(),
            'cpu_count_physical': mp.cpu_count(),
            'memory_total_gb': 0,
            'memory_available_gb': 0,
        }
    return info


def run_batch_parallel():
    """並列バッチ処理（AWS最適化版）"""
    print("=" * 60)
    print("AWS最適化並列バッチ処理を開始")
    print("=" * 60)
    
    # システム情報表示
    sys_info = get_system_info()
    print(f"\nシステム情報:")
    print(f"  CPU数（論理）: {sys_info['cpu_count']}")
    print(f"  CPU数（物理）: {sys_info['cpu_count_physical']}")
    if sys_info['memory_total_gb'] > 0:
        print(f"  総メモリ: {sys_info['memory_total_gb']:.2f} GB")
        print(f"  利用可能メモリ: {sys_info['memory_available_gb']:.2f} GB")
    else:
        print(f"  総メモリ: 不明 (psutilが必要)")
        print(f"  利用可能メモリ: 不明 (psutilが必要)")
    
    # パラメータ組み合わせ生成
    param_combinations = list(product(
        BATCH_PARAM_RANGES['angle'],
        BATCH_PARAM_RANGES['release_x_offset'],
        BATCH_PARAM_RANGES['release_y_offset'],
        BATCH_PARAM_RANGES['relative_angle']
    ))
    
    total_conditions = len(param_combinations)
    print(f"\n処理パラメータ:")
    print(f"  総条件数: {total_conditions}")
    print(f"  条件あたり試行回数: {NUM_TRIALS_PER_CONDITION}")
    print(f"  総試行回数: {total_conditions * NUM_TRIALS_PER_CONDITION}")
    
    # CPU数を取得
    num_cpus = sys_info['cpu_count']
    # 推奨ワーカー数: CPU数 - 1（システム用に1コア残す）
    num_workers = max(1, num_cpus - 1)
    print(f"\n並列処理設定:")
    print(f"  使用ワーカー数: {num_workers}")
    
    # チャンクサイズ計算
    if AWS_OPTIMIZATIONS['chunk_size'] == 'auto':
        chunk_size = calculate_optimal_chunk_size(total_conditions, num_workers)
    else:
        chunk_size = AWS_OPTIMIZATIONS['chunk_size']
    print(f"  チャンクサイズ: {chunk_size}")
    
    if HAS_PSUTIL and AWS_OPTIMIZATIONS['use_cpu_affinity']:
        print(f"  CPU affinity: 有効")
    elif AWS_OPTIMIZATIONS['use_cpu_affinity']:
        print(f"  CPU affinity: 無効 (psutilが必要)")
    
    # 並列処理実行
    start_time = time.time()
    results = []
    last_progress_time = start_time
    
    print("\n処理を開始...")
    print("-" * 60)
    
    try:
        # ワーカー初期化関数を設定
        initializer = partial(init_worker, total_workers=num_workers)
        
        with mp.Pool(processes=num_workers, initializer=initializer,
                     initargs=range(num_workers)) as pool:
            # imap_unorderedを使用して順次結果を取得（メモリ効率的）
            for i, result in enumerate(pool.imap_unordered(
                    run_condition_batch, 
                    param_combinations,
                    chunksize=chunk_size), 1):
                results.append(result)
                
                # 進捗表示
                current_time = time.time()
                if (current_time - last_progress_time >= AWS_OPTIMIZATIONS['progress_interval'] 
                    or i == total_conditions or i % 100 == 0):
                    
                    elapsed = current_time - start_time
                    progress = (i / total_conditions) * 100
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (total_conditions - i) / rate if rate > 0 else 0
                    
                    # メモリ使用状況
                    if HAS_PSUTIL:
                        mem_info = psutil.virtual_memory()
                        mem_percent = mem_info.percent
                        mem_str = f"メモリ: {mem_percent:4.1f}%"
                    else:
                        mem_str = ""
                    
                    print(f"進捗: {i:6d}/{total_conditions} ({progress:5.1f}%) | "
                          f"経過: {elapsed:7.1f}秒 | "
                          f"速度: {rate:5.2f}条件/秒 | "
                          f"残り: {eta:7.1f}秒" + (f" | {mem_str}" if mem_str else ""))
                    
                    last_progress_time = current_time
                    
    except KeyboardInterrupt:
        print("\n\n中断されました。処理済みの結果を保存します...")
        pool.terminate()
        pool.join()
    
    total_time = time.time() - start_time
    
    print("-" * 60)
    print("\n" + "=" * 60)
    print(f"処理完了!")
    print(f"  処理条件数: {len(results)}/{total_conditions}")
    print(f"  総処理時間: {total_time:.2f}秒")
    print(f"  平均処理速度: {len(results)/total_time:.2f}条件/秒")
    
    # パフォーマンス統計
    if len(results) > 0:
        avg_success_rate = np.mean([r['success_rate'] for r in results])
        print(f"  平均成功率: {avg_success_rate:.2f}%")
    
    print("=" * 60)
    
    # 結果をDataFrameに変換
    df = pd.DataFrame(results)
    
    # CSV出力
    output_file = os.path.join(OUTPUT_DIR, 'simulation_results_parallel.csv')
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n結果を保存: {output_file}")
    
    # ヒートマップ生成
    if len(results) > 0:
        generate_heatmaps(df)
    
    return df


def run_batch_sequential():
    """シーケンシャルバッチ処理"""
    print("=" * 60)
    print("シーケンシャルバッチ処理を開始")
    print("=" * 60)
    
    # パラメータ組み合わせ生成
    param_combinations = list(product(
        BATCH_PARAM_RANGES['angle'],
        BATCH_PARAM_RANGES['release_x_offset'],
        BATCH_PARAM_RANGES['release_y_offset'],
        BATCH_PARAM_RANGES['relative_angle']
    ))
    
    total_conditions = len(param_combinations)
    print(f"\n総条件数: {total_conditions}")
    
    start_time = time.time()
    results = []
    
    for i, params in enumerate(param_combinations, 1):
        result = run_condition_batch(params)
        results.append(result)
        
        if i % 10 == 0 or i == total_conditions:
            elapsed = time.time() - start_time
            progress = (i / total_conditions) * 100
            print(f"進捗: {i}/{total_conditions} ({progress:.1f}%) | "
                  f"経過時間: {elapsed:.1f}秒")
    
    total_time = time.time() - start_time
    print(f"\n処理完了! 総処理時間: {total_time:.2f}秒")
    
    # 結果をDataFrameに変換
    df = pd.DataFrame(results)
    
    # CSV出力
    output_file = os.path.join(OUTPUT_DIR, 'simulation_results.csv')
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"結果を保存: {output_file}")
    
    # ヒートマップ生成
    generate_heatmaps(df)
    
    return df


def generate_heatmaps(df):
    """ヒートマップ生成"""
    if not HAS_MATPLOTLIB:
        print("\n警告: matplotlibがインストールされていないため、ヒートマップを生成できません。")
        return
    
    print("\nヒートマップを生成中...")
    
    # 日本語フォント設定
    font_path = 'ipaexg.ttf'
    if os.path.exists(font_path):
        font_prop = font_manager.FontProperties(fname=font_path)
        plt.rcParams['font.family'] = font_prop.get_name()
    
    # 角度ごとにヒートマップ生成
    angles = sorted(df['angle'].unique())
    
    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    axes = axes.flatten()
    
    for idx, angle in enumerate(angles):
        if idx >= len(axes):
            break
            
        angle_data = df[df['angle'] == angle]
        
        # ピボットテーブル作成
        pivot = angle_data.pivot_table(
            values='success_rate',
            index='release_y_offset',
            columns='release_x_offset',
            aggfunc='mean'
        )
        
        # ヒートマップ描画
        sns.heatmap(pivot, 
                   cmap='RdYlGn',
                   vmin=0, vmax=100,
                   cbar_kws={'label': '成功率 (%)'},
                   ax=axes[idx])
        axes[idx].set_title(f'ステージ角度: {angle}°')
        axes[idx].set_xlabel('X オフセット (px)')
        axes[idx].set_ylabel('Y オフセット (px)')
    
    # 未使用のサブプロットを非表示
    for idx in range(len(angles), len(axes)):
        axes[idx].set_visible(False)
    
    plt.tight_layout()
    output_file = os.path.join(OUTPUT_DIR, 'success_rate_heatmaps.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"ヒートマップを保存: {output_file}")


def run_interactive():
    """インタラクティブモード"""
    print("インタラクティブモードは未実装です")
    print("BATCH または BATCH_PARALLEL モードを使用してください")
    sys.exit(1)


def run_single():
    """単一条件モード"""
    print("単一条件モードは未実装です")
    print("BATCH または BATCH_PARALLEL モードを使用してください")
    sys.exit(1)


def main():
    """メイン関数"""
    print(f"\n実行モード: {MODE}")
    
    if MODE == 'BATCH_PARALLEL':
        run_batch_parallel()
    elif MODE == 'BATCH':
        run_batch_sequential()
    elif MODE == 'INTERACTIVE':
        run_interactive()
    elif MODE == 'SINGLE':
        run_single()
    else:
        print(f"エラー: 不明な実行モード '{MODE}'")
        print("有効なモード: BATCH, BATCH_PARALLEL, INTERACTIVE, SINGLE")
        sys.exit(1)


if __name__ == '__main__':
    # マルチプロセッシングの開始方法を設定（Linuxではfork、Windowsではspawn）
    if sys.platform == 'linux':
        mp.set_start_method('fork', force=True)
    
    main()

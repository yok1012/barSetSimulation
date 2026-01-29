#!/usr/bin/env python3
"""
バッチ処理の基本的なテストスクリプト
AWS環境でのテスト用（少ない条件数で動作確認）
"""

import sys
import os

# テスト用の設定でMODE環境変数を設定（importより前に）
os.environ['MODE'] = 'BATCH_PARALLEL'

# main.pyのパスを追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# main.pyをインポート
import main

# テスト用に小規模な範囲に変更
main.BATCH_PARAM_RANGES = {
    'angle': [20, 25],  # 2つの角度のみ
    'release_x_offset': range(-10, 1, 5),  # 3点
    'release_y_offset': range(60, 71, 5),  # 3点
    'relative_angle': [0]
}

# 試行回数を減らす
main.NUM_TRIALS_PER_CONDITION = 3

# 進捗表示を頻繁に
main.AWS_OPTIMIZATIONS['progress_interval'] = 5

print("=" * 60)
print("テストモード: 小規模バッチ処理")
print("=" * 60)
print(f"\n総条件数: {2 * 3 * 3 * 1} = 18条件")
print(f"条件あたり試行回数: {main.NUM_TRIALS_PER_CONDITION}")
print(f"総試行回数: {18 * main.NUM_TRIALS_PER_CONDITION} = 54試行")
print("\nこのテストは1-2分で完了します。\n")

if __name__ == '__main__':
    # マルチプロセッシングの開始方法を設定
    if sys.platform == 'linux':
        import multiprocessing as mp
        mp.set_start_method('fork', force=True)
    
    # 並列バッチ処理を実行
    try:
        df = main.run_batch_parallel()
        print("\n✅ テスト成功!")
        print(f"処理された条件数: {len(df)}")
        print(f"平均成功率: {df['success_rate'].mean():.2f}%")
    except Exception as e:
        print(f"\n❌ テスト失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

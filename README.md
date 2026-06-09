# バー設置シミュレーション

## 概要
斜面ステージ（傾いた床＋垂直な壁）の上に、細長い「バー（短冊）」を上空からリリースして落下させ、**バーが斜面と壁の角にきれいに収まるか（＝設置成功か）** を 2D 物理エンジンで判定するシミュレーションです。リリース位置・角度・ステージ角度を変えながら、**どの条件なら高確率で成功するか** を探索・分析できます。

```
        ＼  ← バーをここからリリース
         ＼
   壁│   ＼
     │  ＼
     └─────＼____ 斜面    バーが壁と斜面の角に収まれば「成功」
   基点(2000,2000)
```

## 技術仕様
- **物理エンジン**: pymunk (2D物理シミュレーション)
- **描画**: pygame (リアルタイム可視化)
- **データ分析**: pandas, numpy, matplotlib, seaborn (結果分析・可視化)
- **並列処理**: multiprocessing (高速化、psutil でメモリ監視)
- **操作UI**: Streamlit (モード選択・パラメータ入力フロントエンド)

> **座標スケールについて**
> 現行コードは μm スケールで動作します（**1 pixel = 1 μm**, PPM = 1,000,000）。
> 画面は 4000×4000 px（= 4mm × 4mm）、ステージ基点 `BASE` は中央 (2000, 2000)。

---

## 実行モード

| モード | 目的 | 出力 |
|--------|------|------|
| **INTERACTIVE** | 手動でパラメータを調整して挙動を体感・デバッグ | リアルタイム画面 |
| **SINGLE** | 1条件だけ実行し初期/最終状態を画像化 | PNG 1枚 |
| **BATCH** | パラメータ範囲を総当たりで逐次探索 | CSV ＋ ヒートマップ |
| **BATCH_PARALLEL** | BATCH をマルチコアで高速化（大量条件向け） | CSV ＋ ヒートマップ |

---

## 使用方法

### 方法① Streamlit UI（推奨）
`main.py` を編集せず、ブラウザ上でモード選択・パラメータ入力・実行ができます。

```powershell
streamlit run streamlit_app.py
```

- サイドバーで **モードを選択** → メイン画面で **パラメータを入力** → **実行ボタン**。
- SINGLE / BATCH / BATCH_PARALLEL は実行後、結果の画像・CSV をブラウザに表示。
- INTERACTIVE は **別ウィンドウ（pygame）** で起動します（ブラウザ内には埋め込めません）。

構成ファイル:
- `streamlit_app.py` … 操作UI本体
- `sim_runner.py` … UIから呼ばれる実行ランナー（`main.py` のグローバル設定を上書きして各モードを起動。`main.py` 自体は変更しない）

> **BATCH_PARALLEL の制限**: Windows の並列処理（spawn）では子プロセスが `main.py` を再 import するため、UIで変更した **バラツキ / シミュレーション時間 / 接触閾値 / 床接触判定** は反映されず `main.py` の既定値が使われます（**パラメータ範囲と試行回数は反映されます**）。これらを変えて探索したい場合は逐次 **BATCH** を使用してください。

### 方法② main.py を直接実行
`main.py` 冒頭の `MODE` を書き換えて実行します。

```python
MODE = "INTERACTIVE"  # "BATCH" / "BATCH_PARALLEL" / "SINGLE"
```
```powershell
python main.py
```

---

## INTERACTIVE モードの操作（キーボード／マウス）

バーが落下して静止すると、右上に成功/失敗の判定が表示されます。

| キー | 操作 |
|------|------|
| `↑ / ↓` | リリース Y 位置（高さ） |
| `← / →` | リリース X 位置 |
| `W / S` | ステージ角度 ±（変更時はステージ再構築） |
| `Q / E` | バーの相対角度 ± |
| `Shift + キー` | 5刻みで高速変更 |
| `R` | 同条件で再落下 |
| `+ / - / マウスホイール` | 表示倍率（20%〜100%） |
| `M` | 接触時のビープ音 ON/OFF |
| 左上の数値をクリック | 値を直接キーボード入力 |
| `ESC` | 終了（入力中なら入力キャンセル） |

**画面マーカーの色:** 赤 = ステージ基点(0,0) / 青 = バー重心 / 緑 = 理想位置。緑と青のズレ（誤差線）が小さいほど良い設置です。

---

## 入力パラメータ

### シミュレーション条件（モード共通の探索対象）
| パラメータ | 変数名 | 既定値 | 単位 | 説明 |
|-----------|--------|-------|------|------|
| ステージ角度 | `angle` | 30 | ° | 斜面の傾斜角度 |
| リリース位置X | `release_x_offset` | 0 | μm | **理想位置**を原点としたXオフセット（実X = ideal_x + offset） |
| リリース位置Y | `release_y_offset` | 600 | μm | **理想位置**を原点としたYオフセット（実Y = ideal_y − offset、大きいほど上） |

> **リリースオフセットの原点について**
> リリースオフセットの原点(0,0)は **理想位置**（バーが収まるべき目標位置 `calculate_ideal_position`）です。
> `offset=(0,0)` ならリリース位置＝理想位置になり、オフセットは「理想位置からのずらし量」を表します。
> `ANGLE_LINKED_OFFSET=True` のときは、その軸（X=斜面方向 / Y=壁方向）がステージ傾斜に連動して回転します。
| 相対角度 | `relative_angle` | 0 | ° | バーの初期回転角度 |

### 基本物理設定（main.py 上部の定数）
| パラメータ | 変数名 | 既定値 | 説明 |
|-----------|--------|-------|------|
| バー摩擦係数 | `BAR_FRICTION` | 1.5 | バー表面の摩擦（無次元） |
| バー反発係数 | `BAR_ELASTICITY` | 0.6 | バーの弾性（無次元） |
| ステージ摩擦係数 | `WALL_FRICTION` | 1.2 | ステージ壁面/斜面の摩擦（無次元） |
| ステージ反発係数 | `WALL_ELASTICITY` | 0.6 | ステージの弾性（無次元） |
| バー長手方向 | `BAR_HEIGHT` | 0.001 m (1mm) | バーの縦サイズ → 1000 px |
| バー短手方向 | `BAR_WIDTH` | 0.0001 m (0.1mm) | バーの横サイズ → 100 px |
| バー質量 | `BAR_MASS` | 1e-8 kg | バーの重量 |
| シミュレーション時間 | `SIMULATION_DURATION` | 4.0 s | 1試行あたりの物理計算時間 |

### バッチ処理設定
| パラメータ | 変数名 | 既定値 | 説明 |
|-----------|--------|-------|------|
| 試行回数 | `NUM_TRIALS_PER_CONDITION` | 10 | 各条件での試行回数 |
| X位置バラツキ | `RELEASE_X_VARIABILITY` | 0 μm | X位置に与える標準偏差 |
| Y位置バラツキ | `RELEASE_Y_VARIABILITY` | 0 μm | Y位置に与える標準偏差 |
| 角度バラツキ | `RELATIVE_ANGLE_VARIABILITY` | 0.0° | 相対角度に与える標準偏差 |

既定の探索範囲（`BATCH_PARAM_RANGES`）:
```python
BATCH_PARAM_RANGES = {
    'angle':            range(20, 31, 10),    # 20°〜30°
    'release_x_offset': range(-300, 300, 5),  # X 位置
    'release_y_offset': range(400, 1000, 5),  # Y 位置
    'relative_angle':   [0]                   # 相対角度は固定
}
```

---

## 判定基準と出力

### 成功判定基準（`SUCCESS_CRITERIA`）
すべてを満たし、かつ床に接触していない場合に「成功」と判定します。
| 項目 | 基準値 | 説明 |
|------|--------|------|
| 最大線速度 | < 1.0 m/s | バーが十分に静止している |
| 最大角速度 | < 0.5 rad/s | バーの回転が収まっている |
| 角度許容誤差 | < 1.0° | 最終角度がステージ角度に一致 |
| 最小安定時間 | > 1.0 s | 安定状態を維持している |
| 位置許容誤差 | < 10.0 μm | 理想位置からのズレが小さい |
| 斜面接触 | 必須 | 斜面に触れていること |

### 失敗判定
| 理由 | 説明 |
|------|------|
| 床接触 | バーが床面に接触（`ENABLE_FLOOR_FAIL_VALIDATION` が有効な場合 NG） |
| 複数短冊接触 | 短手方向での壁面接触が閾値以上、かつ累積差分が閾値超 |
| 不安定 | 速度/角速度が基準を超える |
| 角度不正 | 最終角度が許容範囲外 |
| 未接触 | 斜面との接触が不十分 |
| 不正初期位置 | リリース位置が壁/ステージにめり込んでいる |

接触判定の閾値:
- `CONTACT_COUNT_THRESHOLD = 5` … 短冊方向の接触回数閾値
- `CONTACT_DIFF_THRESHOLD = 1.0` μm … 接触位置の累積差分閾値

### CSV 出力（BATCH / BATCH_PARALLEL）
主な列:
| 列名 | 説明 |
|------|------|
| `angle`, `release_x_offset`, `release_y_offset`, `relative_angle` | 入力条件 |
| `success_rate` | 成功率（%） |
| `ideal_x`, `ideal_y` | 理想設置位置 |
| `avg_final_x`, `avg_final_y` | 成功試行の平均最終位置 |
| `difference_from_ideal_px` / `_mm` | 理想位置からの誤差（μm / mm） |
| `avg_short_contacts`, `max_short_contacts` | 短冊方向接触回数の平均/最大 |
| `failures_floor` / `_multi_short` / `_unstable` / `_angle` / `_no_contact` / `_invalid_pos` | 失敗理由別の回数 |
| `x_offset_std`, `y_offset_std`, `angle_offset_std` | バラツキの標準偏差 |

ファイル名:
- 逐次 BATCH … `simulation_results.csv`
- 並列 BATCH_PARALLEL … `simulation_results_parallel.csv`

### 可視化出力
| ファイル | 内容 |
|----------|------|
| `success_rate_heatmaps.png` | 角度ごとに X-Y 位置別の成功率を一覧表示 |
| `heatmap_interactive_angle_*deg.png` | 角度別の個別ヒートマップ（緑=高、黄=中、赤=低） |
| `single_condition_result.png` | SINGLE モードの結果画像（初期位置=青の半透明、最終位置を重ね描画） |

---

## 出力フォルダ
出力先は `main.py` の `OUTPUT_DIR`（既定 `results_err13`）、または Streamlit UI の「出力フォルダ」欄で指定（既定 `results_streamlit`）。

---

## 依存ライブラリ
```
pygame, pymunk, numpy, pandas, matplotlib, seaborn, psutil, streamlit
```
インストール例:
```powershell
pip install pygame pymunk numpy pandas matplotlib seaborn psutil streamlit
```

## システム要件
- Python 3.6+（動作確認は 3.12）
- マルチコア CPU 推奨（BATCH_PARALLEL モード）
- 日本語フォント `ipaexg.ttf`（リポジトリ同梱、グラフ・UI の日本語表示用）

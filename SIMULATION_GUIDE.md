# バーセット配置シミュレーション - 技術資料

## 1. シミュレーション概要

本シミュレーションは、長方形のバー（棒状部品）を斜面と壁で構成されたステージに落下させ、理想的な位置に正確に配置できるかを検証する物理シミュレーションです。2D物理エンジン（Pymunk）を使用して、重力・摩擦・衝突などの物理現象を再現します。

### 目的
- バーが斜面と壁の間の理想位置に安定して収まる条件を探索
- リリース位置・角度・ステージ角度の最適なパラメータを発見
- 製造バラツキ（位置・角度の誤差）が成功率に与える影響を評価

---

## 2. 物理モデルの詳細

### 2.1 使用している物理エンジン

**Pymunk**: Python用の2D物理エンジン（Chipmunk2Dのラッパー）

主な機能：
- **剛体力学**: 物体の質量、慣性モーメント、速度、角速度を計算
- **衝突検出**: 物体間の接触判定と接触点の計算
- **摩擦・反発**: 表面間の摩擦係数と反発係数による物理的な相互作用
- **重力**: 重力加速度による自由落下の再現

### 2.2 バー（落下物体）のモデル

```python
# バーの物理パラメータ
BAR_WIDTH = 0.1      # 幅: 0.1m (100mm)
BAR_HEIGHT = 1.0     # 高さ: 1.0m (1000mm)
BAR_MASS = 0.01      # 質量: 0.01kg (10g)
BAR_FRICTION = 1.2   # 摩擦係数
BAR_ELASTICITY = 0.6 # 反発係数
```

**形状**: 長方形（`pymunk.Poly.create_box`）
- 縦長の棒状（幅:高さ = 1:10）
- 重心は矩形の中心
- 慣性モーメントは `pymunk.moment_for_box` で自動計算

**物理挙動**:
- 重力により自由落下（重力加速度: 981 cm/s² = 9.81 m/s²）
- 壁・斜面との接触で摩擦と反発が発生
- 回転運動と並進運動の両方をシミュレート

### 2.3 ステージ（環境）のモデル

**構成要素**:
1. **斜面（slope）**: 基点から角度θで伸びる線分
2. **壁（wall）**: 基点から斜面に垂直に立つ線分
3. **床（floor）**: 画面下部の水平線（失敗判定用）
4. **画面の壁**: 画面の上下左右の境界

```python
# ステージの基本設定
BASE_X, BASE_Y = 400, 400  # 基点座標（ピクセル）
SLOPE_LENGTH = 400         # 斜面の長さ（ピクセル）
WALL_FRICTION = 1.2        # 壁の摩擦係数
WALL_ELASTICITY = 0.6      # 壁の反発係数
```

**座標系**:
- 画面左上が原点(0, 0)
- X軸: 右方向が正
- Y軸: 下方向が正
- 角度: 時計回りが正（Pymunkの標準）

**斜面の計算**:
```python
stage_angle_rad = math.radians(-angle_deg)  # 角度をラジアンに変換（符号反転）
slope_end_x = BASE_X + SLOPE_LENGTH * math.cos(stage_angle_rad)
slope_end_y = BASE_Y + SLOPE_LENGTH * math.sin(stage_angle_rad)
```

**壁の計算**:
```python
wall_angle = stage_angle_rad - math.pi/2  # 斜面に垂直
wall_end_x = BASE_X + wall_height * math.cos(wall_angle)
wall_end_y = BASE_Y + wall_height * math.sin(wall_angle)
```

---

## 3. シミュレーションのプロセス

### 3.1 初期条件の設定

**パラメータ**:
- `angle`: ステージの角度（度）- 斜面の傾き
- `release_x_offset`: リリース位置のX方向オフセット（ピクセル）
- `release_y_offset`: リリース位置のY方向オフセット（ピクセル）
- `relative_angle`: バーの相対リリース角度（度）- ステージ角度に対する相対角度

**リリース位置の計算**:
```python
release_pos_x = BASE_X + release_x_offset
release_pos_y = BASE_Y - release_y_offset  # Y方向は符号反転（上方向が正のオフセット）
```

**バーの初期角度**:
```python
stage_angle_rad = math.radians(-angle)
relative_angle_rad = math.radians(-relative_angle)
actual_release_angle_rad = stage_angle_rad + relative_angle_rad
```

### 3.2 製造バラツキの追加（BATCHモード）

現実の製造プロセスを模擬するため、各試行にランダムなバラツキを追加：

```python
RELEASE_X_VARIABILITY = 2      # X位置のバラツキ: ±2ピクセル (±20μm)
RELEASE_Y_VARIABILITY = 2      # Y位置のバラツキ: ±2ピクセル (±20μm)
RELATIVE_ANGLE_VARIABILITY = 1.0  # 角度のバラツキ: ±1.0度

# 各試行でランダムなオフセットを追加
random_x_offset = random.uniform(-RELEASE_X_VARIABILITY, RELEASE_X_VARIABILITY)
random_y_offset = random.uniform(-RELEASE_Y_VARIABILITY, RELEASE_Y_VARIABILITY)
random_angle_offset = random.uniform(-RELATIVE_ANGLE_VARIABILITY, RELATIVE_ANGLE_VARIABILITY)
```

### 3.3 物理シミュレーションの実行

**タイムステップ**: 1/60秒（60 FPS）
```python
SIMULATION_DURATION = 4.0  # シミュレーション時間: 4秒
dt = 1.0 / 60.0            # タイムステップ
```

**シミュレーションループ**:
```python
for step in range(int(SIMULATION_DURATION * 60)):
    space.step(dt)  # 物理演算を1ステップ進める
```

各ステップで実行される処理：
1. 重力による加速度の計算
2. 速度・角速度の更新
3. 位置・角度の更新
4. 衝突検出と応答
5. 摩擦力の適用

### 3.4 衝突判定とイベント処理

**衝突ハンドラー**:
- **床接触ハンドラー**: バーが床に接触したら即座に失敗
- **壁接触ハンドラー**: バーの短手方向（上下の面）が壁に複数回接触したら失敗

**短手方向接触の判定**:
```python
def check_bar_contact_side(bar_body, wall_segment, contact_point):
    # バーの中心から接触点への相対位置を計算
    rel_x = contact_point[0] - bar_pos.x
    rel_y = contact_point[1] - bar_pos.y

    # バーのローカル座標系に変換
    local_x = rel_x * cos(-bar_angle) - rel_y * sin(-bar_angle)
    local_y = rel_x * sin(-bar_angle) + rel_y * cos(-bar_angle)

    # 長手方向（左右）か短手方向（上下）かを判定
    long_side_contact = abs(local_x) > bar_width * 0.25
    short_side_contact = abs(local_y) > bar_height * 0.25

    if long_side_contact and short_side_contact:
        return "both"  # コーナー接触
    elif long_side_contact:
        return "long_side"  # 理想的な接触
    elif short_side_contact:
        return "short_side"  # 望ましくない接触
```

---

## 4. 位置の意味合いと理想位置の計算

### 4.1 位置の定義

#### リリース位置（release_x_offset, release_y_offset）
- **意味**: バーを落下させる初期位置
- **基準**: ステージの基点 (BASE_X=400, BASE_Y=400) からのオフセット
- **調整可能**: インタラクティブモードで矢印キーで調整可能
- **探索範囲**: BATCHモードで広範囲を自動探索
  - 例: X=-60～+30ピクセル, Y=+20～+170ピクセル

#### 理想位置（ideal_x, ideal_y）
- **意味**: バーが斜面と壁の両方に接触して安定する理想的な最終位置
- **計算方法**: ステージ角度から幾何学的に計算
- **固定値**: 各ステージ角度に対して一意に決まる

#### 実際の最終位置（actual_x, actual_y）
- **意味**: シミュレーション終了時のバーの実際の位置
- **可変**: リリース位置や製造バラツキにより変化
- **評価指標**: 理想位置との誤差で配置精度を評価

### 4.2 理想位置の計算式

理想位置は、バーが壁と斜面に同時に接触している状態の位置を示します。

```python
def calculate_ideal_position(stage_angle_rad):
    """
    バーが壁と斜面の両方に接触している理想的な位置を計算
    """
    # ステージ角度を正の値に変換
    stage_angle_deg = abs(math.degrees(stage_angle_rad))

    # ステージの基点を中心とした円弧運動
    center_x = BASE_X  # 400
    center_y = BASE_Y  # 400

    # 実測値から計算した半径
    radius = 57.0  # ピクセル（約5.7mm）

    # 理想位置の角度計算（実測データに基づく）
    # 30度のステージ角度の場合、理想位置は255度の方向
    ideal_angle_deg = 285.0 - stage_angle_deg
    ideal_angle_rad = math.radians(ideal_angle_deg)

    # 円弧上の位置を計算
    ideal_x = center_x + radius * math.cos(ideal_angle_rad)
    ideal_y = center_y + radius * math.sin(ideal_angle_rad)

    return ideal_x, ideal_y
```

**計算の意味**:
- ステージの基点を中心に、半径57ピクセルの円弧上にある
- ステージ角度が変わると、理想位置も円弧に沿って移動する
- 角度関係 `285° - ステージ角度` は実測データから導出された経験式

### 4.3 位置誤差の評価

**位置誤差の計算**:
```python
position_error = math.sqrt((ideal_x - actual_x)**2 + (ideal_y - actual_y)**2)
```

**許容誤差**:
```python
SUCCESS_CRITERIA = {
    'position_tolerance': 3.0  # 許容誤差: 3ピクセル（約0.3mm）
}
```

**評価**:
- 位置誤差 ≤ 3ピクセル: 合格（理想位置に近い）
- 位置誤差 > 3ピクセル: 不合格（位置ずれが大きい）

---

## 5. 成功判定の基準

### 5.1 成功条件（全て満たす必要がある）

```python
SUCCESS_CRITERIA = {
    'max_velocity': 1.0,                    # 最大線速度: 1.0 cm/s
    'max_angular_velocity': 0.5,            # 最大角速度: 0.5 rad/s
    'angle_tolerance_rad': math.radians(1.0), # 角度許容誤差: 1度
    'min_settle_time': 1.0,                 # 最小安定時間: 1.0秒
    'position_tolerance': 3.0               # 位置許容誤差: 3ピクセル（0.3mm）
}
```

#### 1. 速度の安定性
```python
is_stable = (body.velocity.length < 1.0 and
             abs(body.angular_velocity) < 0.5)
```
- バーが静止または十分に遅い速度になっている必要がある

#### 2. 角度の正確性
```python
is_angle_correct = abs(body.angle - slope_angle_rad) < math.radians(1.0)
```
- バーの角度が斜面角度と一致している必要がある（±1度以内）

#### 3. 安定時間
- バーが安定状態を最低1秒間維持する必要がある

#### 4. 位置精度
```python
position_error = math.sqrt((ideal_x - actual_x)**2 + (ideal_y - actual_y)**2)
if position_error > 3.0:
    return False, "位置誤差大"
```
- 理想位置から3ピクセル（0.3mm）以内に収まる必要がある

#### 5. 接触状態
```python
if not touching_slope:
    return False, "未接触"
```
- バーが斜面に接触している必要がある
- 壁への接触は必須ではない（緩い条件）

### 5.2 失敗条件（いずれか1つでも該当すると失敗）

#### 1. 床接触
```python
if ENABLE_FLOOR_FAIL_VALIDATION and floor_was_hit:
    return False, "床に接触"
```
- バーが画面下部の床に接触した場合は即座に失敗

#### 2. 複数回短手方向接触
- バーの短手方向（上下の面）が壁に2回以上接触した場合は失敗
- バーが不安定に跳ね返っている状態を示す

#### 3. 不安定
- 速度または角速度が基準を超えている

#### 4. 角度不正
- バーの角度が斜面角度と1度以上ずれている

#### 5. 位置誤差大
- 理想位置から3ピクセル以上ずれている

#### 6. 未接触
- バーが斜面に接触していない

---

## 6. シミュレーションモード

### 6.1 INTERACTIVEモード（インタラクティブ）

**用途**: リアルタイムでパラメータを調整しながら視覚的に確認

**操作方法**:
- 矢印キー: リリース位置の調整
- W/S: ステージ角度の調整
- Q/E: 相対リリース角度の調整
- Shift+キー: 高速変更（5刻み）
- R: シミュレーションのリセット
- M: 音声アラートのオン/オフ

**表示情報**:
- バーの現在位置と理想位置（緑色のマーカー）
- 位置誤差のリアルタイム表示
- 短手方向接触回数
- 最終結果（成功/失敗の理由）

**警告アラート**:
- 床接触: 赤色の点滅表示とビープ音（440Hz）
- 複数回短手方向接触: 紫色の点滅表示とビープ音（660Hz）

### 6.2 BATCHモード（自動探索）

**用途**: 複数のパラメータ組み合わせを自動的に試行

**設定例**:
```python
BATCH_PARAM_RANGES = {
    'angle': range(20, 21, 1),           # ステージ角度: 20度
    'release_x_offset': range(-60, 30, 1),  # X位置: -60～30ピクセル
    'release_y_offset': range(20, 170, 1),  # Y位置: 20～170ピクセル
    'relative_angle': [0]                # 相対角度: 0度固定
}
NUM_TRIALS_PER_CONDITION = 30  # 各条件で30回試行
```

**出力結果**:
- CSV形式の詳細データ（`simulation_results.csv`）
  - 各条件の成功率
  - 平均最終位置と理想位置との誤差
  - 失敗原因別の統計
  - 短手方向接触の統計
- ヒートマップ画像
  - X-Y位置の成功率分布
  - 角度ごとの個別ヒートマップ

### 6.3 BATCH_PARALLELモード（並列処理）

**用途**: 大量のパラメータ探索を高速化

**特徴**:
- CPUの複数コアを活用（最大8プロセス）
- 通常のBATCHモードと同じ結果を高速に取得
- 進捗表示と推定残り時間の表示

**性能**:
- 利用可能CPU数に応じて最大8倍高速化
- 例: 8コアCPUで約1/8の実行時間

---

## 7. 出力データと可視化

### 7.1 CSV出力データ

**主要なカラム**:
- `angle`: ステージ角度（度）
- `release_x_offset`, `release_y_offset`: リリース位置
- `success_rate`: 成功率（%）
- `ideal_x`, `ideal_y`: 理想位置（ピクセル）
- `avg_final_x`, `avg_final_y`: 平均最終位置（ピクセル）
- `difference_from_ideal_px`: 理想位置との誤差（ピクセル）
- `difference_from_ideal_mm`: 理想位置との誤差（mm）
- `avg_short_contacts`: 平均短手方向接触回数
- `failures_floor`: 床接触による失敗回数
- `failures_multi_short`: 複数短手方向接触による失敗回数
- `failures_unstable`: 不安定による失敗回数
- `failures_angle`: 角度不正による失敗回数
- `failures_no_contact`: 未接触による失敗回数

### 7.2 ヒートマップ

**全体ヒートマップ** (`success_rate_heatmaps.png`):
- 複数の角度を一覧表示（3列レイアウト）
- X軸: リリースX位置
- Y軸: リリースY位置
- 色: 成功率（緑=高、黄=中、赤=低）

**個別インタラクティブヒートマップ** (`heatmap_interactive_angle_*deg.png`):
- 角度ごとの詳細なヒートマップ
- マウスカーソルで各セルの詳細情報を表示
  - X, Y座標
  - その条件での成功率

---

## 8. 物理モデルの使われ方

### 8.1 自由落下フェーズ

**初期状態**:
- バーは指定のリリース位置に、指定の角度で配置される
- 初速度はゼロ（静止状態からの落下）

**物理演算**:
```python
space.gravity = (0, 981)  # 重力ベクトル（cm/s²）
```
- 重力により下方向に加速
- 空気抵抗は考慮しない（真空中の落下を仮定）

**運動方程式**:
- 並進運動: F = ma（力 = 質量 × 加速度）
- 回転運動: τ = Iα（トルク = 慣性モーメント × 角加速度）

### 8.2 衝突と反発フェーズ

**衝突検出**:
```python
contacts = space.shape_query(bar_shape)
```
- Pymunkが物体間の接触点を自動的に検出
- 各接触点で法線方向と接線方向の力を計算

**反発係数の適用**:
```python
BAR_ELASTICITY = 0.6
WALL_ELASTICITY = 0.6
```
- 衝突後の相対速度 = -反発係数 × 衝突前の相対速度
- 反発係数0.6: エネルギーの36%が保存される（非弾性衝突）

### 8.3 摩擦フェーズ

**摩擦力の計算**:
```python
BAR_FRICTION = 1.2
WALL_FRICTION = 1.2
```
- 最大静止摩擦力 = 摩擦係数 × 垂直抗力
- 動摩擦力 = 摩擦係数 × 垂直抗力

**摩擦の効果**:
- バーの滑りを抑制
- 回転エネルギーを散逸
- 最終的な安定状態を実現

### 8.4 安定化フェーズ

**エネルギー散逸**:
- 衝突による反発（エネルギー損失）
- 摩擦による運動エネルギーの熱変換
- 複数回の微小な衝突で徐々に静止

**安定判定**:
```python
if bar_body.velocity.length < 0.5 and abs(bar_body.angular_velocity) < 0.5:
    settle_frames_count += 1
if settle_frames_count > 30:  # 0.5秒間安定
    bar_is_settled = True
```

---

## 9. 主要な関数の説明

### 9.1 setup_space(space, slope_angle_rad, is_visual)
**役割**: 物理空間にステージ（斜面、壁、床、境界）を作成

**処理**:
1. 斜面セグメントを作成し、位置・角度・摩擦・反発を設定
2. 壁セグメントを作成（斜面に垂直）
3. 床と境界壁を作成
4. 全ての静的オブジェクトを物理空間に追加

**戻り値**: (斜面セグメント, 壁セグメント, 床セグメント)

### 9.2 create_bar(space, pos, angle, is_visual)
**役割**: 指定位置・角度にバーを作成

**処理**:
1. バーの剛体を作成（質量、慣性モーメント）
2. 矩形のシェイプを作成（サイズ、摩擦、反発）
3. 衝突タイプを設定（衝突ハンドラー用）
4. 物理空間に追加

**戻り値**: バーのシェイプオブジェクト

### 9.3 check_success(bar_shape, slope_segment, wall_segment, slope_angle_rad, floor_was_hit, settle_time)
**役割**: バーが成功条件を満たしているか総合的に判定

**判定項目**:
1. 床接触の有無
2. 速度・角速度の安定性
3. 角度の正確性
4. 安定時間の充足
5. 位置誤差の許容範囲内
6. 斜面への接触

**戻り値**: (成功フラグ, 理由文字列)

### 9.4 calculate_ideal_position(stage_angle_rad)
**役割**: ステージ角度から理想的なバーの位置を計算

**計算方法**:
- ステージ基点を中心とした円弧運動を仮定
- 半径57ピクセル、角度関係 `285° - ステージ角度`
- 実測データに基づく経験的な計算式

**戻り値**: (ideal_x, ideal_y)

### 9.5 check_bar_contact_side(bar_body, wall_segment, contact_point)
**役割**: バーのどの面が接触しているか判定

**処理**:
1. 接触点をバーのローカル座標系に変換
2. ローカル座標でX方向（長手）かY方向（短手）かを判定
3. 閾値（幅・高さの25%）で判定

**戻り値**: "long_side", "short_side", "both", "unknown"

---

## 10. 応用例と活用方法

### 10.1 最適パラメータの探索
1. BATCHモードで広範囲のパラメータを探索
2. ヒートマップで成功率の高い領域を視覚的に特定
3. INTERACTIVEモードで詳細な微調整
4. 最終的な最適条件を決定

### 10.2 製造バラツキの影響評価
1. `NUM_TRIALS_PER_CONDITION` を増やして統計的な信頼性を向上
2. `RELEASE_X_VARIABILITY`, `RELEASE_Y_VARIABILITY`, `RELATIVE_ANGLE_VARIABILITY` を調整
3. 成功率の変化から許容バラツキを判定
4. 製造プロセスの品質基準を設定

### 10.3 失敗原因の分析
1. CSV出力の失敗原因別統計を確認
2. 主要な失敗原因を特定
   - 床接触 → リリース高さが低すぎる
   - 複数短手方向接触 → バーが不安定に跳ねている
   - 角度不正 → リリース角度が不適切
3. 対策を立案（パラメータ調整、構造変更など）

### 10.4 物理パラメータの感度分析
1. 摩擦係数（`BAR_FRICTION`, `WALL_FRICTION`）を変化させる
2. 反発係数（`BAR_ELASTICITY`, `WALL_ELASTICITY`）を変化させる
3. バーの質量（`BAR_MASS`）を変化させる
4. 各パラメータが成功率に与える影響を評価

---

## 11. まとめ

本シミュレーションは、Pymunk物理エンジンを活用して、バーの落下・配置プロセスを高精度に再現します。

**主な特徴**:
- 実測データに基づく理想位置の計算
- 製造バラツキを考慮した統計的評価
- 多次元パラメータ空間の効率的な探索
- 視覚的なフィードバックと詳細な数値データ

**活用価値**:
- 物理的な試作を行う前にパラメータを最適化
- 製造プロセスの品質管理基準を設定
- 失敗モードの理解と対策の立案
- コスト削減と開発期間の短縮

**今後の拡張可能性**:
- 3D物理シミュレーションへの拡張
- 複数バーの同時配置シミュレーション
- 機械学習による最適化（強化学習など）
- 実機との比較検証とモデルの精緻化

# AWS EC2 デプロイガイド

## 概要
このガイドは、barSetSimulation プロジェクトを AWS EC2 インスタンスにデプロイし、実行するための手順です。

---

## ステップ 1: SSH Config の設定

### 1.1 SSH Config ファイルの編集
Windows ローカルマシンの `~/.ssh/config` に以下の設定を追加：

```ssh
Host my-aws-server
    HostName ec2-35-79-17-67.ap-northeast-1.compute.amazonaws.com
    User ubuntu
    IdentityFile C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem
```

### 1.2 パラメータの説明
| パラメータ | 説明 | 例 |
|-----------|------|-----|
| `Host` | ホスト別名（ショートカット名） | `my-aws-server` |
| `HostName` | AWS EC2 インスタンスのエンドポイント | `ec2-35-79-17-67.ap-northeast-1.compute.amazonaws.com` |
| `User` | ログインユーザー（Ubuntu インスタンスの場合） | `ubuntu` |
| `IdentityFile` | .pem ファイルの絶対パス | `C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem` |

---

## ステップ 2: プロジェクトのデプロイ

### 2.1 AWS EC2 上にディレクトリを作成
```bash
ssh my-aws-server
mkdir -p ~/barsetProjects
cd ~/barsetProjects
```

### 2.2 ローカルマシンからプロジェクトをアップロード
**ローカルマシンの PowerShell で実行**（AWS から抜けた状態で）：

```powershell
scp -r "e:\pythonProject\barSetSimulation\experiments\v_gemini" my-aws-server:~/barsetProjects/v_gemini
```

### 2.3 AWS 上でアップロードを確認
```bash
ssh my-aws-server
cd ~/barsetProjects/v_gemini
ls -la
```

---

## ステップ 3: AWS EC2 上で依存関係をインストール

### 3.1 Python 開発環境をセットアップ
```bash
# パッケージリストを更新
sudo apt update

# Python 仮想環境パッケージをインストール
sudo apt install python3.12-venv -y
```

### 3.2 仮想環境を作成
```bash
cd ~/barsetProjects/v_gemini

# 仮想環境を作成
python3 -m venv venv

# 仮想環境をアクティベート
source venv/bin/activate
```

### 3.3 Python パッケージをインストール
```bash
# 仮想環境がアクティベートされた状態で実行
pip install -r requirements.txt
```

**インストールされるパッケージ:**
- pygame: シミュレーション可視化
- pymunk: 2D物理エンジン
- numpy, pandas: データ処理
- matplotlib, seaborn: グラフ描画
- psutil: システム情報取得（AWS最適化用）

---

## ステップ 4: プロジェクトの実行

### 4.1 実行モード
AWS EC2 では GUI が表示できないため、**BATCH モード**または**BATCH_PARALLEL モード**を推奨します。

| モード | 説明 | 実行コマンド | 推奨度 |
|--------|------|-----------|-------|
| BATCH | シングルスレッド処理（GUI 不要） | `python3 main.py` | ⭐⭐ |
| BATCH_PARALLEL | マルチコア並列処理（高速・AWS最適化済み） | `MODE=BATCH_PARALLEL python3 main.py` | ⭐⭐⭐⭐⭐ |

**BATCH_PARALLEL モードの最適化機能:**
- CPU Affinity（CPUコア固定）による高速化
- 動的チャンクサイズ計算によるロードバランシング
- リアルタイム進捗表示とメモリ監視
- グレースフルシャットダウン（中断時もデータ保存）

詳細は `AWS_OPTIMIZATION_GUIDE.md` を参照してください。

### 4.2 フォアグラウンドで実行
```bash
# 仮想環境がアクティベートされていることを確認
source venv/bin/activate

# 並列処理で実行（推奨）
MODE=BATCH_PARALLEL python3 main.py

# または シーケンシャル実行
python3 main.py
```

**実行時の出力例:**
```
============================================================
AWS最適化並列バッチ処理を開始
============================================================

システム情報:
  CPU数（論理）: 8
  CPU数（物理）: 4
  総メモリ: 16.00 GB
  利用可能メモリ: 12.50 GB

処理パラメータ:
  総条件数: 28512
  条件あたり試行回数: 20
  総試行回数: 570240

並列処理設定:
  使用ワーカー数: 7
  チャンクサイズ: 101
  CPU affinity: 有効

処理を開始...
------------------------------------------------------------
進捗:    100/28512 ( 0.4%) | 経過:    45.2秒 | 速度:  2.21条件/秒 | 残り: 12857.5秒 | メモリ: 35.2%
進捗:    200/28512 ( 0.7%) | 経過:    90.5秒 | 速度:  2.21条件/秒 | 残り: 12840.3秒 | メモリ: 36.1%
...
```

### 4.3 バックグラウンドで実行（推奨）
実行時間が長い場合は、バックグラウンドで実行：

```bash
# 並列処理モードでバックグラウンド実行
nohup python3 main.py > output.log 2>&1 &

# プロセスIDを記録（後で停止する場合に必要）
echo $! > simulation.pid

# ログをリアルタイムで確認
tail -f output.log

# ログから進捗を確認（別のターミナルで）
watch -n 10 'tail -20 output.log'
```

**プロセス管理:**
```bash
# 実行中のPythonプロセスを確認
ps aux | grep python

# プロセスを停止する場合（グレースフル）
kill -INT $(cat simulation.pid)

# 処理中のデータは自動的に保存されます
```

---

## ステップ 5: 結果の確認と取得

### 5.1 AWS 上で結果を確認
```bash
# 結果ディレクトリを確認
ls -la ~/barsetProjects/v_gemini/results/

# CSV ファイルを確認
cat ~/barsetProjects/v_gemini/results/simulation_results.csv
```

### 5.2 ローカルマシンにダウンロード
**ローカルマシンの PowerShell で実行**：

```powershell
# AWS から結果ディレクトリをダウンロード
scp -r my-aws-server:~/barsetProjects/v_gemini/results ~/Downloads/aws_results_v_gemini

# ダウンロードしたファイルを確認
cd ~/Downloads/aws_results_v_gemini
dir
```

---

## ステップ 6: 再度のログイン時の手順

### 次回 AWS にログインしたとき：
```bash
# AWS にログイン
ssh my-aws-server

# プロジェクトディレクトリに移動
cd ~/barsetProjects/v_gemini

# 仮想環境をアクティベート（重要！）
source venv/bin/activate

# プログラムを実行
python3 main.py
```

---

## トラブルシューティング

### エラー: "Could not resolve hostname my-aws-server"
- **原因**: AWS 内から `scp` コマンドを実行しようとしている
- **解決**: ローカルマシンの PowerShell で `scp` コマンドを実行してください

### エラー: "externally-managed-environment"
- **原因**: Python 3.12 で仮想環境が必須
- **解決**: 仮想環境を作成して使用してください（`python3 -m venv venv`）

### エラー: "Permission denied" (apt install 時)
- **原因**: 管理者権限が必要
- **解決**: `sudo` コマンドを使用してください

---

## 参考情報

### ディレクトリ構造（AWS 上）
```
~/barsetProjects/
└── v_gemini/
    ├── main.py
    ├── venv/              # 仮想環境
    ├── results/           # 実行結果が保存される
    ├── README.md
    └── ...
```

### よく使うコマンド
```bash
# 仮想環境をアクティベート
source venv/bin/activate

# 仮想環境を非アクティベート
deactivate

# バックグラウンドプロセスを確認
ps aux | grep python

# プロセスを強制終了
kill -9 <PID>
```

---

## 参考リンク
- [AWS EC2 Documentation](https://docs.aws.amazon.com/ec2/)
- [SSH Config Manual](https://linux.die.net/man/5/ssh_config)
- [Python Virtual Environments](https://docs.python.org/3/tutorial/venv.html)

---

## 付録: AWS EC2 インスタンス選択ガイド

### A. インスタンスタイプ別の性能比較

| インスタンスタイプ | vCPU | メモリ | 推奨ワーカー数 | 期待処理速度 | 月額コスト概算 |
|----------------|------|-------|-------------|-----------|-------------|
| **t3.medium** | 2 | 4GB | 1 | ~2,500条件/時間 | $30-40 |
| **t3.large** | 2 | 8GB | 1 | ~2,500条件/時間 | $60-75 |
| **t3.xlarge** | 4 | 16GB | 3 | ~7,500条件/時間 | $120-150 |
| **c5.large** | 2 | 4GB | 1 | ~3,000条件/時間 | $60-70 |
| **c5.xlarge** ⭐ | 4 | 8GB | 3 | ~10,000条件/時間 | $120-140 |
| **c5.2xlarge** ⭐⭐ | 8 | 16GB | 7 | ~20,000条件/時間 | $240-280 |
| **c5.4xlarge** | 16 | 32GB | 15 | ~40,000条件/時間 | $480-560 |

⭐ = コストパフォーマンスが良い

### B. 処理規模別の推奨インスタンス

#### 小規模テスト（<5,000条件）
- **推奨:** t3.medium または t3.large
- **処理時間:** 1-3時間
- **コスト:** 最も安い（$0.05-0.10/時間）
- **注意点:** CPU クレジットに注意

#### 中規模処理（5,000-20,000条件）
- **推奨:** c5.xlarge または c5.2xlarge
- **処理時間:** 1-2時間
- **コスト:** 中程度（$0.17-0.34/時間）
- **最適:** バランスの良い性能/コスト比

#### 大規模処理（>20,000条件）
- **推奨:** c5.2xlarge または c5.4xlarge
- **処理時間:** 1-3時間
- **コスト:** 高い（$0.34-0.68/時間）
- **最適:** 最速の処理が必要な場合

### C. コスト最適化の Tips

**1. スポットインスタンスを使用（最大90%削減）:**
```bash
# スポットインスタンスでは中断の可能性があるため、
# nohupとグレースフルシャットダウン機能を活用
nohup python3 main.py > output.log 2>&1 &
```

**2. 処理時間を見積もって適切なインスタンスを選択:**
- 短時間（<2時間）: より高性能なインスタンスがコスト効率的
- 長時間（>8時間）: 低コストインスタンスでも良い

**3. 不要になったら即座に停止:**
```bash
# 処理完了後、すぐにインスタンスを停止
sudo shutdown -h now
```

### D. 実際の処理時間例（c5.2xlarge使用）

| パラメータ設定 | 総条件数 | 処理時間 | 推定コスト |
|------------|---------|---------|----------|
| angle: 15-50° (5°刻み)<br>x: -70~10 (5刻み)<br>y: 40~110 (5刻み) | 1,776 | ~5分 | $0.03 |
| angle: 15-50° (5°刻み)<br>x: -70~10 (2刻み)<br>y: 40~110 (2刻み) | 28,512 | ~1.4時間 | $0.48 |
| angle: 15-50° (5°刻み)<br>x: -70~10 (1刻み)<br>y: 40~110 (1刻み) | 45,696 | ~2.3時間 | $0.78 |
| angle: 15-50° (1°刻み)<br>x: -70~10 (1刻み)<br>y: 40~110 (1刻み) | 164,736 | ~8.2時間 | $2.79 |

詳細な最適化情報は `AWS_OPTIMIZATION_GUIDE.md` を参照してください。

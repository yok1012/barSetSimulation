# クイックリファレンス

## 5分でわかるAWS最適化版の使い方

### 1️⃣ セットアップ（初回のみ）

```bash
# EC2にログイン
ssh my-aws-server

# プロジェクトディレクトリ作成
mkdir -p ~/barsetProjects
cd ~/barsetProjects

# ローカルからアップロード（ローカルPCで実行）
scp -r /path/to/barSetSimulation my-aws-server:~/barsetProjects/

# EC2で仮想環境作成
cd ~/barsetProjects/barSetSimulation
python3 -m venv venv
source venv/bin/activate

# 依存関係インストール
pip install -r requirements.txt
```

### 2️⃣ 実行

```bash
# 仮想環境アクティベート
source venv/bin/activate

# 並列バッチ処理を実行
MODE=BATCH_PARALLEL python3 main.py

# またはバックグラウンドで実行
nohup python3 main.py > output.log 2>&1 &
```

### 3️⃣ 進捗確認

```bash
# リアルタイムでログ確認
tail -f output.log

# 10秒ごとに最新20行を表示
watch -n 10 'tail -20 output.log'
```

### 4️⃣ 結果取得

```bash
# EC2上で確認
ls -lh results/

# ローカルPCにダウンロード（ローカルで実行）
scp -r my-aws-server:~/barsetProjects/barSetSimulation/results ./
```

---

## よく使うコマンド

### パラメータ変更

main.pyを編集：

```python
# 処理範囲を変更
BATCH_PARAM_RANGES = {
    'angle': range(20, 31, 1),  # 20-30度を1度刻み
    'release_x_offset': range(-50, 1, 2),
    'release_y_offset': range(60, 91, 2),
    'relative_angle': [0]
}

# 試行回数を変更
NUM_TRIALS_PER_CONDITION = 30  # より高精度

# チャンクサイズを手動設定
AWS_OPTIMIZATIONS['chunk_size'] = 50
```

### プロセス管理

```bash
# 実行中のPythonプロセス確認
ps aux | grep python

# プロセスを停止（データ保存される）
kill -INT <PID>

# 強制停止（非推奨）
kill -9 <PID>
```

### ディスク容量確認

```bash
# 結果フォルダのサイズ
du -sh results/

# ディスク全体の使用状況
df -h
```

---

## トラブルシューティング早見表

| 症状 | 原因 | 解決策 |
|------|------|-------|
| `ModuleNotFoundError: No module named 'pymunk'` | 依存関係未インストール | `pip install -r requirements.txt` |
| `Permission denied` | 仮想環境外で実行 | `source venv/bin/activate` |
| メモリ不足エラー | 大規模処理 | チャンクサイズを小さくする |
| CPU使用率が低い | ワーカー不足 | `num_workers`を増やす |
| 処理が遅い | インスタンス不足 | より大きいインスタンスを使用 |

---

## インスタンス選択ガイド

### 小規模テスト（<5,000条件）
```
インスタンス: t3.medium
処理時間: 1-3時間
コスト: ~$0.10
```

### 中規模処理（5,000-20,000条件）
```
インスタンス: c5.xlarge ⭐推奨
処理時間: 1-2時間
コスト: ~$0.20-0.40
```

### 大規模処理（>20,000条件）
```
インスタンス: c5.2xlarge ⭐⭐推奨
処理時間: 1-3時間
コスト: ~$0.50-1.00
```

---

## パフォーマンスチェックリスト

実行前に確認：

- [ ] 仮想環境がアクティベートされている
- [ ] 依存関係がインストールされている
- [ ] MODE=BATCH_PARLLELを指定している
- [ ] パラメータ範囲が適切（初回は小規模で試す）
- [ ] ディスク容量が十分ある（結果保存用）
- [ ] バックグラウンド実行している（長時間処理の場合）

実行後に確認：

- [ ] CPU使用率が85-95%に達している
- [ ] メモリ使用率が80%未満
- [ ] 結果ファイルが生成されている
- [ ] ヒートマップが生成されている
- [ ] ログにエラーがない

---

## パフォーマンス指標

**期待値（c5.2xlarge使用時）:**

- ✅ 処理速度: 15,000-20,000条件/時間
- ✅ CPU使用率: 85-95%
- ✅ メモリ使用率: 40-60%
- ✅ 28,512条件の処理時間: ~1.4時間
- ✅ コスト: ~$0.48

**実際の値が期待値より低い場合:**

1. CPU使用率が低い → ワーカー数を増やす
2. メモリ使用率が高い → チャンクサイズを減らす
3. 処理速度が遅い → より大きいインスタンスを使用

---

## 便利なエイリアス（オプション）

~/.bashrc に追加：

```bash
# エイリアス
alias sim='cd ~/barsetProjects/barSetSimulation'
alias simrun='cd ~/barsetProjects/barSetSimulation && source venv/bin/activate && MODE=BATCH_PARALLEL python3 main.py'
alias simlog='tail -f ~/barsetProjects/barSetSimulation/output.log'
alias simresults='ls -lh ~/barsetProjects/barSetSimulation/results/'

# 使用例
sim        # プロジェクトディレクトリに移動
simrun     # シミュレーション実行
simlog     # ログ確認
simresults # 結果確認
```

---

## 詳細ドキュメント

- 📖 [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - 最適化の概要
- 📖 [AWS_OPTIMIZATION_GUIDE.md](AWS_OPTIMIZATION_GUIDE.md) - 最適化の詳細
- 📖 [AWS_DEPLOYMENT_GUIDE.md](AWS_DEPLOYMENT_GUIDE.md) - デプロイ手順
- 📖 [CHANGELOG.md](CHANGELOG.md) - 変更履歴

---

## サポート

問題が発生した場合：

1. ログを確認: `cat output.log`
2. システム情報を確認: `uname -a`, `python3 --version`, `pip list`
3. ドキュメントを参照
4. Issueを作成（問題の詳細、環境情報、ログを含める）

---

**作成日:** 2026-01-29  
**バージョン:** 2.0.0

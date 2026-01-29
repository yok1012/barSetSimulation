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
pip install pygame pymunk numpy pandas matplotlib seaborn
```

---

## ステップ 4: プロジェクトの実行

### 4.1 実行モード
AWS EC2 では GUI が表示できないため、**BATCH モード**または**BATCH_PARALLEL モード**を推奨します。

| モード | 説明 | 実行コマンド |
|--------|------|-----------|
| BATCH | シングルスレッド処理（GUI 不要） | `python3 main.py` |
| BATCH_PARALLEL | マルチコア並列処理（高速） | `MODE=BATCH_PARALLEL python3 main.py` |

### 4.2 フォアグラウンドで実行
```bash
# 仮想環境がアクティベートされていることを確認
source venv/bin/activate

# 実行
python3 main.py
```

### 4.3 バックグラウンドで実行（推奨）
実行時間が長い場合は、バックグラウンドで実行：

```bash
nohup python3 main.py > output.log 2>&1 &

# ログを確認
tail -f output.log
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

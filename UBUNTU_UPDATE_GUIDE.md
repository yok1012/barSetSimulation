# Ubuntu上のプロジェクト更新とStreamlit運用

以下は Ubuntu 24.04 / ユーザー `ubuntu` / 配置先 `/home/ubuntu/barSetSimulation` 用です。
別ユーザー・別の配置先の場合は、`deploy/` の2つのserviceファイルのUserとパスも変更してください。

この機能は、現在 **`codex/aws-large-batch` ブランチ（PR #2）** にあります。
mainへマージする前に `git pull origin main` だけ実行しても取得できません。

## 0. 更新前に計算を完了・停止する

既存の計算を完了させるか、保存機能がある実行なら停止して保存してください。
通常モードの古い計算は再開機能を持たないため、できれば完了まで待ちます。
ブラウザ画面の更新だけでも、旧サービスが子プロセスごと終了させる場合があります。

既にサービスを設定している場合、対象が存在するものだけ停止します。

```bash
sudo systemctl stop barsim-web
# 新ワーカーを導入済みの場合
sudo systemctl stop barsim-worker
```

tmuxから起動している場合は、対応するウィンドウでCtrl+Cで終了してください。
同じ8501番ポートで旧Streamlitと新サービスを同時起動しないでください。

**途中のチェックポイントを新コードで再開する際は注意:** CLIはコードの変更を検出すると再開を拒否します。
再開予定のジョブは更新前に旧バージョンで完了させるか、旧コードと依存環境を維持してください。
チェックを回避して異なる計算結果を混ぜないでください。

## 1-A. Git cloneで配置した場合

EC2で確認します。

```bash
cd ~/barSetSimulation
ls -ld .git
git status --short
```

`.git` がある場合はこの手順です。変更が表示されたら、必要な変更をバックアップ・コミットして
作業ツリーを整理してから先へ進んでください。結果フォルダは削除しません。

更新前のコードをGitのローカルタグに残して更新します。

```bash
git tag "before-web-update-$(date +%Y%m%d-%H%M%S)"
git fetch origin
git switch codex/aws-large-batch
git pull --ff-only origin codex/aws-large-batch
```

`git switch` は、初回は取得済みのリモートブランチを追跡するローカルブランチを作ります。
ブランチやローカル変更の競合が表示されたらその時点で止め、`reset --hard` や `git clean` は使わないでください。

## 1-B. SCPなどで手動アップロードした場合（.gitがない）

`.git` がない場合は、元フォルダを丸ごとバックアップ名へ変更してからGit管理へ移行します。
既存の結果、設定、仮想環境はバックアップ側にそのまま残します。

```bash
cd ~
backup_dir="$HOME/barSetSimulation.backup-$(date +%Y%m%d-%H%M%S)"
mv "$HOME/barSetSimulation" "$backup_dir"
git clone --branch codex/aws-large-batch https://github.com/yok1012/barSetSimulation.git "$HOME/barSetSimulation"
cd "$HOME/barSetSimulation"
```

cloneに失敗した場合は、新規フォルダを確認してから元バックアップを戻してください。
新しいフォルダをそのまま旧フォルダへ重ねないでください。

ローカルで変更したPythonコードがある場合はバックアップとの差分を確認してから個別に取り込みます。
結果を参照・回収する場合はバックアップ内の `results*` フォルダを使えます。
旧 `.venv` を移動して流用せず、次の手順で新しく作成してください。

新ワーカー導入後にこの移行を行う場合、既存 `aws_results/web` に絶対パスの記録があるため、
全計算を停止したうえで同じ配置先へコピーしてからサービスを起動します。
初回導入では不要です。

## 2. Python依存関係の更新

```bash
cd ~/barSetSimulation
sudo apt update
sudo apt install -y python3-venv git tmux htop
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python -m pip freeze > requirements-installed.txt
```

既に `.venv` があれば `python3 -m venv .venv` で中のパッケージは削除されません。
実行中の計算がある状態で依存関係を更新しないでください。

## 3. Webと計算ワーカーを別サービスにする

```bash
cd ~/barSetSimulation
sudo install -m 644 deploy/barsim-web.service /etc/systemd/system/barsim-web.service
sudo install -m 644 deploy/barsim-worker.service /etc/systemd/system/barsim-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now barsim-worker barsim-web
systemctl status barsim-worker barsim-web --no-pager
curl -f http://127.0.0.1:8501/_stcore/health
```

Web再起動は `sudo systemctl restart barsim-web` です。AWSモードの計算は別ワーカーなので継続します。
ワーカーやEC2が再起動した場合、計算中のジョブは「中断」になり、画面から明示的に再開します。
ワーカー停止時は最大300秒待ち、その後はsystemdが残存プロセスを終了させます。
未コミットのタスクは再開時に再計算されます。

## 4. Tailnetからアクセスする

Tailscale導入・同じTailnetへの参加が済んでいる場合:

```bash
sudo tailscale serve --bg http://127.0.0.1:8501
tailscale serve status
```

表示されたHTTPS URLを、Tailscaleに接続したPCのブラウザで開きます。
既に同じ設定がある場合は確認だけで十分です。Funnelは有効にしません。
AWSの8501番ポートを開ける必要はありません。Tailnetのアクセスルールで利用者を絞ってください。
この画面にはユーザー別のジョブ所有権はなく、アクセスできる利用者は同じキューを操作します。

## 5. ブラウザで計算を行う

1. サイドバーの **「AWS向けに保存・再開して実行」** をONにする。
2. BATCH / BATCH_PARALLEL / BATCH_V2の既存入力欄で条件を設定する。
3. 並列数（0で自動）、タスクあたりの試行数、seedを設定して実行する。
4. 下部の「AWSバッチの実行状況」で履歴を選び、進捗とログを確認する。
5. 必要なら「停止して保存」、その後「保存済み分から再開」を押す。
6. 完了・停止後に「CSVダウンロードを準備」→「結果CSVをダウンロード」を押す。

実行はキューへ登録され、1台で同時に1ジョブを処理します。ジョブ内部はマルチプロセス並列です。
出力先欄の値はAWSモードでは使わず、`aws_results/web/<ジョブID>/results` へ自動保存します。
位置・傾きのカラーマップPNGを生成します。GIFは生成しません。ブラウザを閉じても計算は継続し、開き直すと履歴から確認できます。
画面は約3秒ごと、計算の進捗データは約10秒ごとに更新します。
100MiBを超えるCSVはサーバーからSCP等で取得してください。

## ログ確認・tmuxでの監視

```bash
journalctl -u barsim-web -n 100 --no-pager
journalctl -u barsim-worker -n 100 --no-pager
```

個別計算のログは `aws_results/web/<ジョブID>/run.log` にあります。
SSHでtmuxを開き、`htop` や `tail -f` を使う運用も継続できます。
Tailnetへの接続とインターネットへの外向き通信が可能なネットワーク構成を維持してください。

## 次回以降の更新

計算の完了を待つ → Webとワーカーを停止 → `git status --short`を確認 →
`git pull --ff-only origin codex/aws-large-batch` → 必要に応じて依存・serviceファイル更新 →
`sudo systemctl start barsim-worker barsim-web` の順です。
PR #2をmainへマージした後にmainで運用する場合は、作業ツリーを整理して
`git fetch origin` → `git switch main` → `git pull --ff-only origin main` に切り替えます。

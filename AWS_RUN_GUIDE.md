# AWS EC2でバーセットシミュレーションを実行する手順

この手順は、ローカルPCのプロジェクトをAWS EC2へ転送し、EC2上でシミュレーションを実行して、結果をローカルへ回収するためのものです。

## 前提

- EC2へSSH接続できること
- 秘密鍵のパス:

```powershell
C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem
```

- EC2ホスト:

```text
ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com
```

- EC2のユーザー名:

```text
ec2-user
```

## 1. EC2へSSH接続

ローカルPowerShellで実行します。

```powershell
ssh -i "C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem" ec2-user@ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com
```

## 2. EC2側の基本パッケージをインストール

EC2に入った後、以下を実行します。

```bash
sudo yum update -y
sudo yum install -y git python3 python3-pip python3-devel gcc gcc-c++ make tmux
```

Ubuntu系AMIの場合は `yum` ではなく `apt` を使います。

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv python3-dev gcc g++ make tmux
```

## 3. ローカルからEC2へプロジェクトを転送

`scp` は除外指定ができないため、`.venv` や結果フォルダまで送られてしまいます。不要ファイルを除外する場合は `rsync` を使うのが推奨です。

Git Bash、WSL、またはrsyncが使える環境で以下を実行します。

```bash
rsync -avz --delete \
  -e 'ssh -i /c/Users/255396/Documents/AWS_private_key/md_yokokawa.pem' \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.streamlit_ui_settings.json' \
  --exclude 'results*/' \
  --exclude 'aws_results/' \
  /c/Users/255396/Documents/pythonDevPro/barset_Simulations/barSetSimulation/ \
  ec2-user@ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com:~/barSetSimulation/
```

PowerShellで `rsync` が使えない場合は、除外付きのtarを作って送ります。

ローカルPowerShellで実行します。

```powershell
cd "C:\Users\255396\Documents\pythonDevPro\barset_Simulations"
tar --exclude="barSetSimulation/.git" --exclude="barSetSimulation/.venv" --exclude="barSetSimulation/__pycache__" --exclude="barSetSimulation/results*" --exclude="barSetSimulation/aws_results" -czf barSetSimulation_upload.tar.gz barSetSimulation
scp -i "C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem" ".\barSetSimulation_upload.tar.gz" ec2-user@ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com:~
```

EC2上で展開します。

```bash
cd ~
rm -rf barSetSimulation
tar -xzf barSetSimulation_upload.tar.gz
```

単純に全ファイルを送ってよい場合だけ、以下の `scp` を使います。

```powershell
scp -i "C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem" -r "C:\Users\255396\Documents\pythonDevPro\barset_Simulations\barSetSimulation" ec2-user@ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com:~
```

## 4. EC2でPython仮想環境を作成

EC2上で実行します。

```bash
cd ~/barSetSimulation
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pygame pymunk numpy pandas matplotlib seaborn psutil streamlit Pillow
```

## 5. CLIで動作確認

まずStreamlitではなく、計算本体が動くか確認します。

注意: AWS上ではpygameの別ウィンドウを使う `INTERACTIVE` モードは基本的に使いません。`SINGLE`、`BATCH`、`BATCH_PARALLEL` の利用を推奨します。

## 6. StreamlitをAWS上で起動

EC2上で実行します。

```bash
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

AWS Security Groupで、あなたの現在IPからTCP `8501` への inbound を許可してください。

ブラウザで以下へアクセスします。

```text
http://ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com:8501
```

## 7. 長時間実行する場合

SSHが切れても処理が止まらないように `tmux` を使います。

EC2上で実行します。

```bash
tmux new -s barsim
cd ~/barSetSimulation
source .venv/bin/activate
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

`tmux` から一時的に抜ける:

```text
Ctrl+B → D
```

再接続:

```bash
tmux attach -t barsim
```

## 8. 結果をローカルへ回収

ローカルPowerShellで実行します。

```powershell
scp -i "C:\Users\255396\Documents\AWS_private_key\md_yokokawa.pem" -r ec2-user@ec2-57-182-254-255.ap-northeast-1.compute.amazonaws.com:~/barSetSimulation/results_streamlit "C:\Users\255396\Documents\pythonDevPro\barset_Simulations\aws_results"
```

## 推奨運用

- 大量計算は `BATCH_PARALLEL` を使う
- AWSでは `INTERACTIVE` は使わない
- Streamlit UIで操作したい場合だけSecurity Groupで8501番を開ける
- 長時間計算は必ず `tmux` 内で実行する
- 計算完了後、不要ならEC2を停止して課金を抑える

# EC2での大量バッチ実行

大量計算には、Streamlitではなく専用CLI `aws_batch.py` を推奨します。
既存の物理計算 `main.run_single_condition_parallel` を使い、BATCH系4モードを
すべて並列実行します。既存UIと `sim_runner.py` の動作は変えていません。

## 1. EC2の準備

初めは c7i.2xlarge（8 vCPU / 16 GiB）、Python 3.12、EBS gp3を推奨します。
CPU中心の計算なのでGPUは不要です。料金・リージョンの空きはAWSで確認してください。
同じ小規模条件で8/16 vCPUの実行時間を測ってから大きくしてください。

Ubuntu 24.04の場合:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv tmux htop
# 初回だけ。既存のディレクトリがある場合は削除せず、内容を確認する。
git clone https://github.com/yok1012/barSetSimulation.git
cd barSetSimulation
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-aws.txt
# 使用した正確なバージョンを記録する
.venv/bin/python -m pip freeze > requirements-installed.txt
```

Amazon LinuxではOSに合ったパッケージ管理でPython 3.12、git、tmuxを用意し、
上のvenv作成以降を実行してください。バージョン範囲を指定した依存ファイルを
同梱していますが、Pythonやライブラリを更新した環境での再開は避けてください。

## 2. 計算条件の設定

`configs/aws_batch.json` をコピーして編集します。
`output_dir` は実行ごとに別名にします。サンプルは **7,442条件 × 100試行 = 744,200試行**
の設定で、最初は範囲と試行数を小さくしてください。

- `batch_ranges` の3整数は `[開始, 終了（含まない）, 刻み]`。
- `relative_angle` は角度のリスト。
- 摩擦係数、初速度、バラツキなどは `sim_runner.py` と同じJSON設定。
- `BATCH_V2_PARALLEL` の場合は `conditions` を明示し、条件ごとの `num_trials`、
  `bar_friction` などを設定可能。

```bash
.venv/bin/python aws_batch.py configs/aws_batch.json --dry-run
```

この確認は条件数と並列数を表示し、計算や出力先作成は行いません。

## 3. tmuxで開始・監視

```bash
tmux new -s barsim
# プロジェクトのディレクトリで実行
bash scripts/run_aws_batch.sh configs/aws_batch.json --workers 8
```

`Ctrl+B`、続けて `D` で離脱しても計算は続きます。SSHで入り直した後:

```bash
tmux attach -t barsim
```

`Ctrl+B`、続けて `C` で別ウィンドウを作り、`htop` でCPU・メモリを確認できます。
`Ctrl+B` → `0` などでウィンドウを切り替えます。

10秒ごとに保存済みタスク数、進捗率、処理速度、残り時間の目安、メモリ使用率を表示します。
ログは `logs/` に残ります。計算時間は条件によって異なるため、残り時間は概算です。
SSH（22番）以外にアプリ用ポートを開ける必要はありません。

## 4. 停止・再開

`Ctrl+C` または親プロセスへのSIGTERMで新規投入を止め、投入済みの少数タスクを
保存して終了します（終了コード130）。即時終了ではありません。

```bash
bash scripts/run_aws_batch.sh configs/aws_batch.json --workers 8 --resume
```

同一設定・同一コード・同一の主要ライブラリバージョンの場合だけ再開できます。
並列数は変更可能です。`--seed`（既定2026）、`--trials-per-task`（既定50）は
再開時に変更できません。設定の取り違えと同じ出力先への二重起動はエラーにします。
固定seedとチャンク分割により、同じ環境なら並列数や再開順序によらず同じ乱数を使います。

## 5. 結果と保存の仕組み

- `output_dir/checkpoint.sqlite3`: タスク単位の統計結果を都度コミット。
- `output_dir/simulation_results_aws.csv`: 完了・正常停止・例外終了時に、保存済みの全タスクを統合して出力。
- CSVの `num_trials` は指定数、`trials_done` は保存済みの試行数。中断時には未完了の条件が含まれます。
- 成功率、平均位置、接触回数、バラツキの標準偏差を全チャンクから統合し、保存のたびに過去結果を失う問題を防ぎます。
- `difference_from_ideal_px` の単位は現行コードのμm。`difference_from_ideal_mm` はそれを1000で割った値です。
- 試行中のプログラムエラーは単なる設置失敗と区別し、タスクを未保存のまま異常終了します。保存済み分は再利用可能です。

親プロセスが保持する投入タスクは並列数の2倍までです。条件と試行を順次生成し、
ワーカーが持つ試行結果も `--trials-per-task` の範囲に制限します。並列数の初期上限は
CPU affinityと利用可能メモリ（OS用1GiB＋1ワーカー512MiBの目安）から決めます。
厳密なメモリ上限ではないため、まず小規模実行で `htop` を確認してください。

ヒートマップ・PNG/GIFはこのCLIでは生成せず、計算とCSV保存に集中します。
Streamlitの実行ボタンからは既存経路を使うため、この再開機能は有効になりません。

## 運用上の範囲

この実装は **1台のEC2内のマルチプロセス** 用です。複数EC2への分散実行やAWS Batchへの
ジョブ投入、S3への自動保存は含みません。長時間計算ではEBSの空き容量も確認してください。
SQLiteとCSVはEBS上に置き、EC2削除時にボリュームを削除する設定なら事前に退避してください。

tmuxはEC2停止・再起動を越えてプロセスを維持できません。強制終了・停電・Spot中断では
コミット済みSQLiteから再開し、未保存チャンクだけを再計算します。
まずオンデマンドで動作確認し、途中再開と保存運用が確認できてからSpotを検討してください。

## 検証

```bash
.venv/bin/python -m unittest discover -s tests -v
```

小規模な実エンジン実行で、チャンクの集約、重複しない再開、欠落チャンクの再計算、
設定変更の拒否、並列数による再現性、条件別設定、SIGTERM後の再開を確認します。

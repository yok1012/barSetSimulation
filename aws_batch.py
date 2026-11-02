"""EC2向け: 投入数を制限した並列計算と、SQLiteによる再開可能な保存。"""
import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import csv
import hashlib
import importlib.metadata
import itertools
import json
import logging
import math
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
import time

# 数値ライブラリの内部スレッドによるCPUの過剰使用を防ぐ。import前に設定する。
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS'):
    os.environ[_key] = '1'
os.environ['MPLBACKEND'] = 'Agg'
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('1以上の整数を指定してください')
    return value


def resolve(config):
    import main
    from sim_runner import _apply_overrides
    if config.get('mode') not in ('BATCH', 'BATCH_PARALLEL', 'BATCH_V2', 'BATCH_V2_PARALLEL'):
        raise ValueError('AWS CLIはBATCH系モード専用です')
    _apply_overrides(config)
    settings = main.collect_worker_settings()
    if 'V2' in config['mode']:
        conditions = config.get('conditions')
        if not conditions:
            raise ValueError('V2ではconditionsを明示してください')
        resolved = []
        for i, cond in enumerate(conditions):
            n = positive(cond.get('num_trials', config.get('num_trials', main.NUM_TRIALS_PER_CONDITION)))
            resolved.append((main.build_v2_condition_params(cond, i),
                             main.build_v2_condition_settings(cond, settings), n))
        return resolved, len(resolved), True
    n = positive(config.get('num_trials', main.NUM_TRIALS_PER_CONDITION))
    ranges = main.BATCH_PARAM_RANGES
    names = ('angle', 'release_x_offset', 'release_y_offset', 'relative_angle')
    count = math.prod(len(ranges[k]) for k in names)
    if count == 0:
        raise ValueError('探索範囲が空です')
    # 条件の直積もタスク一覧もリスト化しない。
    conditions = ((dict(zip(names, values)), settings, n)
                  for values in itertools.product(*(ranges[k] for k in names)))
    return conditions, count, False


def tasks(conditions, chunk_size):
    for index, (params, settings, n) in enumerate(conditions):
        for start in range(0, n, chunk_size):
            yield index, start, min(start + chunk_size, n), params, settings, n


def initialize_worker():
    # Ctrl+Cは親だけが受け、ワーカーは投入済みのチャンクを完了させる。
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def calculate(task, seed):
    import random
    import main
    index, start, stop, params, settings, n = task
    digest = hashlib.sha256(f'{seed}:{index}:{start}'.encode()).digest()
    random.seed(int.from_bytes(digest[:8], 'big'))
    _, successful, trials = main.run_single_condition_parallel(
        (params, range(start + 1, stop + 1), settings))
    errors = [r['reason'] for r in trials if r['reason'].startswith('error:')]
    if errors or len(trials) != stop - start:
        raise RuntimeError(f'条件{index}, 試行{start}:{stop}: {errors[:3]}')
    row = main.summarize_condition_result(params, successful, trials, stop - start)
    row.update(main.v2_settings_columns(settings))
    row['_successes'] = len(successful)
    row['_requested_trials'] = n
    row['_means'] = {out: sum(t[key] for t in trials) / len(trials) for out, key in (
        ('x_offset_std', 'x_offset'), ('y_offset_std', 'y_offset'),
        ('angle_offset_std', 'angle_offset'))}
    return row


def combine(rows):
    """チャンクの統計量を試行数で重み付けして統合（全試行は保持しない）。"""
    result = None
    total = successes = 0
    keys = ('x_offset_std', 'y_offset_std', 'angle_offset_std')
    # バラツキの平均も保存して、チャンク間の平均差を分散へ反映する。
    moments = {k: [0.0, 0.0] for k in keys}
    contacts_sum = 0.0
    final_x = final_y = 0.0
    failures = {}
    max_contacts = 0
    for row in rows:
        if result is None:
            result = dict(row)
        n = row['trials_done']
        s = row['_successes']
        total += n
        successes += s
        contacts_sum += row['avg_short_contacts'] * n
        max_contacts = max(max_contacts, row['max_short_contacts'])
        if s:
            final_x += row['avg_final_x'] * s
            final_y += row['avg_final_y'] * s
        for key in moments:
            avg = row['_means'][key]
            moments[key][0] += avg * n
            moments[key][1] += (row[key] ** 2 + avg ** 2) * n
        for key, value in row.items():
            if key.startswith('failures_'):
                failures[key] = failures.get(key, 0) + value
    result.update(failures)
    result.update(trials_done=total, num_trials=result['_requested_trials'],
                  success_rate=100 * successes / total,
                  avg_short_contacts=contacts_sum / total, max_short_contacts=max_contacts,
                  avg_final_x=final_x / successes if successes else None,
                  avg_final_y=final_y / successes if successes else None)
    for key, (s, ss) in moments.items():
        result[key] = math.sqrt(max(0, ss / total - (s / total) ** 2))
    diff = (math.hypot(result['ideal_x'] - result['avg_final_x'],
                       result['ideal_y'] - result['avg_final_y']) if successes else None)
    result['difference_from_ideal_px'] = diff
    # 現行コードの列名を維持。位置はμmなのでmmへの変換は /1000。
    result['difference_from_ideal_mm'] = diff / 1000 if diff is not None else None
    return {k: v for k, v in result.items() if not k.startswith('_')}


def export_csv(db, path):
    temp = path.with_suffix('.csv.tmp')
    cursor = db.execute('SELECT condition_id, result FROM results ORDER BY condition_id, start')
    with temp.open('w', newline='', encoding='utf-8') as f:
        writer = None
        for _, group in itertools.groupby(cursor, key=lambda r: r[0]):
            row = combine(json.loads(r[1]) for r in group)
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def fingerprint(config, chunk_size, seed):
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ('main.py', 'sim_runner.py', 'aws_batch.py', 'heatmap_render.py')}
    versions = {name: importlib.metadata.version(name) for name in ('pymunk', 'numpy', 'pygame')}
    return encode(dict(config=config, chunk_size=chunk_size, seed=seed,
                       sources=sources, versions=versions))


def main_entry(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--workers', type=positive)
    parser.add_argument('--trials-per-task', type=positive, default=50)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    conditions, count, is_v2 = resolve(config)
    import main
    total_tasks = (sum(math.ceil(item[2] / args.trials_per_task) for item in conditions)
                   if is_v2 else count * math.ceil(main.NUM_TRIALS_PER_CONDITION / args.trials_per_task))
    import psutil
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
    # 1ワーカー512MiBを初期目安とし、OS用に1GiBを残す。
    memory_limit = max(1, int((psutil.virtual_memory().available - 1024**3) // (512 * 1024**2)))
    workers = min(args.workers or cpus, cpus, memory_limit)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('条件数=%s タスク数=%s workers=%s trials-per-task=%s', count, total_tasks, workers, args.trials_per_task)
    if args.dry_run:
        return 0
    output = Path(config['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    # 同じ出力先への二重起動を防止（EC2/Linux向け）。
    import fcntl
    with (output / '.aws_batch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('同じ出力先で既に実行中です')
        with sqlite3.connect(output / 'checkpoint.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (signature TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS results (condition_id INTEGER, start INTEGER, '
                       'result TEXT NOT NULL, PRIMARY KEY(condition_id,start))')
            signature = fingerprint(config, args.trials_per_task, args.seed)
            previous = db.execute('SELECT signature FROM metadata').fetchone()
            if previous and (not args.resume or previous[0] != signature):
                raise ValueError('既存結果があります。同一設定で--resumeするか、別のoutput_dirを指定してください')
            if not previous:
                db.execute('INSERT INTO metadata VALUES (?)', (signature,))
                db.commit()
            stopped = False
            def stop(signum, frame):
                nonlocal stopped
                stopped = True
                logging.warning('停止要求: 実行中の少数タスクを保存して終了します。再実行時は--resumeを指定してください')
            old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
            started = time.monotonic()
            completed = 0
            saved_before = db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
            last_report = started
            pending = {}
            def write_progress(state):
                elapsed = time.monotonic() - started
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = max(0, total_tasks - saved_before - completed)
                data = dict(state=state, done=saved_before + completed, total=total_tasks,
                            elapsed_seconds=elapsed,
                            eta_seconds=remaining / rate if rate else None)
                temp = output / 'progress.json.tmp'
                temp.write_text(encode(data), encoding='utf-8')
                temp.replace(output / 'progress.json')
            write_progress('running')
            finished = False
            task_iter = iter(tasks(conditions, args.trials_per_task))
            exhausted = False
            try:
                with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
                                         initializer=initialize_worker) as pool:
                    while pending or not exhausted:
                        while not stopped and not exhausted and len(pending) < 2 * workers:
                            task = next(task_iter, None)
                            if task is None:
                                exhausted = True
                                break
                            if db.execute('SELECT 1 FROM results WHERE condition_id=? AND start=?', task[:2]).fetchone():
                                continue
                            pending[pool.submit(calculate, task, args.seed)] = task[:2]
                        if not pending:
                            break
                        done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                        for future in done:
                            key = pending.pop(future)
                            row = future.result()  # 異常試行を成功扱いで保存しない。
                            db.execute('INSERT INTO results VALUES (?,?,?)', (*key, encode(row)))
                            db.commit()  # タスクごとに耐久保存。重複は主キーで防ぐ。
                            completed += 1
                        now = time.monotonic()
                        if now - last_report >= 10:
                            rate = completed / (now - started)
                            eta = (total_tasks - saved_before - completed) / rate if rate else float('inf')
                            logging.info('進捗=%s/%s (%.1f%%) 経過=%.0fs 残り目安=%.0fs 処理速度=%.2fタスク/s 実行待ち=%s メモリ使用率=%.1f%%',
                                         saved_before + completed, total_tasks,
                                         100 * (saved_before + completed) / total_tasks,
                                         now-started, eta, rate, len(pending), psutil.virtual_memory().percent)
                            write_progress('stopping' if stopped else 'running')
                            last_report = now
                        if stopped:
                            exhausted = True
                finished = True
            finally:
                write_progress('paused' if stopped else 'completed' if finished else 'failed')
                export_csv(db, output / 'simulation_results_aws.csv')
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
            logging.info('CSV保存: %s / 状態=%s', output / 'simulation_results_aws.csv', '中断' if stopped else '完了')
            return 130 if stopped else 0


if __name__ == '__main__':
    raise SystemExit(main_entry())

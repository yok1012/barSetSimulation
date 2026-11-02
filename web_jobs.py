"""Web画面と独立ワーカーが共有する、永続ジョブキュー。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

BASE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('BARSIM_JOB_ROOT', BASE / 'aws_results' / 'web')).resolve()
MODES = ('BATCH', 'BATCH_PARALLEL', 'BATCH_V2', 'BATCH_V2_PARALLEL')
TERMINAL = ('completed', 'paused', 'failed', 'interrupted')


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def database():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'queue.sqlite3', timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created TEXT, '
                   'status TEXT, workers INTEGER, chunk INTEGER, seed INTEGER, resume INTEGER, '
                   'message TEXT, finished TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS worker (id INTEGER PRIMARY KEY, heartbeat REAL)')
        yield db
        db.commit()
    finally:
        db.close()


def job_dir(job_id):
    # ブラウザから渡された識別子をパスとして解釈しない。
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('ジョブIDが不正です')
    return ROOT / job_id


def submit(config, workers=None, chunk=50, seed=2026):
    if config.get('mode') not in MODES:
        raise ValueError('AWS向け実行はBATCH系モード専用です')
    if workers is not None and (type(workers) is not int or workers < 1):
        raise ValueError('並列数は1以上にしてください')
    if type(chunk) is not int or chunk < 1:
        raise ValueError('タスクあたりの試行数は1以上にしてください')
    job_id = uuid.uuid4().hex
    folder = job_dir(job_id)
    folder.mkdir(parents=True)
    config = dict(config, output_dir=str(folder / 'results'))
    (folder / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    with database() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                   (job_id, timestamp(), 'queued', workers, chunk, int(seed), 0, '', None))
    return job_id


def list_jobs():
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC, rowid DESC LIMIT 100')]


def get_job(job_id):
    with database() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None


def request_stop(job_id):
    with database() as db:
        db.execute("UPDATE jobs SET status=CASE WHEN status='queued' THEN 'paused' ELSE 'stopping' END "
                   "WHERE id=? AND status IN ('queued','running')", (job_id,))


def request_resume(job_id):
    with database() as db:
        db.execute("UPDATE jobs SET status='queued',resume=1,message='',finished=NULL "
                   "WHERE id=? AND status IN ('paused','failed','interrupted')", (job_id,))


def heartbeat():
    with database() as db:
        db.execute('INSERT OR REPLACE INTO worker VALUES (1,?)', (time.time(),))


def worker_online():
    with database() as db:
        row = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
    return bool(row and time.time() - row[0] < 15)


def recover():
    # ワーカー再起動後は自動再開しない。画面で明示的に再開する。
    with database() as db:
        db.execute("UPDATE jobs SET status='interrupted', message='ワーカーが再起動しました。保存済み分から再開できます' "
                   "WHERE status IN ('running','stopping')")


def claim():
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,rowid LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
            return dict(row)


def finish(job_id, returncode):
    status = 'completed' if returncode == 0 else 'paused' if returncode == 130 else 'failed'
    with database() as db:
        db.execute('UPDATE jobs SET status=?,message=?,finished=? WHERE id=?',
                   (status, f'終了コード: {returncode}', timestamp(), job_id))


def read_progress(job_id):
    try:
        return json.loads((job_dir(job_id) / 'results' / 'progress.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def log_tail(job_id, limit=32768):
    try:
        with (job_dir(job_id) / 'run.log').open('rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - limit))
            return f.read().decode('utf-8', errors='replace')
    except OSError:
        return ''

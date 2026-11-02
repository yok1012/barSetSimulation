"""Streamlitとは別サービスで動く、1台のEC2用計算ワーカー。"""
import fcntl
import logging
import signal
import subprocess
import sys
import time

import web_jobs as jobs


def run():
    jobs.ROOT.mkdir(parents=True, exist_ok=True)
    with (jobs.ROOT / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        jobs.recover()
        stopping = False
        def stop(signum, frame):
            nonlocal stopping
            stopping = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, stop)
        while not stopping:
            jobs.heartbeat()
            job = jobs.claim()
            if not job:
                time.sleep(1)
                continue
            folder = jobs.job_dir(job['id'])
            command = [sys.executable, '-u', str(jobs.BASE / 'aws_batch.py'), str(folder / 'config.json'),
                       '--trials-per-task', str(job['chunk']), '--seed', str(job['seed'])]
            if job['workers']:
                command.extend(['--workers', str(job['workers'])])
            if job['resume']:
                command.append('--resume')
            try:
                with (folder / 'run.log').open('ab', buffering=0) as log:
                    proc = subprocess.Popen(command, cwd=jobs.BASE, stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                    signalled = False
                    while proc.poll() is None:
                        jobs.heartbeat()
                        if (stopping or jobs.get_job(job['id'])['status'] == 'stopping') and not signalled:
                            # 親CLIだけに通知。子計算プロセスの完了と保存を待つ。
                            try:
                                proc.send_signal(signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            signalled = True
                        time.sleep(0.5)
                    code = proc.returncode
                    # CLI初期化中の停止は、まだ専用のシグナル処理がない場合がある。
                    if signalled and code in (-signal.SIGTERM, -signal.SIGINT):
                        code = 130
                    jobs.finish(job['id'], code)
            except OSError as exc:
                logging.exception('計算プロセスを開始できません: %s', exc)
                jobs.finish(job['id'], 1)
        with jobs.database() as db:
            db.execute('DELETE FROM worker')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run()

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import web_jobs as jobs


class WebJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(jobs, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.config = dict(mode='BATCH_PARALLEL', output_dir='/ignored', num_trials=4,
                           simulation_duration=0.02,
                           batch_ranges=dict(angle=[30, 31, 1], release_x_offset=[0, 1, 1],
                                             release_y_offset=[600, 601, 1], relative_angle=[0]))

    def start_worker(self):
        env = dict(os.environ, BARSIM_JOB_ROOT=str(self.root), MPLCONFIGDIR='/tmp/barsim-mpl-test')
        log = (self.root / 'worker-test.log').open('wb')
        self.addCleanup(log.close)
        proc = subprocess.Popen([sys.executable, str(jobs.BASE / 'web_worker.py')], cwd=jobs.BASE,
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        def cleanup():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        self.addCleanup(cleanup)
        return proc

    def await_status(self, job_id, statuses, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = jobs.get_job(job_id)
            if row['status'] in statuses:
                return row
            time.sleep(0.1)
        self.fail(f'状態待機タイムアウト: {row}; {jobs.log_tail(job_id)}')

    def test_queue_claim_stop_and_resume(self):
        job_id = jobs.submit(self.config, workers=2, chunk=2)
        self.assertEqual(jobs.claim()['id'], job_id)
        self.assertIsNone(jobs.claim())
        jobs.request_stop(job_id)
        self.assertEqual(jobs.get_job(job_id)['status'], 'stopping')
        jobs.finish(job_id, 130)
        jobs.request_resume(job_id)
        row = jobs.claim()
        self.assertEqual(row['resume'], 1)
        self.assertEqual(row['id'], job_id)

    def test_outputs_isolated_and_traversal_rejected(self):
        a, b = jobs.submit(self.config), jobs.submit(self.config)
        self.assertNotEqual(a, b)
        cfg = json.loads((jobs.job_dir(a) / 'config.json').read_text())
        self.assertEqual(cfg['output_dir'], str(jobs.job_dir(a) / 'results'))
        with self.assertRaises(ValueError):
            jobs.job_dir('../../etc/passwd')

    def test_cancel_queued_job_does_not_start(self):
        job_id = jobs.submit(self.config)
        jobs.request_stop(job_id)
        self.assertIsNone(jobs.claim())
        self.assertEqual(jobs.get_job(job_id)['status'], 'paused')

    def test_worker_restart_marks_interrupted(self):
        job_id = jobs.submit(self.config)
        jobs.claim()
        jobs.recover()
        self.assertEqual(jobs.get_job(job_id)['status'], 'interrupted')
        jobs.request_resume(job_id)
        self.assertIsNotNone(jobs.claim())

    def test_real_worker_completes_and_persists_progress(self):
        job_id = jobs.submit(self.config, workers=1, chunk=2)
        self.start_worker()
        row = self.await_status(job_id, jobs.TERMINAL)
        self.assertEqual(row['status'], 'completed', jobs.log_tail(job_id))
        self.assertTrue(jobs.worker_online())
        progress = jobs.read_progress(job_id)
        self.assertEqual((progress['done'], progress['total']), (2, 2))
        self.assertTrue((jobs.job_dir(job_id) / 'results' / 'simulation_results_aws.csv').exists())
        self.assertEqual(len(list((jobs.job_dir(job_id) / 'results').glob('*_error_stage_*.png'))), 2)

    def test_real_worker_stop_resume_and_serial_queue(self):
        self.config['num_trials'] = 300
        first = jobs.submit(self.config, workers=1, chunk=2)
        second = jobs.submit(dict(self.config, num_trials=1), workers=1, chunk=2)
        self.start_worker()
        self.await_status(first, ('running',))
        deadline = time.monotonic() + 60
        while not jobs.read_progress(first) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(jobs.get_job(second)['status'], 'queued')
        jobs.request_stop(first)
        self.assertEqual(self.await_status(first, jobs.TERMINAL)['status'], 'paused', jobs.log_tail(first))
        self.assertEqual(self.await_status(second, jobs.TERMINAL)['status'], 'completed')
        jobs.request_resume(first)
        self.assertEqual(self.await_status(first, jobs.TERMINAL)['status'], 'completed', jobs.log_tail(first))

    def test_immediate_stop_before_cli_initialization(self):
        self.config['num_trials'] = 300
        job_id = jobs.submit(self.config, workers=1, chunk=2)
        self.start_worker()
        self.await_status(job_id, ('running',))
        jobs.request_stop(job_id)
        self.assertEqual(self.await_status(job_id, jobs.TERMINAL)['status'], 'paused', jobs.log_tail(job_id))

    def test_streamlit_monitor_survives_new_session(self):
        from streamlit.testing.v1 import AppTest
        job_id = jobs.submit(self.config, workers=1, chunk=2)
        self.start_worker()
        self.await_status(job_id, jobs.TERMINAL)
        app_text = 'import web_dashboard\nweb_dashboard.render()'
        for _ in range(2):
            app = AppTest.from_string(app_text).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox[0].value, job_id)
            labels = [b.label for b in app.button]
            self.assertIn('CSVダウンロードを準備', labels)
            next(b for b in app.button if b.label == 'CSVダウンロードを準備').click().run(timeout=20)
            self.assertFalse(app.exception)

    def test_existing_ui_submits_to_persistent_worker(self):
        from streamlit.testing.v1 import AppTest
        jobs.heartbeat()
        app = AppTest.from_file(str(jobs.BASE / 'streamlit_app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        next(c for c in app.checkbox if c.label == 'AWS向けに保存・再開して実行').check()
        next(r for r in app.radio if r.label == '実行モード').set_value('BATCH_PARALLEL')
        app.run(timeout=30)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == '▶ 並列実行').click().run(timeout=30)
        self.assertFalse(app.exception)
        entries = jobs.list_jobs()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['status'], 'queued')


if __name__ == '__main__':
    unittest.main()

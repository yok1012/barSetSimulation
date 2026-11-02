"""実エンジンを小規模実行し、再開・集約・並列度による再現性を確認。"""
import csv
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import aws_batch

ROOT = Path(__file__).resolve().parents[1]


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = {'mode': 'BATCH_PARALLEL', 'output_dir': str(self.folder / 'results'),
                       'num_trials': 3, 'simulation_duration': 0.02,
                       'variability': {'x': 10, 'y': 10, 'angle': 1},
                       'batch_ranges': {'angle': [20, 31, 10], 'release_x_offset': [0, 1, 1],
                                        'release_y_offset': [600, 601, 1], 'relative_angle': [0]}}
        self.path = self.folder / 'config.json'

    def command(self, *args):
        self.path.write_text(json.dumps(self.config))
        return [sys.executable, str(ROOT / 'aws_batch.py'), str(self.path),
                '--workers', '2', '--trials-per-task', '2', *args]

    def run_cli(self, *args, ok=True):
        result = subprocess.run(self.command(*args), cwd=ROOT, capture_output=True, text=True, timeout=90)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def rows(self):
        with (Path(self.config['output_dir']) / 'simulation_results_aws.csv').open() as f:
            return list(csv.DictReader(f))

    def test_resume_keeps_every_chunk_once(self):
        self.run_cli()
        original = self.rows()
        self.assertEqual(len(original), 2)
        self.assertTrue(all(r['trials_done'] == '3' for r in original))
        self.run_cli('--resume')
        self.assertEqual(self.rows(), original)
        with sqlite3.connect(Path(self.config['output_dir']) / 'checkpoint.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 4)

    def test_existing_run_requires_explicit_resume_and_same_config(self):
        self.run_cli()
        self.run_cli(ok=False)
        self.config['num_trials'] = 4
        self.run_cli('--resume', ok=False)

    def test_partial_checkpoint_recomputes_only_missing_chunk(self):
        self.run_cli()
        original = self.rows()
        with sqlite3.connect(Path(self.config['output_dir']) / 'checkpoint.sqlite3') as db:
            db.execute('DELETE FROM results WHERE condition_id=0 AND start=0')
        self.run_cli('--resume')
        self.assertEqual(self.rows(), original)

    def test_worker_count_does_not_change_results(self):
        self.run_cli()
        original = self.rows()
        self.config['output_dir'] = str(self.folder / 'single-worker')
        self.run_cli('--workers', '1')
        self.assertEqual(self.rows(), original)

    def test_v2_preserves_per_condition_settings(self):
        self.config.update(mode='BATCH_V2_PARALLEL', conditions=[
            {'label': 'a', 'num_trials': 2, 'bar_friction': 0.2},
            {'label': 'b', 'num_trials': 3, 'bar_friction': 0.8}])
        self.run_cli()
        rows = self.rows()
        self.assertEqual([r['bar_friction'] for r in rows], ['0.2', '0.8'])
        self.assertEqual([r['trials_done'] for r in rows], ['2', '3'])

    def test_dry_run_does_not_create_results(self):
        self.run_cli('--dry-run')
        self.assertFalse(Path(self.config['output_dir']).exists())

    def test_empty_range_fails(self):
        self.config['batch_ranges']['angle'] = [20, 20, 1]
        self.run_cli(ok=False)

    def test_chunk_aggregation_matches_all_trials(self):
        import main
        params = {'angle': 30}
        chunks = []
        all_trials = []
        all_successful = []
        for values in ([1, 2], [10]):
            trials = [dict(success=True, short_contacts=v, x_offset=v, y_offset=v,
                           angle_offset=v, reason='success') for v in values]
            successful = [dict(pos=(v, v), angle=0) for v in values]
            row = main.summarize_condition_result(params, successful, trials, len(values))
            row.update(_requested_trials=3, _successes=len(values),
                       _means={k: sum(values) / len(values) for k in
                               ('x_offset_std', 'y_offset_std', 'angle_offset_std')})
            chunks.append(row)
            all_trials.extend(trials)
            all_successful.extend(successful)
        combined = aws_batch.combine(chunks)
        expected = main.summarize_condition_result(params, all_successful, all_trials, 3)
        for key in ('success_rate', 'avg_final_x', 'avg_short_contacts', 'x_offset_std'):
            self.assertAlmostEqual(combined[key], expected[key])

    def test_sigterm_saves_and_resume_finishes(self):
        self.check_stop_and_resume(signal.SIGTERM)

    def test_ctrl_c_saves_and_resume_finishes(self):
        self.check_stop_and_resume(signal.SIGINT)

    def check_stop_and_resume(self, stop_signal):
        self.config['num_trials'] = 40
        self.config['simulation_duration'] = 0.1
        process = subprocess.Popen(self.command(), cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            checkpoint = Path(self.config['output_dir']) / 'checkpoint.sqlite3'
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if checkpoint.exists():
                    with sqlite3.connect(checkpoint) as db:
                        try:
                            if db.execute('SELECT COUNT(*) FROM results').fetchone()[0] > 0:
                                break
                        except sqlite3.OperationalError:
                            pass
                if process.poll() is not None:
                    self.fail('停止試験の前にプロセスが終了しました')
                time.sleep(0.1)
            else:
                self.fail('チェックポイント待機タイムアウト')
            if stop_signal == signal.SIGINT:
                os.killpg(process.pid, stop_signal)
            else:
                process.send_signal(stop_signal)
            self.assertEqual(process.wait(timeout=60), 130)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        self.run_cli('--resume')
        self.assertTrue(all(r['trials_done'] == '40' for r in self.rows()))


if __name__ == '__main__':
    unittest.main()

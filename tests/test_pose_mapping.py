import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aws_batch
import main
from pose_mapping import pose_errors, summarize_pose, render_maps


class PoseMappingTests(unittest.TestCase):
    def test_distance_and_axis_symmetry(self):
        self.assertEqual(pose_errors((3, 4), math.pi, (0, 0), 0), (5, 0))
        self.assertAlmostEqual(pose_errors((0, 0), math.radians(355), (0, 0), math.radians(5))[1], 10)
        self.assertEqual(pose_errors((0, 0), math.pi / 2, (0, 0), 0)[1], 90)

    def test_opposite_displacements_do_not_cancel(self):
        trials = [dict(final_pos=(x, 0), final_angle=0, success=False) for x in (-10, 10)]
        trials.append(dict(success=False, reason='invalid_initial_position'))
        summary = summarize_pose(trials, (0, 0), 0)
        self.assertEqual(summary['pose_samples'], 2)
        self.assertEqual(summary['mean_position_error_um'], 10)
        self.assertEqual(summary['mean_alignment_error_deg'], 0)

    def test_missing_is_not_perfect_alignment(self):
        summary = summarize_pose([{}], (0, 0), 0)
        self.assertEqual(summary['pose_samples'], 0)
        self.assertIsNone(summary['mean_position_error_um'])
        self.assertIsNone(summary['mean_alignment_error_deg'])

    def test_failed_trials_keep_final_pose(self):
        params = dict(angle=30, release_x_offset=0, release_y_offset=600, relative_angle=0)
        settings = dict(main.collect_worker_settings(), SIMULATION_DURATION=0.02)
        _, _, trials = main.run_single_condition_parallel((params, range(1, 2), settings))
        self.assertFalse(trials[0]['success'])
        self.assertIsNotNone(trials[0]['final_pos'])
        self.assertIsNotNone(trials[0]['final_angle'])

    def test_chunk_means_weight_by_valid_samples(self):
        def row(n, distance):
            result = main.summarize_condition_result({'angle': 0}, [], [], 3)
            result.update(trials_done=3, _successes=0, _requested_trials=6,
                          _means={k: 0 for k in ('x_offset_std', 'y_offset_std', 'angle_offset_std')},
                          pose_samples=n, mean_position_error_um=distance, mean_alignment_error_deg=distance)
            return result
        result = aws_batch.combine([row(1, 10), row(2, 40)])
        self.assertEqual(result['pose_samples'], 3)
        self.assertEqual(result['mean_position_error_um'], 30)
        self.assertEqual(result['mean_alignment_error_deg'], 30)

    def test_maps_separate_initial_angles_and_preserve_missing_cells(self):
        import pandas as pd
        frame = pd.DataFrame([
            dict(angle=30, relative_angle=r, release_x_offset=x, release_y_offset=y,
                 mean_position_error_um=10 if x == 0 else None, mean_alignment_error_deg=5 if x == 0 else None)
            for r in (0, 10) for x in (0, 20) for y in (100, 200)])
        with tempfile.TemporaryDirectory() as folder:
            paths = render_maps(frame, folder)
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(p.stat().st_size > 1000 for p in paths))
            self.assertEqual(render_maps(frame.assign(condition_index=range(len(frame))), folder), [])

    def test_standard_parallel_exports_pose_columns(self):
        import pandas as pd
        ranges = dict(angle=[30], release_x_offset=[0, 20], release_y_offset=[600], relative_angle=[0])
        with tempfile.TemporaryDirectory() as folder, patch.object(main, 'OUTPUT_DIR', folder), \
                patch.object(main, 'BATCH_PARAM_RANGES', ranges), patch.object(main, 'NUM_TRIALS_PER_CONDITION', 2), \
                patch.object(main, 'SIMULATION_DURATION', 0.02), patch.object(main, 'cpu_count', return_value=1), \
                patch.object(main, 'generate_heatmaps'):
            main.run_batch_mode_parallel()
            frame = pd.read_csv(Path(folder) / 'simulation_results_parallel.csv')
            self.assertEqual(len(frame), 2)
            self.assertTrue((frame.pose_samples == 2).all())
            self.assertTrue(frame.mean_position_error_um.notna().all())
            self.assertEqual(len(list(Path(folder).glob('*_error_stage_*.png'))), 2)


if __name__ == '__main__':
    unittest.main()

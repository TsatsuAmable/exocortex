#!/usr/bin/env python3
import unittest

import distillation_worker_daemon as daemon


class DistillationWorkerDaemonTests(unittest.TestCase):
    def test_run_cycle_summarizes_processed_work(self):
        fake = lambda limit: {
            'a': {'attempted': 3, 'done': 2, 'repair': 1, 'provider_errors': 0, 'queue_errors': 0},
            'b': {'attempted': 2, 'done': 2, 'repair': 0, 'provider_errors': 1, 'queue_errors': 0},
        }
        result = daemon.run_cycle(5, run_pool_fn=fake)
        self.assertEqual(result['attempted'], 5)
        self.assertEqual(result['done'], 4)
        self.assertEqual(result['repair'], 1)
        self.assertEqual(result['provider_errors'], 1)
        self.assertFalse(result['idle'])

    def test_run_cycle_marks_empty_queue_idle(self):
        fake = lambda limit: {'a': {'attempted': 0, 'done': 0, 'repair': 0, 'provider_errors': 0, 'queue_errors': 0}}
        result = daemon.run_cycle(25, run_pool_fn=fake)
        self.assertTrue(result['idle'])
        self.assertEqual(result['attempted'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

scripts = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('iraq_iq', scripts / 'iraq_iq_probe.py')
probe = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(scripts)] + sys.path):
    spec.loader.exec_module(probe)


class IraqImportTests(unittest.TestCase):
    def test_both_interpretations_preserve_bytes_and_refuse_overwrite(self):
        body = np.array([0.125+0.25j, -0.5+0.75j], dtype='<c8').tobytes() * 512
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'candidate'
            result = probe.export_prefix(body, target)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(x['read_back_equal'] and x['stored_bytes_exact'] for x in result))
            with self.assertRaises(ValueError):
                probe.export_prefix(body, target)
            self.assertEqual(Path(str(target)+'.le.sigmf-data').read_bytes(), body)

    def test_reject_incomplete_and_over_budget(self):
        for body in (b'', b'123456789', b'x'*65544):
            with self.assertRaises(ValueError):
                probe.export_prefix(body, 'unused')

    def test_analysis_retains_uncertainty_and_baseband_reference(self):
        import json
        rng = np.random.default_rng(7)
        body = (rng.choice([-0.5, -0.25, 0.25, 0.5], 8192) + 1j*rng.choice([-0.5, -0.25, 0.25, 0.5], 8192)).astype('<c8').tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'candidate'
            probe.export_prefix(body, target)
            summary = probe.analyze_hypothesis(target, 'le')
            report = json.loads(Path(summary['report']).read_text())
            self.assertEqual(report['interpretation_datatype'], 'cf32_le')
            self.assertEqual(report['frequency_reference'], 'baseband_hz')
            self.assertFalse(report['center_frequency_verified'])
            self.assertEqual(summary['analyzed_seconds'], 0.004)
            self.assertIn('unverified', summary['interpretation_status'])

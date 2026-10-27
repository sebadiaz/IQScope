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
        for body in (b'', b'123456789', b'x'*(probe.MAX_PREFIX_BYTES+8)):
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

    def test_nonfinite_alternative_does_not_prevent_valid_interpretation(self):
        # Little endian finite float with bytes that encode a big endian NaN.
        body = bytes.fromhex('7fc0003f0000803f') * 1024
        with tempfile.TemporaryDirectory() as tmp:
            result = probe.export_prefix(body, Path(tmp) / 'candidate')
            self.assertTrue(result[0]['read_back_equal'])
            self.assertEqual(result[1]['read_back_status'], 'rejected_nonfinite_interpretation')
            self.assertTrue(result[1]['stored_bytes_exact'])

    def test_recording_selection_is_exact_and_size_checked(self):
        import zipfile
        name, size = probe.RECORDINGS['vhf144']
        member = zipfile.ZipInfo(name)
        member.file_size = size
        self.assertIs(probe.select_recording([member], 'vhf144'), member)
        for members in ([], [member, member]):
            with self.assertRaises(ValueError):
                probe.select_recording(members, 'vhf144')
        member.file_size -= 1
        with self.assertRaises(ValueError):
            probe.select_recording([member], 'vhf144')

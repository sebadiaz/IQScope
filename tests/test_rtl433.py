import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from iqscope_channels import extract_channel
from iqscope_rtl433 import _run, search_rtl433, OUTPUT_LIMIT


class ChannelTests(unittest.TestCase):
    def test_separation_and_source_interval(self):
        fs = 1_000_000
        t = np.arange(200_000)/fs
        x = np.exp(2j*np.pi*220_000*t) + .7*np.exp(-2j*np.pi*260_000*t)
        y, info = extract_channel(x, fs, 220_000)
        self.assertEqual(info['sample_rate'], 250_000)
        self.assertEqual(info['source_sample_end'], len(x))
        self.assertEqual(len(y), 50_000)
        self.assertLess(np.std(y[100:-100]), .01)
        self.assertAlmostEqual(abs(np.mean(y[100:-100])), 1, places=2)
        y, info = extract_channel(x, fs, -260_000, seconds=.05)
        self.assertEqual(info['source_sample_end'], 50_000)
        self.assertTrue(info['duration_limited'])
        self.assertAlmostEqual(abs(np.mean(y[100:-100])), .7, places=2)

    def test_invalid_inputs(self):
        for rate, offset in ((0,0), (float('nan'),0), (250000,125000)):
            with self.assertRaises(ValueError):
                extract_channel(np.ones(1024),rate,offset)


class AdapterTests(unittest.TestCase):
    def test_missing_dependency_is_explicit(self):
        with patch('iqscope_rtl433.shutil.which', return_value=None):
            self.assertEqual(search_rtl433(np.ones(1024),250000,[])['status'],'unavailable')

    def test_values_preserved_without_claiming_crc_and_no_configuration(self):
        fields = {'model':'Example','temperature_C':24.6,'humidity':33,'mic':'CRC'}
        output = json.dumps(fields).encode()+b'\ninvalid\n{"model":"Bad","value":NaN}\n'
        with patch('iqscope_rtl433.shutil.which', return_value=sys.executable), patch('iqscope_rtl433._run', return_value=(0,output)) as runner:
            result=search_rtl433(np.ones(4096,dtype=complex),250000,[])
        self.assertEqual(result['messages'][0]['fields'],fields)
        self.assertFalse(result['messages'][0]['independently_validated'])
        self.assertEqual(result['channels_examined'][0]['invalid_json_lines'],2)
        argv=runner.call_args.args[0]
        self.assertEqual(argv[1:3],['-c','0'])
        self.assertIn('-r',argv)
        self.assertNotIn('-d',argv)

    def test_time_and_output_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _ = _run([sys.executable,'-c','import time; time.sleep(10)'],directory,.1)
            self.assertEqual(code,'timeout')
            code, output = _run([sys.executable,'-c',f'import sys; sys.stdout.write("x"*{OUTPUT_LIMIT*2})'],directory,3)
            self.assertEqual(code,'output_limit')
            self.assertLessEqual(len(output),OUTPUT_LIMIT)

    def test_channel_budget_and_message_limit(self):
        detections=[{'offset_hz':v,'spectral_snr_db':10} for v in range(-900000,900000,100000)]
        line=b'{"model":"Example"}\n'
        with patch('iqscope_rtl433.shutil.which',return_value=sys.executable),patch('iqscope_rtl433._run',return_value=(0,line*200)):
            result=search_rtl433(np.ones(4096,dtype=complex),2_000_000,detections)
        self.assertEqual(len(result['messages']),128)
        self.assertEqual(result['status'],'budget_exhausted')
        self.assertGreater(result['deferred_channel_count'],0)

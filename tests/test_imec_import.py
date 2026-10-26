from pathlib import Path
import tempfile
import importlib.util
import io
import sys
from unittest.mock import patch, Mock
import unittest
import numpy as np
from iqscope import read_iq
from iqscope_datasets import export_imec_hypotheses, imec_filename_metadata


class ImecImportTests(unittest.TestCase):
    def test_filename_rate_is_a_hint_and_rf_center_is_not_promoted(self):
        info = imec_filename_metadata('wf10Msps_g76_rabot_f5240MHz_r1.bin')
        self.assertEqual(info['sample_rate_hz'],10000000)
        self.assertEqual(info['filename_center_hint_hz'],5240000000)
        self.assertEqual(imec_filename_metadata('lte_test.bin')['sample_rate_source'],'authors_default_not_measured')
        with self.assertRaises(ValueError):
            imec_filename_metadata('wf1Msps_2Msps.bin')

    def test_both_byte_orders_roundtrip_without_selecting_one(self):
        rng = np.random.default_rng(104)
        raw = rng.integers(-1000,1000,(4096,2),dtype=np.int16).astype('<i2').tobytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'wf1Msps_test_f5240MHz.bin'
            path.write_bytes(raw)
            result = export_imec_hypotheses(path,Path(directory)/'out',max_bytes=8192)
            self.assertIsNone(result['selected_hypothesis'])
            self.assertFalse(result['endianness_verified'])
            self.assertEqual(result['sample_count'],2048)
            for interpretation in result['interpretations']:
                x,fs,center = read_iq(interpretation['metadata'])
                self.assertEqual(center,0)
                self.assertEqual(fs,1000000)
                order = interpretation['byte_order_hypothesis']
                restored = np.empty((len(x),2),dtype='<i2' if order=='le' else '>i2')
                restored[:,0] = np.rint(x.real*32768)
                restored[:,1] = np.rint(x.imag*32768)
                self.assertEqual(restored.tobytes(),raw[:8192])
            from iqscope import analyze
            report = analyze(result['interpretations'][0]['metadata'],Path(directory)/'analysis')
            self.assertEqual(report['interpretation_status'],'unverified_byte_order_and_header_layout')
            self.assertEqual(report['interpretation_datatype'],'ci16_le')
            with self.assertRaises(ValueError):
                export_imec_hypotheses(path,Path(directory)/'out')

    def test_odd_source_and_small_prefix_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.bin'
            for payload in (b'x'*4097,b'x'*100):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    export_imec_hypotheses(path,Path(directory)/'out')


class ImecPrefixNetworkTests(unittest.TestCase):
    def load_probe(self):
        root = Path(__file__).parents[1]/'scripts'
        spec = importlib.util.spec_from_file_location('imec_catalog_probe',root/'imec_catalog_probe.py')
        metadata = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(metadata)
        spec = importlib.util.spec_from_file_location('imec_prefix_probe',root/'imec_iq_prefix.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'imec_catalog_probe':metadata}):
            spec.loader.exec_module(module)
        return module

    def test_paths_stay_inside_the_fixed_share(self):
        module = self.load_probe()
        self.assertEqual(module.checked_path(module.ROOT+'rabot/test.bin'),module.ROOT+'rabot/test.bin')
        for path in ('https://example.org/a',module.ROOT+'%2e%2e/test.bin',module.ROOT+'test.bin?download=1','/public.php/dav/files/other/test.bin'):
            with self.assertRaises(ValueError):
                module.checked_path(path)

    def test_ignored_range_is_still_bounded(self):
        module = self.load_probe()
        class Response(io.BytesIO):
            read_bytes = 0
            def read(self,count=-1):
                value = super().read(count)
                self.read_bytes += len(value)
                return value
        response = Response(b'x'*1048576)
        response.status = 200
        response.headers = {'Content-Type':'application/octet-stream'}
        opener = Mock()
        opener.open.return_value = response
        with patch.object(module.urllib.request,'build_opener',return_value=opener):
            data,http = module.download_prefix({'href':module.ROOT+'rabot/test.bin','bytes':'1048576'})
        self.assertEqual(len(data),262144)
        self.assertEqual(response.read_bytes,262144)
        self.assertEqual(http['source_file_bytes'],1048576)

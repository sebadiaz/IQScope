import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from iqscope import read_iq
from iqscope_datasets import catalog, export_panoradio_window


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, data):
        path = self.root/'source.npy'
        np.save(path,data)
        return path

    def test_selected_window_round_trip_and_provenance(self):
        data = np.array([np.zeros(2048),np.exp(2j*np.pi*.01*np.arange(2048))],dtype=np.complex128)
        result = export_panoradio_window(self.source(data),self.root/'window',record=1)
        x,fs,center = read_iq(result['metadata'])
        np.testing.assert_allclose(x,data[1],rtol=1e-6)
        self.assertEqual(len(x),2048)
        self.assertEqual(fs,6000)
        self.assertEqual(center,0)
        provenance = json.loads(Path(result['provenance']).read_text())
        self.assertEqual(provenance['record_index'],1)
        self.assertFalse(provenance['continuous_across_rows'])
        self.assertIsNone(provenance['class_label'])
        self.assertIsNone(provenance['full_source_hash'])

    def test_reject_invalid_layout_and_pickle_objects(self):
        for data in [np.zeros((1,2048)),np.zeros((2,1024),dtype=complex),np.zeros((1,2,2048),dtype=complex),np.array([{'x':1}],dtype=object)]:
            with self.assertRaises(ValueError):
                export_panoradio_window(self.source(data),self.root/'bad')

    def test_index_and_nonfinite_data(self):
        path = self.source(np.zeros((2,2048),dtype=complex))
        for record in (-1,2):
            with self.assertRaises(ValueError):
                export_panoradio_window(path,self.root/'bad',record=record)
        data = np.zeros((1,2048),dtype=complex)
        data[0,4] = np.nan
        with self.assertRaisesRegex(ValueError,'non-finite'):
            export_panoradio_window(self.source(data),self.root/'bad')

    def test_refuse_to_overwrite_any_output(self):
        path = self.source(np.zeros((1,2048),dtype=complex))
        target = self.root/'out.sigmf-meta'
        target.write_text('existing')
        with self.assertRaisesRegex(ValueError,'exists'):
            export_panoradio_window(path,self.root/'out')
        self.assertEqual(target.read_text(),'existing')
        self.assertFalse((self.root/'out.sigmf-data').exists())

    def test_catalog_does_not_claim_all_sources_are_integrated(self):
        entries = catalog()['entries']
        ids = [entry['id'] for entry in entries]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(ids),17)
        self.assertIsNone(next(e for e in entries if e['id']=='imec_subghz')['adapter'])
        self.assertEqual(next(e for e in entries if e['id']=='satellite_recordings')['kind'],'real_mono_waveforms')

    def test_bounded_npy_prefix_does_not_flatten_rows(self):
        import io
        spec = importlib.util.spec_from_file_location('panoradio_probe',Path(__file__).parents[1]/'scripts/panoradio_smoke.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = np.array([np.ones(2048)*1j,np.ones(2048)*2j],dtype=np.complex128)
        stream = io.BytesIO()
        np.save(stream,data)
        prefix = stream.getvalue()[:128+2048*16]
        row, info = module.parse_first_window(prefix)
        np.testing.assert_array_equal(row,data[0])
        self.assertEqual(info['source_shape'],[2,2048])
        with self.assertRaises(ValueError):
            module.parse_first_window(prefix[:256])


if __name__ == '__main__':
    unittest.main()

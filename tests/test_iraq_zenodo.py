import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

scripts = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('iraq_probe', scripts / 'iraq_zenodo_probe.py')
probe = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(scripts)] + sys.path):
    spec.loader.exec_module(probe)


class IraqDocumentationTests(unittest.TestCase):
    def test_archives_and_oversized_documents_are_not_requested(self):
        doc = {'id': 22019720, 'files': [
            {'key': 'Day1.zip', 'size': 5_000_000_000},
            {'key': 'README_Iraq_RF_Spectrum_Dataset_Part1_FINAL.md', 'size': 262145}]}
        with patch.object(probe.urllib.request, 'build_opener') as opener:
            result = probe.inspect_documents(doc, '22019720')
        opener.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertIn('error', result[0])
        with self.assertRaises(ValueError):
            probe.inspect_documents(doc, '22036530')

    def test_csv_integrity_and_mismatch(self):
        body = b'day,sample_rate\n1,2048000\n2,2048000\n'
        doc = {'id': 22071547, 'files': [{'key': 'Iraq_RF_Master_Metadata_FINAL.csv',
                'size': len(body), 'checksum': 'md5:' + hashlib.md5(body).hexdigest()}]}
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        with patch.object(probe.urllib.request, 'build_opener', return_value=opener):
            result = probe.inspect_documents(doc, '22071547')[0]
        self.assertTrue(result['published_md5_verified'])
        self.assertEqual(result['rows'], 2)
        self.assertEqual(result['column_values']['sample_rate'], ['2048000'])
        opener.open.return_value = io.BytesIO(b'x' * len(body))
        with patch.object(probe.urllib.request, 'build_opener', return_value=opener):
            result = probe.inspect_documents(doc, '22071547')[0]
        self.assertIn('error', result)
        self.assertNotIn('first_rows', result)

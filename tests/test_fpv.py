import importlib.util
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from iqscope_datasets import fpv_annotations

spec = importlib.util.spec_from_file_location('fpv_probe',Path(__file__).parents[1]/'scripts/fpv_metadata_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

HEADER = 'id,drone_freq,vtx_power_mw'+chr(92)+',distance _m,environment,obtacles,floor_diff,hackrf_lna,hackrf_vga,samples_per_freq,sample_rate,iq_folder,notes\n'
NEGATIVE = '1,none,0,0,room,none,0,32,32,10,20,sweep_a,\n'
POSITIVE = '2,1240,25,5-27,room,movement,0,32,32,10,20,sweep_b,\n'


class FpvAnnotationTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'meta.csv'
            path.write_text(text)
            return fpv_annotations(path)

    def test_source_header_quirks_units_and_distance_range(self):
        result = self.parse(HEADER+NEGATIVE+POSITIVE)
        self.assertEqual(result['summary'],{'sweeps':2,'tx_active':1,'tx_inactive':1})
        row = result['recordings'][1]
        self.assertEqual(row['distance_raw'],'5-27')
        self.assertEqual(row['sample_rate_raw'],'20')
        self.assertIsNone(row['sample_rate_unit'])
        self.assertIsNone(row['transmitter_frequency_unit'])
        self.assertEqual(row['source_row']['obstacles'],'movement')
        self.assertIn('not_each_IQ_window',row['label_scope'])

    def test_duplicate_and_inconsistent_annotations_rejected(self):
        for rows in (NEGATIVE+NEGATIVE,NEGATIVE.replace('none,0','none,25'),POSITIVE.replace('1240,25','1240,0')):
            with self.assertRaises(ValueError):
                self.parse(HEADER+rows)

    def test_extra_columns_and_empty_annotations_rejected(self):
        for text in (HEADER,HEADER+NEGATIVE.rstrip()+'extra,field\n'):
            with self.assertRaises(ValueError):
                self.parse(text)


class Response:
    def __init__(self,data,status,header):
        self.body = io.BytesIO(data)
        self.status = status
        self.headers = {'Content-Range':header}

    def read(self,count):
        return self.body.read(count)

    def __enter__(self):
        return self

    def __exit__(self,*args):
        return False


class RangeArchiveTests(unittest.TestCase):
    def test_read_metadata_without_extracting_large_iq_member(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('sweep/iq.bin',bytes(1024*1024))
            archive.writestr('sweep/metadata.csv',b'offset,frequency\n0,123\n')
        content = stream.getvalue()
        requests = []
        def request(req,timeout):
            start,end = map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',req.get_header('Range')).groups())
            requests.append((start,end))
            return Response(content[start:end+1],206,f'bytes {start}-{end}/{len(content)}')
        with patch.object(probe.urllib.request,'urlopen',side_effect=request):
            with probe.RangeReader('https://example.org/file.zip',budget=8192) as remote:
                with zipfile.ZipFile(remote) as archive:
                    self.assertEqual(archive.read('sweep/metadata.csv'),b'offset,frequency\n0,123\n')
                self.assertLess(remote.received,8192)
        self.assertGreater(len(requests),1)

    def test_ignored_or_wrong_ranges_refused(self):
        for status,header in ((200,''),(206,'bytes 1-1/100')):
            with patch.object(probe.urllib.request,'urlopen',return_value=Response(b'x',status,header)):
                with self.assertRaisesRegex(ValueError,'exact HTTP ranges'):
                    probe.RangeReader('https://example.org/file.zip')

    def test_transfer_budget_checked_before_fetch(self):
        response = Response(b'x',206,'bytes 0-0/1000000')
        with patch.object(probe.urllib.request,'urlopen',return_value=response) as request:
            remote = probe.RangeReader('https://example.org/file.zip',budget=10)
            with self.assertRaisesRegex(ValueError,'budget'):
                remote.read(1000)
            self.assertEqual(request.call_count,1)


if __name__ == '__main__':
    unittest.main()

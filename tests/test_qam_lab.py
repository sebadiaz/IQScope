import unittest
import numpy as np
from scripts.qam_lab_reference import read_keysight_csv


def export_fixture(count=1024):
    x=np.arange(count)/1000+1j*(np.arange(count)[::-1]/700)
    rows=['MeasResult','BASIC:WAV','Center Frequency,28000000000',
          f'WAV_Used_CaptureTime,{(count-1)*5e-9}',
          'MeasResult0,MeasResult1,MeasResult2']
    scalars=[5e-9,-20,-20,count,6,-14,-90]
    for index,value in enumerate(np.column_stack((x.real,x.imag)).ravel()):
        rows.append(f'{value},{scalars[index] if index<7 else ""},-999')
    return '\n'.join(rows).encode(),x


class QamLaboratoryFormatTests(unittest.TestCase):
    def test_interleaved_iq_and_physical_metadata(self):
        raw,expected=export_fixture()
        x,fs,layout=read_keysight_csv(raw)
        np.testing.assert_array_equal(x,expected)
        self.assertEqual(fs,200e6)
        self.assertEqual(layout['sample_count'],len(expected))
        self.assertEqual(layout['center_frequency_hz'],28e9)

    def test_inconsistent_and_nonfinite_exports_are_refused(self):
        raw,_=export_fixture()
        for invalid in (raw.replace(b'BASIC:WAV',b'BASIC:SPEC'),
                        raw.replace(b',1024,',b',1025,'),
                        raw.replace(b'5e-09,',b'1e-08,'),
                        raw.replace(b'0.0,',b'nan,',1),
                        raw.rsplit(b'\n',1)[0]):
            with self.assertRaises(ValueError):read_keysight_csv(invalid)

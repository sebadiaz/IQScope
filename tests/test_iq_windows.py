import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

from iqscope import analyze,main,read_iq
from iqscope_iq_windows import read_iq_window
from test_formats import make_wave,chunk


class IQWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_seek_reads_only_selected_samples(self):
        path=self.root/'raw.cf32'
        data=(np.arange(20000)+1j*np.arange(20000)[::-1]).astype('<c8');data.tofile(path)
        original=np.fromfile
        with patch('iqscope_iq_windows.np.fromfile',wraps=original) as reader:
            x,fs,center,w=read_iq_window(path,24000,seconds=.1,start_sample=4097)
        np.testing.assert_array_equal(x,data[4097:6497])
        self.assertEqual(reader.call_args.kwargs['offset'],4097*8)
        self.assertEqual(reader.call_args.kwargs['count'],2400)
        self.assertEqual((w['start_sample'],w['end_sample'],w['total_samples']),(4097,6497,20000))
        self.assertEqual((fs,center),(24000,0))

    def test_all_sigmf_encodings_preserve_interleaved_sample_alignment(self):
        for name,dtype in [('cf32_le','<c8'),('cf32_be','>c8'),('ci16_le','<i2'),('ci16_be','>i2'),('cu8','u1')]:
            path=self.root/(name+'.sigmf-data')
            if 'cf32' in name:
                data=(np.arange(10000)/20000+1j*np.arange(10000)[::-1]/20000).astype(dtype)
                expected=data.astype(np.complex64)
            else:
                raw=np.arange(20000)%200 if name=='cu8' else np.arange(20000)-10000
                np.asarray(raw,dtype=dtype).tofile(path)
                values=(raw.astype(np.float32)-127.5)/127.5 if name=='cu8' else raw.astype(np.float32)/32768
                expected=values[::2]+1j*values[1::2];data=None
            if data is not None:data.tofile(path)
            path.with_suffix('.sigmf-meta').write_text(json.dumps({'global':{'core:datatype':name,'core:sample_rate':24000},'captures':[{'core:frequency':145000000}]}))
            x,fs,center,w=read_iq_window(path,seconds=.1,start_sample=3001)
            np.testing.assert_array_equal(x,expected[3001:5401])
            self.assertEqual(center,145000000)

    def test_wave_pcm_float_and_packed24_seek_past_metadata(self):
        for bits,encoding,dtype in [(8,1,'u1'),(16,1,'<i2'),(24,1,None),(32,1,'<i4'),(32,3,'<f4'),(64,3,'<f8')]:
            integers=np.arange(20000)%200-100
            if bits==24:
                payload=b''.join(int(v&0xffffff).to_bytes(3,'little') for v in integers)
            else:
                payload=np.asarray(integers+128 if bits==8 else integers,dtype=dtype).tobytes()
            path=self.root/'sample.wav';path.write_bytes(make_wave(payload,bits=bits,encoding=encoding,center=868000000))
            full,_,_=read_iq(path,limit_seconds=1)
            x,fs,center,w=read_iq_window(path,seconds=.1,start_sample=3001)
            np.testing.assert_array_equal(x,full[3001:5401])
            self.assertEqual(center,868000000)

    def test_rf64_and_sdriq_endianness_seek(self):
        raw=np.arange(20000,dtype='<i2').tobytes()
        fmt=chunk(b'fmt ',struct.pack('<HHIIHH',1,2,24000,96000,4,16))
        total=12+36+len(fmt)+8+len(raw)
        ds64=chunk(b'ds64',struct.pack('<QQQI',total-8,len(raw),10000,0))
        path=self.root/'sample.wav';path.write_bytes(b'RF64'+b'\xff'*4+b'WAVE'+ds64+fmt+b'data'+b'\xff'*4+raw)
        full,_,_=read_iq(path,limit_seconds=1)
        x,_,_,_=read_iq_window(path,seconds=.1,start_sample=3001)
        np.testing.assert_array_equal(x,full[3001:5401])
        for endian,bits,width in [('<',16,2),('<',24,4),('>',24,4)]:
            header=struct.pack(endian+'IQQII',24000,77500,0,bits,0)
            header+=struct.pack(endian+'I',zlib.crc32(header))
            raw=np.arange(20000,dtype=endian+f'i{width}').tobytes()
            path=self.root/'sample.sdriq';path.write_bytes(header+raw)
            full,_,_=read_iq(path,limit_seconds=1)
            x,_,center,w=read_iq_window(path,seconds=.1,start_sample=3001)
            np.testing.assert_array_equal(x,full[3001:5401]);self.assertEqual(center,77500)

    def test_integer_navigation_has_no_gaps_at_fractional_second_boundaries(self):
        path=self.root/'samples.cf32';np.zeros(12000,dtype='<c8').tofile(path)
        first=read_iq_window(path,39062,seconds=.1)[3]
        second=read_iq_window(path,39062,seconds=.1,start_sample=first['next_start_sample'])[3]
        third=read_iq_window(path,39062,seconds=.1,start_sample=second['next_start_sample'])[3]
        self.assertEqual([first['start_sample'],first['end_sample'],second['end_sample'],third['end_sample']],[0,3906,7812,11718])
        self.assertEqual(second['previous_start_sample'],0)
        self.assertIsNone(third['next_start_sample']);self.assertEqual(third['remaining_samples'],282)
        self.assertEqual(read_iq_window(path,39062,seconds=.1,start_seconds=.1)[3]['start_sample'],3906)

    def test_sample_budget_and_eof_are_reported_without_loading_the_prefix(self):
        path=self.root/'large.cf32'
        with path.open('wb') as handle:handle.truncate(8200000*8)
        x,_,_,w=read_iq_window(path,2400000,seconds=120,start_sample=100000)
        self.assertEqual(len(x),8000000);self.assertTrue(w['sample_budget_limited'])
        self.assertEqual(w['next_start_sample'],8100000)
        x,_,_,tail=read_iq_window(path,2400000,seconds=120,start_sample=w['next_start_sample'])
        self.assertEqual(len(x),100000);self.assertIsNone(tail['next_start_sample'])
        self.assertEqual(tail['previous_start_sample'],100000)

    def test_invalid_start_and_incomplete_source_are_rejected(self):
        path=self.root/'samples.cf32';np.zeros(10000,dtype='<c8').tofile(path)
        for kwargs in [dict(start_seconds=-1),dict(start_seconds=float('nan')),dict(start_seconds=float('inf')),
                       dict(start_sample=True),dict(start_sample=-1),dict(start_sample=1.5),
                       dict(start_seconds=.1,start_sample=1),dict(start_sample=9999),dict(start_sample=10**30)]:
            with self.assertRaises(ValueError):read_iq_window(path,24000,seconds=.1,**kwargs)
        with path.open('ab') as handle:handle.write(b'x')
        with self.assertRaisesRegex(ValueError,'incomplete'):read_iq_window(path,24000,start_seconds=.1)

    def test_cli_seeks_and_preserves_window_metadata_in_saved_report(self):
        path=self.root/'samples.cf32';np.zeros(12000,dtype='<c8').tofile(path)
        out=self.root/'cli';capture=io.StringIO()
        with patch('sys.argv',['iqscope','analyze',str(path),'--sample-rate','24000','--seconds','.1','--start-seconds','.2','--out',str(out)]),patch('sys.stdout',capture):
            main()
        report=json.loads(capture.getvalue())
        self.assertEqual(report['source_sample_start'],4800)
        self.assertEqual(report['source_sample_end'],7200)
        self.assertEqual(json.loads((out/'report.json').read_text()),report)

    def test_late_fm_packet_is_decoded_in_a_seeked_window(self):
        from test_afsk_fm import fixture
        x=np.r_[np.zeros(12*48000,dtype=np.complex64),fixture(offset=0,payload=b'>late file window')]
        path=self.root/'late.cf32';x.astype('<c8').tofile(path)
        report=analyze(path,self.root/'late-out',sample_rate=48000,seconds=5,start_seconds=12)
        trial=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_fm_ax25')
        self.assertEqual(len(trial['frames']),4)
        self.assertEqual(report['source_sample_start'],576000)
        self.assertEqual(trial['source_window_reference']['start_sample'],576000)
        self.assertEqual(json.loads((self.root/'late-out'/trial['artifact']).read_text()),trial)
        self.assertTrue(all(f['fcs_valid'] and f['fields']['text']=='>late file window' for f in trial['frames']))
        self.assertAlmostEqual(report['source_window']['start_seconds']+trial['frames'][0]['time_seconds'],12+80/1200,delta=2/1200)

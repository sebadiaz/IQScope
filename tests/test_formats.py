import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile
import zlib

import numpy as np

from iqscope import read_iq
from iqscope_formats import read_wave_iq


def chunk(kind, data):
    return struct.pack('<4sI', kind, len(data))+data+(b'\0' if len(data)%2 else b'')


def make_wave(payload, bits=16, encoding=1, fs=24000, channels=2, center=None):
    align = channels*(bits//8)
    parts = chunk(b'fmt ',struct.pack('<HHIIHH',encoding,channels,fs,fs*align,align,bits))
    parts += chunk(b'JUNK',b'abc')
    if center is not None:
        parts += chunk(b'auxi',b'\0'*32+struct.pack('<I',center)+b'\0'*128)
    parts += chunk(b'data',payload)
    return b'RIFF'+struct.pack('<I',len(parts)+4)+b'WAVE'+parts


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data):
        p = self.root/name
        p.write_bytes(data)
        return p

    def test_stereo_pcm_wave_and_auxi(self):
        raw = np.tile(np.array([16384,-8192],dtype='<i2'),4096).tobytes()
        path = self.write('sample.wav',make_wave(raw,center=1090000000))
        x,fs,center = read_iq(path)
        self.assertTrue(np.allclose(x,.5-.25j))
        self.assertEqual(fs,24000)
        self.assertEqual(center,1090000000)

    def test_packed_24_bit_and_float_wave(self):
        integers = np.tile([4194304,-2097152],2048)
        packed = b''.join(int(v & 0xFFFFFF).to_bytes(3,'little') for v in integers)
        x,_,_ = read_iq(self.write('packed.wav',make_wave(packed,bits=24)))
        self.assertTrue(np.allclose(x,.5-.25j))
        raw = np.tile(np.array([.5,-.25],dtype='<f4'),2048).tobytes()
        x,_,_ = read_iq(self.write('float.wav',make_wave(raw,bits=32,encoding=3)))
        self.assertTrue(np.allclose(x,.5-.25j))

    def test_mono_audio_is_not_iq(self):
        data = np.zeros(2048,dtype='<i2').tobytes()
        with self.assertRaisesRegex(ValueError,'two channels'):
            read_iq(self.write('mono.wav',make_wave(data,channels=1)))

    def test_truncated_wave_rejected_but_explicit_prefix_readable(self):
        raw = np.tile(np.array([16384,-8192],dtype='<i2'),8192).tobytes()
        path = self.write('prefix.wav',make_wave(raw)[:-4096])
        with self.assertRaisesRegex(ValueError,'truncated'):
            read_iq(path)
        x,_,_ = read_wave_iq(path,allow_prefix=True)
        self.assertTrue(np.allclose(x,.5-.25j))

    def test_sdriq_crc_storage_width_and_endianness(self):
        for endian,bits,width in (('<',16,2),('<',24,4),('>',24,4)):
            header = struct.pack(endian+'IQQII',192000,77500,1700000000000,bits,0)
            header += struct.pack(endian+'I',zlib.crc32(header))
            values = np.tile(np.array([2**(bits-2),-2**(bits-3)],dtype=endian+f'i{width}'),2048)
            x,fs,center = read_iq(self.write('sample.sdriq',header+values.tobytes()))
            self.assertTrue(np.allclose(x,.5-.25j))
            self.assertEqual(fs,192000)
            self.assertEqual(center,77500)
        corrupted = bytearray(header+values.tobytes())
        corrupted[0] ^= 1
        with self.assertRaisesRegex(ValueError,'CRC'):
            read_iq(self.write('bad.sdriq',corrupted))

    def test_sdriq_incomplete_sample_and_range(self):
        header = struct.pack('<IQQII',48000,100000000,0,24,0)
        header += struct.pack('<I',zlib.crc32(header))
        with self.assertRaisesRegex(ValueError,'incomplete'):
            read_iq(self.write('partial.sdriq',header+b'12345'))
        raw = np.full(4096,2**30,dtype='<i4').tobytes()
        with self.assertRaisesRegex(ValueError,'24-bit range'):
            read_iq(self.write('range.sdriq',header+raw))

    def test_rf64_with_ds64(self):
        raw = np.zeros(4096,dtype='<i2').tobytes()
        fmt = chunk(b'fmt ',struct.pack('<HHIIHH',1,2,24000,96000,4,16))
        total = 12+36+len(fmt)+8+len(raw)
        ds64 = chunk(b'ds64',struct.pack('<QQQI',total-8,len(raw),len(raw)//4,0))
        file = b'RF64'+b'\xff'*4+b'WAVE'+ds64+fmt+b'data'+b'\xff'*4+raw
        x,fs,_ = read_iq(self.write('rf64.wav',file))
        self.assertEqual(len(x),2048)
        self.assertEqual(fs,24000)

    def test_streaming_zip_excerpt_is_bounded(self):
        spec = importlib.util.spec_from_file_location('corpus_script',Path(__file__).parents[1]/'scripts/sdrangel_corpus.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = make_wave(np.tile(np.array([123,-456],dtype='<i2'),50000).tobytes())
        for compression in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream,'w',compression=compression) as archive:
                archive.writestr('folder/',b'')
                archive.writestr('folder/capture.wav',payload)
            stream.seek(0)
            name, prefix, received = module.first_iq_prefix(stream,output_limit=8192)
            self.assertEqual(name,'folder/capture.wav')
            self.assertEqual(len(prefix),8192)
            self.assertEqual(prefix,payload[:8192])
            x,fs,_ = read_wave_iq(self.write('prefix.wav',prefix),allow_prefix=True)
            self.assertEqual(fs,24000)
            self.assertGreater(len(x),1024)

    def test_zip_download_retries_once_without_accepting_invalid_prefix(self):
        spec = importlib.util.spec_from_file_location('corpus_retry_script',Path(__file__).parents[1]/'scripts/sdrangel_corpus.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = make_wave(np.tile(np.array([123,-456],dtype='<i2'),50000).tobytes())
        archive = io.BytesIO()
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as handle:
            handle.writestr('capture.wav',payload)
        invalid = io.BytesIO(b'not a ZIP file'*20)
        valid = io.BytesIO(archive.getvalue())
        for response in (invalid,valid):
            response.status = 200
            response.headers = {}
        with patch.object(module.urllib.request,'urlopen',side_effect=[invalid,valid]) as fetch:
            _,prefix,_ = module.download_prefix('https://example.org/test.zip',8192)
            self.assertEqual(prefix,payload[:8192])
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(fetch.call_args.args[0].get_header('Range'),'bytes=0-')
        with patch.object(module.urllib.request,'urlopen',side_effect=ValueError('bad ZIP')) as fetch:
            with self.assertRaises(ValueError):
                module.download_prefix('https://example.org/test.zip',8192)
            self.assertEqual(fetch.call_count,2)


if __name__ == '__main__':
    unittest.main()

"""Independent APT transmitter fixture; tests image recovery, rejection and budgets."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

import numpy as np
from scipy import signal

from iqscope_apt import search_apt,write_apt_artifacts,_correlation,SYNC_A,SYNC_B


def fixture(fs=62500,lines=9,clock_ppm=0,offset=0,inverted=False,missing_b=False,line_seconds=.5,bad_b_row=None):
    # NOAA pulse positions, independently specified rather than importing receiver templates.
    a=np.zeros(39);b=np.zeros(39)
    for pulse in range(7):
        a[4+4*pulse:6+4*pulse]=1
        b[4+5*pulse:7+5*pulse]=1
    rows=[]
    for row in range(lines):
        video_a=.15+.7*(np.arange(909)//100%2)
        video_b=np.linspace(.1,.9,909) if row%2 else np.linspace(.9,.1,909)
        rows.append(np.concatenate((a,np.ones(47)*.2,video_a,np.ones(45)*.7,
                                   np.ones(39)*.4 if missing_b or row==bad_b_row else b,np.ones(47)*.8,video_b,np.ones(45)*.5)))
    source=np.array(rows).ravel()
    word_rate=2080/line_seconds*(1+clock_ppm*1e-6)
    t=np.arange(int(fs*(len(source)/word_rate+.13)))/fs
    word_index=(t-.073)*word_rate
    levels=np.interp(word_index,np.arange(len(source))+.5,source,left=.3,right=.3)
    audio=(.2+.8*levels)*np.cos(2*np.pi*2400*t+.7)
    audio=signal.convolve(audio,signal.firwin(101,4500,fs=fs),mode='same')
    iq=np.exp(2j*np.pi*(np.cumsum(audio*15000)/fs+offset*t))
    if inverted:iq=iq.conj()
    rng=np.random.default_rng(862);iq+=.003*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    return iq,fs,np.array(rows)


def png_pixels(data):
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    pos=8;compressed=b''
    while pos<len(data):
        count=struct.unpack_from('>I',data,pos)[0];kind=data[pos+4:pos+8];payload=data[pos+8:pos+8+count]
        assert zlib.crc32(kind+payload)&0xffffffff==struct.unpack_from('>I',data,pos+8+count)[0]
        if kind==b'IHDR':width,height,depth,color,*_=struct.unpack('>IIBBBBB',payload);assert (depth,color)==(8,0)
        if kind==b'IDAT':compressed+=payload
        pos+=count+12
    raw=np.frombuffer(zlib.decompress(compressed),dtype='u1').reshape(height,width+1)
    assert not raw[:,0].any()
    return raw[:,1:]


class APTTests(unittest.TestCase):
    def test_recovers_known_image_pixels_and_both_sync_patterns(self):
        x,fs,source=fixture()
        trial=search_apt(x,fs,[])
        self.assertEqual(trial['status'],'image_candidates')
        image=trial['images'][0]
        self.assertGreaterEqual(image['height'],7)
        pixels=np.frombuffer(bytes.fromhex(image['pixels_u8_hex']),dtype='u1').reshape(image['height'],2080)
        for row in pixels:
            self.assertGreater(np.corrcoef(row[100:980],source[0,100:980])[0,1],.98)
        self.assertAlmostEqual(image['time_seconds'],.073,delta=2/4160)
        self.assertTrue(all(line['sync_b_correlation']>=.6 for line in image['lines']))
        self.assertNotIn('frames',trial)

    def test_sample_rates_clock_error_translation_and_iq_inversion(self):
        for fs,ppm,inverted in [(48000,-800,False),(96000,700,True),(192000,0,False)]:
            offset=38000 if fs==192000 else 0
            x,_,_=fixture(fs=fs,lines=7,clock_ppm=ppm,offset=offset,inverted=inverted)
            with self.subTest(fs=fs):
                trial=search_apt(x,fs,[dict(offset_hz=offset,bandwidth_hz=34000)])
                self.assertTrue(trial['images'])
                line=trial['images'][0]['lines'][0]
                self.assertAlmostEqual(line['clock_error_ppm'],-ppm,delta=350)

    def test_rejects_missing_second_sync_wrong_line_clock_and_too_short_runs(self):
        for options in [dict(missing_b=True),dict(line_seconds=.53),dict(lines=3)]:
            x,fs,_=fixture(**options)
            with self.subTest(options=options):self.assertFalse(search_apt(x,fs,[])['images'])

    def test_rejects_noise_tone_and_unrelated_analog_fm(self):
        fs=48000;t=np.arange(fs*3)/fs;rng=np.random.default_rng(6)
        for x in [np.zeros(len(t),complex),np.exp(2j*np.pi*2400*t),
                  rng.normal(size=len(t))+1j*rng.normal(size=len(t)),
                  np.exp(1j*7*np.sin(2*np.pi*1000*t)),
                  np.exp(2j*np.pi*np.cumsum(15000*np.cos(2*np.pi*2400*t))/fs)]:
            self.assertFalse(search_apt(x,fs,[])['images'])

    def test_constant_envelopes_do_not_have_perfect_sync_correlation(self):
        for level in [0,1e-6,1,1000]:
            for template in [SYNC_A,SYNC_B]:
                self.assertFalse(_correlation(np.ones(8320)*level,template).any())

    def test_wide_baseband_fallback_and_missing_line_is_not_stitched(self):
        x,fs,_=fixture(fs=256000,bad_b_row=4)
        trial=search_apt(x,fs,[])
        self.assertEqual(trial['images'][0]['height'],4)
        self.assertEqual(trial['channels_examined'][0]['sync_runs'],2)
        lines=trial['images'][0]['lines']
        self.assertAlmostEqual(lines[-1]['time_end_seconds']-lines[0]['time_seconds'],2,delta=.001)

    def test_input_and_work_budgets(self):
        x,fs,_=fixture()
        self.assertFalse(search_apt(x,fs,[],max_channels=0)['images'])
        self.assertFalse(search_apt(x,fs,[],max_seconds=1)['images'])
        self.assertFalse(search_apt(x,fs,[],max_lines=2)['images'])
        self.assertEqual(search_apt(x,fs,[],max_lines=3)['images'][0]['height'],3)
        trial=search_apt(x,fs,[],max_seconds=3)
        self.assertTrue(trial['duration_limited'])
        for samples,rate in [(x.real,fs),(x,24000),(x,float('nan')),(np.array([complex('nan')]*fs*2),fs)]:
            self.assertEqual(search_apt(samples,rate,[])['status'],'not_applicable')

    def test_png_csv_binary_and_json_exports_agree_on_pixel_order(self):
        x,fs,_=fixture();trial=search_apt(x,fs,[])
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);write_apt_artifacts(trial,out);image=trial['images'][0];names=image['artifacts']
            pixels=png_pixels((out/names['full']).read_bytes())
            np.testing.assert_array_equal(png_pixels((out/names['A']).read_bytes()),pixels[:,86:995])
            np.testing.assert_array_equal(png_pixels((out/names['B']).read_bytes()),pixels[:,1126:2035])
            np.testing.assert_array_equal(np.loadtxt(out/names['csv'],delimiter=',',dtype='u1'),pixels)
            self.assertEqual((out/names['pixels']).read_bytes(),pixels.tobytes())
            self.assertEqual(json.loads((out/trial['artifact']).read_text()),trial)


if __name__=='__main__':unittest.main()

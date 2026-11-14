import unittest
import numpy as np

from iqscope_afsk_fm import search_afsk_fm
from test_afsk import fixture as audio_fixture


def fixture(fs=48000, offset=6500, baud=1200, bad=False, payload=b'>FM IQ reference'):
    audio, _ = audio_fixture(fs=fs, baud=baud, bad=bad, payload=payload)
    t = np.arange(len(audio))/fs
    iq = np.exp(2j*np.pi*(offset*t+3000*np.cumsum(audio)/fs))
    rng = np.random.default_rng(810)
    return iq+.003*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))


class AfskFmTests(unittest.TestCase):
    def test_fm_iq_recovers_crc_payload_and_rf_channel(self):
        for baud in (1200,1194.8):
            x = fixture(baud=baud)
            bands = [dict(offset_hz=6500,bandwidth_hz=14000,spectral_snr_db=30)]
            trial = search_afsk_fm(x,48000,bands,145000000)
            self.assertEqual(len(trial['frames']),4,trial)
            for frame in trial['frames']:
                self.assertEqual(frame['fields']['text'],'>FM IQ reference')
                self.assertTrue(frame['fcs_valid'])
                self.assertEqual(frame['frontend'],'fm_iq_afsk1200')
                self.assertAlmostEqual(frame['channel']['frequency_hz'],145006500,delta=100)
                self.assertTrue(frame['channel']['rf_center_known'])
                self.assertEqual(frame['demodulated_audio_channel'],{'audio_frequency_hz':1700})
                self.assertTrue(frame['fm_frontend']['filter_delay_compensated'])

    def test_baseband_fallback_and_unknown_rf_center(self):
        trial = search_afsk_fm(fixture(offset=0),48000,[])
        self.assertEqual(len(trial['frames']),4,trial)
        self.assertTrue(all(not f['channel']['rf_center_known'] for f in trial['frames']))

    def test_silent_prefix_keeps_source_time_and_clock_metadata(self):
        x=np.r_[np.zeros(24000,dtype=complex),fixture(offset=0,baud=1194.8)]
        trial=search_afsk_fm(x,48000,[])
        self.assertEqual(len(trial['frames']),4,trial)
        first=trial['frames'][0]
        self.assertAlmostEqual(first['time_seconds'],.5+80/1194.8,delta=2/1194.8)
        self.assertAlmostEqual(first['clock_baud'],1194.8,delta=.2)
        self.assertGreater(first['time_end_seconds'],first['time_seconds'])
        self.assertIn('demodulated_audio_start',first['timing_evidence']['time_reference'])

    def test_bad_crc_noise_carrier_and_real_audio_do_not_become_packets(self):
        rng = np.random.default_rng(811)
        for x in (fixture(offset=0,bad=True), np.ones(24000,dtype=complex),
                  rng.normal(size=24000)+1j*rng.normal(size=24000),np.ones(24000)):
            self.assertEqual(search_afsk_fm(x,48000,[])['frames'],[])

    def test_two_detected_wideband_channels_and_channel_limit(self):
        # Generate directly at 192 kS/s; interpolating IQ would add no RF bandwidth.
        from scipy import signal
        a,_ = audio_fixture(fs=48000,payload=b'>first')
        b,_ = audio_fixture(fs=48000,payload=b'>other')
        a,b = signal.resample_poly(a,4,1),signal.resample_poly(b,4,1)
        count=min(len(a),len(b));t=np.arange(count)/192000
        x=np.exp(2j*np.pi*(-35000*t+3000*np.cumsum(a[:count])/192000))
        x+=.8*np.exp(2j*np.pi*(35000*t+3000*np.cumsum(b[:count])/192000))
        bands=[dict(offset_hz=v,bandwidth_hz=14000,spectral_snr_db=30-i) for i,v in enumerate((-35000,35000))]
        result=search_afsk_fm(x,192000,bands)
        self.assertEqual({f['fields']['text'] for f in result['frames']},{'>first','>other'},result)
        limited=search_afsk_fm(x,192000,bands,max_channels=1)
        self.assertEqual({f['fields']['text'] for f in limited['frames']},{'>first'})
        self.assertEqual(limited['deferred_channel_count'],1)

    def test_budgets_and_no_invented_direct_wideband_channel(self):
        x=fixture(offset=0)
        result=search_afsk_fm(x,48000,[],max_frames=2,max_flag_pairs=20)
        self.assertLessEqual(len(result['frames']),2)
        self.assertLessEqual(result['flag_pairs_examined'],20)
        self.assertTrue(result['budget_exhausted'])
        self.assertEqual(search_afsk_fm(x,192000,[])['channels_examined'],[])
        self.assertEqual(search_afsk_fm(x,48000,[],max_seconds=0)['status'],'not_applicable')

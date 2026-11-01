import unittest
import numpy as np
from scipy import signal
from test_psk_rrc import fixture
from test_psk import equivalent
from iqscope_psk import decode_psk
from iqscope_psk_audio import search_audio_psk
from iqscope_ax25 import decode_psk_ax25


class PskTrackingTests(unittest.TestCase):
    def test_time_varying_carrier_symbols(self):
        for order in (2,):
            x,fs,expected,_=fixture(order)
            time=np.arange(len(x))/fs
            x*=np.exp(2j*np.pi*(12*time*time+1.2*np.sin(2*np.pi*.7*time)))
            report=decode_psk(x,fs)
            self.assertTrue(report['candidates'],report)
            c=report['candidates'][0]
            self.assertTrue(equivalent(c['symbols'],expected,order))
            self.assertIn('carrier_recovery',c['parameters'])
            self.assertLessEqual(c['evidence']['symbol_evm_rms'],.16)

    def test_automatic_audio_burst_without_rf_metadata(self):
        x,fs,expected,_=fixture(2,offset=1500)
        audio=np.r_[np.zeros(fs//2),x.real,np.zeros(fs//2)]
        audio=signal.resample_poly(audio,1,2)
        report=search_audio_psk(audio,fs/2)
        self.assertEqual(report['search_mode'],'energy_bursts')
        self.assertTrue(report['candidates'],report)
        c=report['candidates'][0]
        self.assertTrue(equivalent(c['symbols'],expected,2))
        self.assertIn('audio_frequency_hz',c['channel'])
        self.assertNotIn('frequency_hz',c['channel'])
        self.assertGreater(c['parameters']['first_symbol_center_seconds'],.5)

    def test_g3ruh_crc_valid_payload_and_corruption(self):
        from test_ax25 import frame,hdlc,candidate
        for bad in (False,True):
            packet=frame(bad=bad)
            source=hdlc(packet)
            state=0
            states=[]
            for bit in source:
                state^=int(bit=='0')
                states.append(state)
            # Independent feedback transmitter shift register, zero initial state.
            register=0
            scrambled=[]
            for bit in states:
                output=bit^((register>>11)&1)^((register>>16)&1)
                scrambled.append(str(output))
                register=((register<<1)|output)&0x1ffff
            c=candidate(''.join(scrambled));c['modulation']='BPSK'
            c['parameters']['first_symbol_center_seconds']=2
            report=decode_psk_ax25([c])
            if bad:
                self.assertFalse(report['frames'])
            else:
                self.assertEqual(len(report['frames']),1)
                f=report['frames'][0]
                self.assertEqual(f['hex'],packet.hex())
                self.assertEqual(f['frontend'],'bpsk_g3ruh')
                self.assertAlmostEqual(f['time_seconds'],2+f['bit_start']/1200)

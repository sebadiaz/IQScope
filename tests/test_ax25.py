import tempfile
import unittest
from pathlib import Path
import numpy as np
from iqscope_ax25 import crc_x25, decode_ax25, unstuff

TEXT = 'CQ IQSCOPE'


def frame(payload=TEXT.encode(),bad=False):
    # Literal AX.25 destination APRS-0 and source N0CALL-1, UI / no layer 3.
    body = bytes.fromhex('82a0a4a64040609c60868298986303f0')+payload
    packet = with_fcs(body)
    if bad:
        packet = packet[:17]+bytes([packet[17]^1])+packet[18:]
    return packet


def with_fcs(body):
    # Independent bit-by-bit MSB polynomial reference, with reflected octets.
    crc = 0xffff
    for octet in body:
        reflected = int(format(octet,'08b')[::-1],2)
        crc ^= reflected<<8
        for _ in range(8):
            crc = ((crc<<1)^0x1021)&0xffff if crc&0x8000 else (crc<<1)&0xffff
    fcs = int(format(crc,'016b')[::-1],2)^0xffff
    return body+fcs.to_bytes(2,'little')


def hdlc(packet):
    raw = ''.join(format(octet,'08b')[::-1] for octet in packet)
    out,ones = '',0
    for bit in raw:
        out += bit
        ones = ones+1 if bit=='1' else 0
        if ones==5:
            out += '0'
            ones = 0
    return '01111110'*10+out+'01111110'*10


def fixture(fs=24000,baud=1200,coding='nrzi',inverted=False,bad=False):
    bits = hdlc(frame(bad=bad))*4
    if coding=='nrzi':
        state = 0
        tone_bits = []
        for bit in bits:
            if bit=='0':
                state ^= 1
            tone_bits.append(state)
    else:
        tone_bits = list(map(int,bits))
    if inverted:
        tone_bits = [1-v for v in tone_bits]
    indices = np.floor((np.arange(int(len(tone_bits)*fs/baud))-2.3)*baud/fs).astype(int)
    keyed = np.array(tone_bits)[np.clip(indices,0,len(tone_bits)-1)]
    frequency = 210+(2*keyed-1)*2400
    x = np.exp(2j*np.pi*np.cumsum(frequency)/fs)
    rng = np.random.default_rng(92)
    x += .012*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,fs


def candidate(bits):
    return {'bits':bits,'parameters':{'baud':1200,'first_symbol_center_seconds':0}}


class Ax25Tests(unittest.TestCase):
    def test_crc_standard_check_value(self):
        self.assertEqual(crc_x25(b'123456789'),0x906e)

    def test_frame_stuffing_addresses_text_and_corruption(self):
        for payload in (TEXT.encode(),b'\xff'*30):
            bits = hdlc(frame(payload))
            result = decode_ax25([candidate(bits)])
            self.assertEqual(len(result['frames']),1,result)
            fields = result['frames'][0]['fields']
            self.assertEqual(fields['source']['callsign'],'N0CALL')
            self.assertEqual(fields['source']['ssid'],1)
            self.assertEqual(fields['destination']['callsign'],'APRS')
            self.assertEqual(fields['payload_hex'],payload.hex())
        self.assertEqual(decode_ax25([candidate(hdlc(frame(bad=True)))])['frames'],[])
        self.assertIsNone(unstuff('11111100'))

    def test_iq_to_crc_frames_nrzi_and_polarity(self):
        from iqscope import analyze_samples
        for inverted in (False,True):
            x,fs = fixture(inverted=inverted)
            with tempfile.TemporaryDirectory() as directory:
                report = analyze_samples(x,fs,0,directory)
                trial = next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')
                self.assertGreaterEqual(len(trial['frames']),3,trial)
                self.assertTrue(all(f['fields']['text']==TEXT for f in trial['frames']))
                self.assertTrue(all(f['line_coding']=='nrzi' for f in trial['frames']))

    def test_nrz_inversion_and_valid_crc_non_ui_rejection(self):
        bits = hdlc(frame())
        for inverted in (False,True):
            stream = bits.translate(str.maketrans('01','10')) if inverted else bits
            result = decode_ax25([candidate(stream)])
            self.assertEqual(len(result['frames']),1)
            self.assertEqual(result['frames'][0]['line_coding'],'nrz_inverted' if inverted else 'nrz')
        body = frame()[:-2]
        # Correct FCS is insufficient: non-UI control or malformed address.
        for malformed in (body[:14]+b'\x00'+body[15:],b'\x01'+body[1:]):
            result = decode_ax25([candidate(hdlc(with_fcs(malformed)))])
            self.assertEqual(result['frames'],[])

    def test_wideband_iq_channel_is_preserved(self):
        from iqscope import analyze_samples
        x,fs = fixture(fs=192000,baud=300)
        x *= np.exp(2j*np.pi*35000*np.arange(len(x))/fs)
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,7_000_000,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')
            self.assertGreaterEqual(len(trial['frames']),3,trial)
            self.assertAlmostEqual(trial['frames'][0]['channel']['frequency_hz'],7_035_210,delta=20)

    def test_corrupted_iq_frame_is_rejected_without_correction(self):
        from iqscope import analyze_samples
        x,fs = fixture(bad=True)
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,0,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')
            self.assertEqual(trial['frames'],[])
            self.assertGreaterEqual(trial['crc_rejected'],3)

    def test_budget_truncation_and_random_bits(self):
        bits = hdlc(frame())*5
        result = decode_ax25([candidate(bits)],max_frames=2)
        self.assertEqual(len(result['frames']),2)
        self.assertTrue(result['budget_exhausted'])
        self.assertEqual(decode_ax25([candidate(hdlc(frame())[:-100])])['frames'],[])
        rng = np.random.default_rng(38)
        self.assertEqual(decode_ax25([candidate(''.join(map(str,rng.integers(0,2,10000).tolist())))])['frames'],[])

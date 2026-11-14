"""Classic APRS101 T# samples, abstentions and CRC-gated receiver paths."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from iqscope_aprs import parse_aprs_telemetry
from iqscope_ax25 import decode_ax25, decode_psk_ax25
from test_ax25 import frame, hdlc, candidate, with_fcs

SAMPLE = b'T#005,199,000,255,073,123,01101001'
PAYLOAD = SAMPLE+b' <b>telemetry</b>'
MIC = b'T#MIC199,000,255,073,123,01101001'
INVALID = b'T#005,256,000,255,073,123,01101001'


class AprsTelemetryTests(unittest.TestCase):
    def test_published_sample_raw_values_and_bit_order(self):
        value=parse_aprs_telemetry(SAMPLE)
        self.assertEqual(value['status'],'decoded_telemetry')
        self.assertEqual(value['data_type_identifier'],'T')
        t=value['telemetry']
        self.assertEqual(t['sequence'],dict(raw='005',kind='counter',value=5))
        self.assertEqual(t['analog_raw'],[199,0,255,73,123])
        self.assertEqual(t['digital_raw'],'01101001')
        self.assertEqual(t['digital_bits'],[0,1,1,0,1,0,0,1])
        self.assertNotIn('latitude_deg',value)
        self.assertNotIn('physical_values',t)

    def test_published_mic_form_with_and_without_comma_has_no_invented_counter(self):
        for payload in (MIC,MIC.replace(b'MIC',b'MIC,',1)):
            value=parse_aprs_telemetry(payload)['telemetry']
            self.assertEqual(value['sequence'],dict(raw='MIC',kind='MIC'))
            self.assertEqual(value['analog_raw'],[199,0,255,73,123])
            self.assertNotIn('value',value['sequence'])

    def test_zero_maximum_and_sequence_boundaries_are_values(self):
        for sequence in (b'000',b'999'):
            for analog in (b'000',b'255'):
                for digital in (b'00000000',b'11111111'):
                    t=parse_aprs_telemetry(b'T#'+sequence+b','+(analog+b',')*5+digital)['telemetry']
                    self.assertEqual(t['sequence']['value'],int(sequence))
                    self.assertEqual(t['analog_raw'],[int(analog)]*5)
                    self.assertEqual(t['digital_bits'],list(map(int,digital.decode())))

    def test_invalid_analog_range_never_yields_partial_or_clamped_values(self):
        for channel in range(5):
            for token in (b'256',b'999'):
                values=[b'001']*5;values[channel]=token
                report=parse_aprs_telemetry(b'T#001,'+b','.join(values)+b',00000000')
                self.assertEqual(report['status'],'invalid_telemetry_analog_range')
                self.assertNotIn('telemetry',report)

    def test_truncation_and_missing_channels_never_become_zeroes(self):
        for end in range(2,len(SAMPLE)):
            self.assertNotIn('telemetry',parse_aprs_telemetry(SAMPLE[:end]))
        for payload in (b'T#005,199,,255,073,123,01101001',b'T#005,199,000,255,073,01101001',
                        b'T#005,199,000,255,073,123,042,01101001'):
            self.assertNotIn('telemetry',parse_aprs_telemetry(payload))

    def test_extended_signed_float_and_wrong_width_formats_stay_uninterpreted(self):
        for token in (b'-01',b'1.5',b'1',b'01',b'+01',b'NaN',b'Inf',b'  1'):
            value=parse_aprs_telemetry(SAMPLE.replace(b'199',token,1))
            self.assertNotIn('telemetry',value)
        for sequence in (b'05',b'0005',b'abc',b'mic',b'005 '):
            value=parse_aprs_telemetry(SAMPLE.replace(b'005',sequence,1))
            self.assertNotIn('telemetry',value)

    def test_digital_bytes_are_exactly_eight_wire_bits(self):
        for bits in (b'0110100',b'01102001',b'0110?001',b'0110\xff01'):
            value=parse_aprs_telemetry(SAMPLE[:-8]+bits)
            self.assertNotIn('telemetry',value)
        # The classic fixed-width field is followed by an arbitrary comment,
        # which may itself begin with a digit; it is not a ninth input bit.
        value=parse_aprs_telemetry(SAMPLE+b'1 trailing comment')['telemetry']
        self.assertEqual(len(value['digital_bits']),8)
        self.assertEqual(value['comment'],'1 trailing comment')

    def test_comment_octets_and_html_like_text_are_preserved(self):
        tail=b' <b>telemetry</b> \xc2\xb0C \xff\x00'
        value=parse_aprs_telemetry(SAMPLE+tail)['telemetry']
        self.assertEqual(value['comment_hex'],tail.hex())
        self.assertEqual(value['comment'],tail.decode('utf-8',errors='replace'))
        self.assertEqual(parse_aprs_telemetry(bytearray(SAMPLE))['status'],'decoded_telemetry')

    def test_prefix_type_and_payload_budget_are_bounded(self):
        for payload in (None,'T#005',b'',b'Test',b't#005',b'CQ '+SAMPLE,b'!'+SAMPLE,b':N0CALL   :'+SAMPLE):
            self.assertIsNone(parse_aprs_telemetry(payload))
        self.assertEqual(parse_aprs_telemetry(SAMPLE+b'x'*(256-len(SAMPLE)))['status'],'decoded_telemetry')
        self.assertIsNone(parse_aprs_telemetry(SAMPLE+b'x'*(257-len(SAMPLE))))

    def test_definition_messages_keep_raw_values_and_cannot_rewrite_previous_samples(self):
        definitions=[b':N0CALL-1 :PARM.Battery,Temp',b':N0CALL-1 :UNIT.v/100,deg.F',
                     b':N0CALL-1 :EQNS.0,5.2,0,0,.53,-32',b':N0CALL-1 :BITS.10110000,Project']
        source=[candidate(''.join(hdlc(frame(payload=p)) for p in [SAMPLE,*definitions,SAMPLE]))]
        frames=decode_ax25(source)['frames']
        self.assertEqual(len(frames),6)
        before=frames[0]['fields']['aprs']['telemetry']
        self.assertNotIn('analog_channels',before)
        for decoded in frames[1:-1]:self.assertEqual(decoded['fields']['aprs']['status'],'decoded_telemetry_definition')
        raw=frames[-1]['fields']['aprs']['telemetry']
        self.assertEqual(raw['analog_raw'][0],199)
        self.assertEqual(raw['analog_raw'],before['analog_raw'])
        self.assertAlmostEqual(raw['analog_channels'][0]['value'],1034.8)
        for key in ('units','names','coefficients','physical_values','digital_active'):
            self.assertNotIn(key,raw)

    def test_crc_pid_raw_payload_and_inputs_are_preserved(self):
        source=[candidate(hdlc(frame(payload=PAYLOAD)))];untouched=deepcopy(source)
        decoded=decode_ax25(source)['frames']
        self.assertEqual(source,untouched)
        self.assertEqual(len(decoded),1)
        fields=decoded[0]['fields']
        self.assertEqual(fields['payload_hex'],PAYLOAD.hex())
        self.assertEqual(fields['text'],PAYLOAD.decode())
        self.assertEqual(fields['aprs']['status'],'decoded_telemetry')
        self.assertEqual(decode_ax25([candidate(hdlc(frame(payload=PAYLOAD,bad=True)))])['frames'],[])
        body=bytearray(frame(payload=PAYLOAD)[:-2]);body[15]=0xCF
        other=decode_ax25([candidate(hdlc(with_fcs(bytes(body))))])['frames'][0]['fields']
        self.assertNotIn('aprs',other)
        json.dumps(decoded,allow_nan=False)

    def test_invalid_telemetry_does_not_discard_a_valid_ax25_frame(self):
        decoded=decode_ax25([candidate(hdlc(frame(payload=INVALID)))])['frames']
        self.assertEqual(len(decoded),1)
        self.assertTrue(decoded[0]['fcs_valid'])
        self.assertEqual(decoded[0]['fields']['payload_hex'],INVALID.hex())
        self.assertNotIn('telemetry',decoded[0]['fields']['aprs'])

    def test_bpsk_descrambling_uses_the_same_telemetry_reader(self):
        state=register=0;bits=[]
        for bit in hdlc(frame(payload=PAYLOAD)):
            state ^= int(bit=='0')
            output=state^((register>>11)&1)^((register>>16)&1)
            bits.append(str(output));register=((register<<1)|output)&0x1ffff
        source=candidate(''.join(bits));source['modulation']='BPSK'
        frames=decode_psk_ax25([source])['frames']
        self.assertEqual(len(frames),1)
        self.assertEqual(frames[0]['fields']['aprs']['telemetry']['analog_raw'],[199,0,255,73,123])

    def test_actual_iq_and_audio_paths_recover_values_and_keep_crc_counts(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        from test_ax25 import fixture as iq_fixture
        from test_afsk import fixture as audio_fixture
        iq,fs=iq_fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(iq,fs,0,directory)
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
            self.assertGreaterEqual(len(frames),3)
            self.assertTrue(all(f['fields']['aprs']['telemetry']['sequence']['value']==5 for f in frames))
        for payload in (MIC,INVALID):
            audio,fs=audio_fixture(payload=payload)
            frames=decode_afsk1200(audio,fs)['frames']
            self.assertEqual(len(frames),4)
            self.assertTrue(all(f['fields']['payload_hex']==payload.hex() for f in frames))

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_and_json_preserve_raw_values_without_rf_center(self):
        from test_afsk import fixture
        from iqscope_audio import analyze_audio
        audio,fs=fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wave=root/'telemetry.wav';wavfile.write(wave,fs,audio.astype(np.float32))
            report=analyze_audio(wave,root/'out')
            self.assertIsNone(report['center_frequency_hz'])
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_ax25')['frames']
            self.assertEqual(len(frames),4)
            self.assertEqual(json.loads((root/'out'/report['frame_artifact']).read_text())['frames'],frames)
            self.assertTrue(all(f['fields']['aprs']['telemetry']['digital_raw']=='01101001' for f in frames))


if __name__=='__main__':
    unittest.main()

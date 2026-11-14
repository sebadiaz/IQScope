"""Primary base-91 comment examples, bit order and receiver integration."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from iqscope_aprs import parse_aprs_comment_telemetry as parse_comment, parse_aprs_position, parse_aprs_telemetry
from iqscope_aprs_calibration import enrich_aprs_telemetry_frames as enrich
from iqscope_ax25 import decode_ax25, decode_psk_ax25
from test_ax25 import frame, hdlc, candidate, with_fcs
from test_aprs import POSITION
from test_aprs_calibration import DEFINITIONS, receiver_fixture, stream_bits, report

BLOCK=b'|ss1122334455!"|'
PAYLOAD=b'!'+POSITION+b' <b>base91</b> '+BLOCK
MINIMAL=b'!'+POSITION+b' zero |!!!!|'
INVALID=b'!'+POSITION+b' broken |!!!|'


def pair(value):
    quotient,remainder=divmod(value,91)
    return bytes((quotient+33,remainder+33))


class CommentTelemetryTests(unittest.TestCase):
    def test_published_pair_examples_and_minimum(self):
        for block,values in ((b'|ss11|',[1472]),(b'|ss112233|',[1472,1564,1656]),(BLOCK,[1472,1564,1656,1748,1840])):
            value=parse_comment(block)
            self.assertEqual(value['status'],'decoded_comment_telemetry')
            self.assertEqual(value['telemetry']['sequence']['value'],7544)
            self.assertEqual(value['telemetry']['analog_raw'],values)
        zero=parse_comment(b'|!!!!|')['telemetry']
        self.assertEqual(zero['sequence']['value'],0)
        self.assertEqual(zero['analog_raw'],[0])

    def test_published_complete_uncompressed_and_compressed_packets(self):
        payloads=(b'!/0%3RTh<6>dS_http://aprs.fi/|"p%T\'.ag|',
                  b'!6304.03NN02739.63E#PHG26303/Siilinjarvi|"p%T\'.agff|')
        for payload,count in zip(payloads,(3,4)):
            value=parse_aprs_position(payload)
            self.assertEqual(value['status'],'decoded_position')
            self.assertEqual(value['telemetry']['sequence']['value'],170)
            self.assertEqual(value['telemetry']['analog_raw'][:3],[415,559,5894])
            self.assertEqual(len(value['telemetry']['analog_raw']),count)
            plain=parse_aprs_position(payload[:payload.index(b'|')])
            self.assertEqual((value['latitude_deg'],value['longitude_deg']),(plain['latitude_deg'],plain['longitude_deg']))

    def test_one_through_five_channels_and_maximum_are_not_padded(self):
        for count in range(1,6):
            t=parse_comment(b'|'+pair(8280)+pair(8280)*count+b'|')['telemetry']
            self.assertEqual(t['sequence']['value'],8280)
            self.assertEqual(t['analog_raw'],[8280]*count)
            self.assertEqual(t['digital_status'],'not_transmitted')
            self.assertNotIn('digital_raw',t)
            self.assertNotIn('digital_bits',t)

    def test_binary_lsb_is_b1_and_is_distinct_from_classic_wire_order(self):
        t=parse_comment(BLOCK)['telemetry']
        self.assertEqual(t['digital_word_raw'],1)
        self.assertEqual(t['digital_raw'],'10000000')
        self.assertEqual(t['digital_bits'],[1,0,0,0,0,0,0,0])
        classic=parse_aprs_telemetry(b'T#001,000,000,000,000,000,00000001')['telemetry']
        self.assertEqual(classic['digital_bits'],[0,0,0,0,0,0,0,1])

    def test_reserved_word_bits_are_retained_without_extra_inputs(self):
        for word in (0,255,256,8191,8280):
            t=parse_comment(b'|'+pair(0)*6+pair(word)+b'|')['telemetry']
            self.assertEqual(t['digital_word_raw'],word)
            self.assertEqual(t['digital_reserved_value'],word>>8)
            self.assertEqual(len(t['digital_bits']),8)
            self.assertEqual(sum(bit<<i for i,bit in enumerate(t['digital_bits'])),word&255)

    def test_comment_octets_byte_offsets_and_unapplied_dao_suffix(self):
        before=b'\xc2\xb0C <b>example</b> '
        comment=before+b'|!!!!|!w12!'
        t=parse_comment(comment)['telemetry']
        self.assertEqual(t['comment_hex'],comment.hex())
        self.assertEqual(t['comment'],comment.decode())
        self.assertEqual(t['extension_span']['start'],len(before))
        self.assertEqual(t['extension_span']['end'],len(before)+6)
        value=parse_aprs_position(b'!'+POSITION+comment)
        plain=parse_aprs_position(b'!'+POSITION)
        self.assertEqual(value['latitude_deg'],plain['latitude_deg'])
        self.assertEqual(value['encoded_resolution_minutes'],.01)
        self.assertIn('not applied',value['telemetry']['trailing_extension_status'])

    def test_dao_looking_bytes_inside_telemetry_do_not_change_position(self):
        value=parse_aprs_position(b'!'+POSITION+b'|!W12!q|')
        self.assertEqual(value['telemetry']['sequence']['value'],54)
        self.assertEqual(value['telemetry']['analog_raw'],[1473,80])
        self.assertNotIn('trailing_extension_status',value['telemetry'])
        self.assertEqual(value['latitude_deg'],parse_aprs_position(b'!'+POSITION)['latitude_deg'])

    def test_bad_lengths_bytes_and_ambiguous_delimiters_have_no_partial_values(self):
        for block in (b'||',b'|!!|',b'|!!!|',b'|'+b'!'*15+b'|',b'|'+b'!'*16+b'|',
                      b'|!! !|',b'|!!\x00!|',b'|!!}!|',b'|!!\xff!|',b'|!!!!',b'|!!!!||!!!!|',b'||!!!!|'):
            parsed=parse_comment(block)
            self.assertNotIn('telemetry',parsed,block)
            value=parse_aprs_position(b'!'+POSITION+block)
            self.assertEqual(value['status'],'decoded_position')
            self.assertNotIn('telemetry',value)

    def test_unrecognized_suffix_is_preserved_and_never_selects_a_block(self):
        for suffix in (b'comment after',b'!Waa!',b'!w12!!W34!',b'|3',b'\xff'):
            comment=b'|!!!!|'+suffix
            self.assertNotIn('telemetry',parse_comment(comment))
            result=parse_aprs_position(b'!'+POSITION+comment)
            self.assertEqual(result['comment_and_extensions_hex'],comment.hex())
        self.assertEqual(parse_comment(b'|!!!!|!W12!')['status'],'decoded_comment_telemetry')

    def test_null_and_ambiguous_positions_may_carry_independent_telemetry(self):
        for core,status in ((b'4903.5 N/07201.75W>','ambiguous_position'),(b'0000.00N\\00000.00W.','null_position')):
            result=parse_aprs_position(b'!'+core+b'|!!!!|')
            self.assertEqual(result['status'],status)
            self.assertNotIn('latitude_deg',result)
            self.assertEqual(result['telemetry']['analog_raw'],[0])
        for payload in (b'!9100.00N/07201.75W>|!!!!|',b'@092445z'+POSITION+b'|!!!!|',
                        b';LEADER   *092345z'+POSITION+BLOCK,b')AID!'+POSITION+BLOCK):
            self.assertNotIn('telemetry',parse_aprs_position(payload))
        self.assertIsNone(parse_aprs_position(b'`mic-e'+BLOCK))

    def test_encoded_altitude_looking_bytes_are_opaque_and_no_annotation_is_fabricated(self):
        block=b'|!!/A=001234!!!|'
        value=parse_aprs_position(b'!'+POSITION+block)
        self.assertIn('telemetry',value)
        self.assertNotIn('altitude_ft',value)
        value=parse_aprs_position(b'!'+POSITION+b'/A=000123 '+block)
        self.assertEqual(value['altitude_ft'],123)
        compressed=parse_aprs_position(b'=/5L!!<*e7OS]S'+block)
        self.assertAlmostEqual(compressed['altitude_ft'],10004,delta=1)
        self.assertNotIn('altitude_candidates',compressed)
        self.assertNotIn('altitude_ft',parse_aprs_position(b'!'+POSITION+b'/A=|!!!!|001234'))

    def test_crc_pid_gate_raw_payload_and_candidate_immutability(self):
        source=[candidate(hdlc(frame(payload=PAYLOAD)))];before=deepcopy(source)
        result=decode_ax25(source)['frames']
        self.assertEqual(source,before)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['fields']['payload_hex'],PAYLOAD.hex())
        self.assertEqual(result[0]['fields']['aprs']['status'],'decoded_position')
        self.assertIn('telemetry',result[0]['fields']['aprs'])
        self.assertEqual(decode_ax25([candidate(hdlc(frame(payload=PAYLOAD,bad=True)))])['frames'],[])
        body=bytearray(frame(payload=PAYLOAD)[:-2]);body[15]=0xCF
        other=decode_ax25([candidate(hdlc(with_fcs(bytes(body))))])['frames'][0]['fields']
        self.assertNotIn('aprs',other)

    def test_partial_analog_calibration_does_not_invent_missing_channels(self):
        payload=b'!'+POSITION+b'|ss112233|'
        frames=decode_ax25([candidate(stream_bits([*DEFINITIONS,payload]))])['frames']
        t=frames[-1]['fields']['aprs']['telemetry']
        self.assertEqual(len(t['analog_channels']),3)
        self.assertEqual(t['digital_channels'],[])
        self.assertNotIn('digital_bits',t)
        self.assertAlmostEqual(t['analog_channels'][0]['value'],7654.4)
        self.assertEqual(t['analog_channels'][0]['unit'],'v/100')

    def test_declared_binary_sense_uses_the_correct_b1_and_reparse_is_idempotent(self):
        frames=decode_ax25([candidate(stream_bits([*DEFINITIONS,PAYLOAD]))])['frames']
        t=frames[-1]['fields']['aprs']['telemetry']
        self.assertTrue(t['digital_channels'][0]['matches_declared_sense'])
        self.assertEqual(t['digital_channels'][0]['label'],'Click')
        self.assertEqual(frames,enrich(frames))
        stale=report(b'!'+POSITION,10)
        stale['fields']['aprs']=deepcopy(frames[-1]['fields']['aprs'])
        self.assertNotIn('telemetry',enrich([stale])[0]['fields']['aprs'])

    def test_iq_and_audio_receiver_paths_keep_one_packet_for_two_content_types(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        for kind in ('audio','iq'):
            values,fs=receiver_fixture(kind,payloads=[PAYLOAD]*4)
            if kind=='audio':
                frames=decode_afsk1200(values,fs)['frames']
                self.assertEqual(len(frames),4)
            else:
                with tempfile.TemporaryDirectory() as directory:
                    result=analyze_samples(values,fs,0,directory)
                    frames=next(t for t in result['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
                    self.assertGreaterEqual(len(frames),3)
            self.assertTrue(all(f['fields']['aprs']['telemetry']['digital_raw']=='10000000' for f in frames))

    def test_bpsk_shared_parser_preserves_position_and_calibration(self):
        state=register=0;bits=[]
        for bit in stream_bits([*DEFINITIONS,PAYLOAD]):
            state ^= int(bit=='0');output=state^((register>>11)&1)^((register>>16)&1)
            bits.append(str(output));register=((register<<1)|output)&0x1ffff
        c=candidate(''.join(bits));c['modulation']='BPSK'
        frames=decode_psk_ax25([c])['frames']
        self.assertEqual(len(frames),5)
        value=frames[-1]['fields']['aprs']
        self.assertEqual(value['status'],'decoded_position')
        self.assertAlmostEqual(value['telemetry']['analog_channels'][0]['value'],7654.4)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_json_round_trip_and_unknown_rf_center(self):
        from iqscope_audio import analyze_audio
        values,fs=receiver_fixture(payloads=[PAYLOAD]*4)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wave=root/'base91.wav';wavfile.write(wave,fs,values.astype(np.float32))
            result=analyze_audio(wave,root/'out')
            self.assertIsNone(result['center_frequency_hz'])
            frames=next(t for t in result['wideband_trials'] if t['decoder']=='afsk1200_ax25')['frames']
            self.assertEqual(len(frames),4)
            self.assertEqual(json.loads((root/'out'/result['frame_artifact']).read_text())['frames'],frames)
            self.assertTrue(all(f['fields']['aprs']['telemetry']['extension_hex']==BLOCK.hex() for f in frames))

    def test_types_budget_and_exact_comment_preservation(self):
        for value in (None,'|!!!!|',b'',b'ordinary comment'):
            self.assertIsNone(parse_comment(value))
        self.assertIsNone(parse_comment(b'x'*251+b'|!!!!|'))
        self.assertEqual(parse_comment(bytearray(b'|!!!!|'))['telemetry']['analog_raw'],[0])
        self.assertEqual(parse_comment(b'x'*250+b'|!!!!|')['status'],'decoded_comment_telemetry')


if __name__=='__main__':
    unittest.main()

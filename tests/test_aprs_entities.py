"""APRS101 object/item syntax and conservative withdrawal reporting."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from iqscope_aprs import parse_aprs_position
from iqscope_ax25 import decode_ax25, decode_psk_ax25
from test_ax25 import frame, hdlc, candidate, with_fcs
from test_aprs import POSITION
from test_aprs_compressed import COMPRESSED

OBJECT = b';LEADER   *092345z'+POSITION+b'088/036'
OBJECT_UI = b';<b>TEST  *092345z'+COMPRESSED+b' <i>entity</i>'
ITEM = b')AID #2!'+POSITION[:-1]+b'A first aid'
RETRACTED = OBJECT_UI.replace(b'*092345z',b'_092345z',1)


class AprsEntityTests(unittest.TestCase):
    def test_published_live_object_and_partial_timestamp(self):
        value=parse_aprs_position(OBJECT)
        self.assertEqual(value['status'],'decoded_position')
        self.assertEqual(value['data_type_identifier'],';')
        self.assertEqual(value['position_subject'],'named_entity')
        self.assertEqual(value['requested_profile'],'object_position')
        self.assertEqual(value['entity'],dict(kind='object',name='LEADER   ',name_hex=b'LEADER   '.hex(),marker='*',state_reported='live'))
        self.assertAlmostEqual(value['latitude_deg'],49+3.5/60)
        self.assertEqual((value['course_deg'],value['speed_knots']),(88,36))
        self.assertEqual(value['timestamp']['day'],9)
        self.assertNotIn('month',value['timestamp'])
        self.assertNotIn('messaging_capability_reported',value)

    def test_published_compressed_object_keeps_entity_identity(self):
        value=parse_aprs_position(b';LEADER   *092345z'+COMPRESSED)
        self.assertEqual(value['format'],'compressed')
        self.assertEqual(value['requested_profile'],'object_position')
        self.assertEqual(value['latitude_deg'],49.5)
        self.assertAlmostEqual(value['longitude_deg'],-72.75,delta=1/190463)
        self.assertEqual(value['entity_position_hex'],COMPRESSED.hex())
        self.assertNotIn('messaging_capability_reported',value)

    def test_published_item_uncompressed_and_compressed(self):
        value=parse_aprs_position(ITEM)
        self.assertEqual(value['entity']['name'],'AID #2')
        self.assertEqual(value['entity']['kind'],'item')
        self.assertEqual(value['data_type_identifier'],')')
        self.assertEqual(value['symbol_code'],'A')
        self.assertEqual(value['timestamp'],dict(status='not_transmitted'))
        self.assertNotIn('messaging_capability_reported',value)
        compressed=parse_aprs_position(b')MOBIL!\\5L!!<*e79 sT')
        self.assertEqual(compressed['format'],'compressed')
        self.assertEqual(compressed['entity']['name'],'MOBIL')
        self.assertEqual(compressed['latitude_deg'],49.5)
        self.assertNotIn('speed_knots',compressed)

    def test_names_keep_case_padding_and_fixed_object_delimiters(self):
        for name in (b' Leader  ',b'LEADER   ',b'A*B_C!DEF',b'         '):
            value=parse_aprs_position(b';'+name+b'*092345z'+POSITION)
            self.assertEqual(value['entity']['name'],name.decode())
            self.assertEqual(value['status'],'decoded_position')
        for name in (b'ABC',b'Abc',b'123456789',b' GATE '):
            value=parse_aprs_position(b')'+name+b'!'+POSITION)
            self.assertEqual(value['entity']['name'],name.decode())
            self.assertEqual(value['status'],'decoded_position')

    def test_invalid_header_lengths_names_and_markers_do_not_make_positions(self):
        for payload in (b';',b';SHORT*092345z'+POSITION,b';TOO-LONG-X*092345z'+POSITION,
                        b';LEADER   !092345z'+POSITION,b';BAD\x00NAME *092345z'+POSITION,
                        b';BAD\xffNAME *092345z'+POSITION,b')',b')AB!'+POSITION,
                        b')ABCDEFGHIJ!'+POSITION,b')A!BC!'+POSITION,b')AB_CD!'+POSITION,
                        b')BAD\x00!'+POSITION,b')BAD\xff!'+POSITION):
            value=parse_aprs_position(payload)
            self.assertNotIn('latitude_deg',value,payload)
            self.assertNotIn('longitude_deg',value,payload)
        self.assertIsNone(parse_aprs_position(OBJECT+b'x'*256))

    def test_objects_require_valid_timestamp_items_do_not_guess_one(self):
        for timestamp in (b'002345z',b'092445z',b'092345X',b'xxxxxxx'):
            value=parse_aprs_position(b';LEADER   *'+timestamp+POSITION)
            self.assertEqual(value['status'],'invalid_timestamp')
            self.assertNotIn('latitude_deg',value)
        self.assertNotIn('latitude_deg',parse_aprs_position(b';LEADER   *'+POSITION))
        self.assertNotIn('latitude_deg',parse_aprs_position(b')AID!092345z'+POSITION))
        for stamp in (b'092345/',b'234517h'):
            self.assertEqual(parse_aprs_position(b';LEADER   *'+stamp+POSITION)['status'],'decoded_position')

    def test_killed_entities_never_expose_an_active_position_or_motion(self):
        for payload in (OBJECT.replace(b'*',b'_',1),RETRACTED,ITEM.replace(b'!',b'_',1),
                        b')MOBIL_\\5L!!<*e79 sT'):
            value=parse_aprs_position(payload)
            self.assertEqual(value['status'],'retracted_entity')
            self.assertEqual(value['entity']['state_reported'],'killed')
            self.assertEqual(value['reported_position_status'],'decoded_position')
            for key in ('latitude_deg','longitude_deg','course_deg','speed_knots','altitude_ft','compression_type'):
                self.assertNotIn(key,value)
            self.assertTrue(value['entity_position_hex'])

    def test_bad_withdrawal_body_or_timestamp_is_reported_unresolved(self):
        for payload in (b';LEADER   _092345z',b';LEADER   _092445z'+POSITION,
                        b')AID_',b')AID_9100.00N/07201.75W>'):
            value=parse_aprs_position(payload)
            self.assertEqual(value['status'],'unresolved_entity_retraction')
            self.assertNotIn('latitude_deg',value)

    def test_ambiguity_and_null_positions_stay_unresolved_on_entities(self):
        for body,status in ((b'4903.5 N/07201.75W>','ambiguous_position'),
                            (b'0000.00N\\00000.00W.','null_position')):
            for prefix in (b';LEADER   *092345z',b')AID!'):
                value=parse_aprs_position(prefix+body)
                self.assertEqual(value['status'],status)
                self.assertNotIn('latitude_deg',value)
                self.assertNotIn('longitude_deg',value)
            self.assertEqual(parse_aprs_position(b')AID_'+body)['status'],'retracted_entity')

    def test_area_entities_are_not_presented_as_points_or_vehicle_motion(self):
        for body in (b'4903.50N\\07201.75Wl710/310',b'A5L!!<*e7l7P['):
            for prefix in (b';SEARCH   *092345z',b')AREA!'):
                value=parse_aprs_position(prefix+body)
                self.assertEqual(value['status'],'unsupported_area_entity')
                self.assertNotIn('latitude_deg',value)
                self.assertNotIn('speed_knots',value)
        # Primary-table l is a different symbol, not alternate-table area l.
        self.assertEqual(parse_aprs_position(b')POINT!'+POSITION[:-1]+b'l')['status'],'decoded_position')

    def test_reports_with_same_name_and_different_senders_do_not_mutate_each_other(self):
        live=frame(payload=OBJECT);dead=bytearray(frame(payload=OBJECT.replace(b'*',b'_',1))[:-2])
        dead[7:13]=bytes(ord(c)<<1 for c in 'SECOND')
        inputs=[candidate(hdlc(live)+hdlc(with_fcs(bytes(dead)))+hdlc(live))]
        untouched=deepcopy(inputs)
        frames=decode_ax25(inputs)['frames']
        self.assertEqual(inputs,untouched)
        self.assertEqual(len(frames),3)
        self.assertEqual([f['fields']['source']['callsign'] for f in frames],['N0CALL','SECOND','N0CALL'])
        self.assertEqual([f['fields']['aprs']['status'] for f in frames],['decoded_position','retracted_entity','decoded_position'])
        self.assertEqual(frames[0]['fields']['aprs'],frames[2]['fields']['aprs'])

    def test_crc_pid_and_original_raw_payload_gate_interpretation(self):
        value=decode_ax25([candidate(hdlc(frame(payload=OBJECT_UI)))])['frames'][0]['fields']
        self.assertEqual(value['payload_hex'],OBJECT_UI.hex())
        self.assertEqual(value['text'],OBJECT_UI.decode())
        self.assertEqual(value['aprs']['entity']['name'],'<b>TEST  ')
        self.assertEqual(decode_ax25([candidate(hdlc(frame(payload=OBJECT,bad=True)))])['frames'],[])
        body=bytearray(frame(payload=OBJECT)[:-2]);body[15]=0xCF
        other=decode_ax25([candidate(hdlc(with_fcs(bytes(body))))])['frames'][0]['fields']
        self.assertNotIn('aprs',other)
        json.dumps(value,allow_nan=False)

    def test_iq_and_audio_receiver_paths_and_unchanged_crc_counts(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        from test_ax25 import fixture as iq_fixture
        from test_afsk import fixture as audio_fixture
        iq,fs=iq_fixture(payload=OBJECT_UI)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(iq,fs,0,directory)
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
            self.assertGreaterEqual(len(frames),3)
            self.assertTrue(all(f['fields']['aprs']['entity']['kind']=='object' for f in frames))
        for payload in (ITEM,RETRACTED):
            audio,fs=audio_fixture(payload=payload)
            frames=decode_afsk1200(audio,fs)['frames']
            self.assertEqual(len(frames),4)
            self.assertTrue(all(f['fields']['payload_hex']==payload.hex() for f in frames))

    def test_bpsk_descrambling_keeps_entity_as_payload_subject(self):
        state=register=0;bits=[]
        for bit in hdlc(frame(payload=OBJECT_UI)):
            state ^= int(bit=='0')
            output=state^((register>>11)&1)^((register>>16)&1)
            bits.append(str(output));register=((register<<1)|output)&0x1ffff
        source=candidate(''.join(bits));source['modulation']='BPSK'
        frames=decode_psk_ax25([source])['frames']
        self.assertEqual(len(frames),1)
        self.assertEqual(frames[0]['fields']['source']['callsign'],'N0CALL')
        self.assertEqual(frames[0]['fields']['aprs']['entity']['name'],'<b>TEST  ')
        self.assertEqual(frames[0]['fields']['aprs']['position_subject'],'named_entity')

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_json_export_preserves_active_and_retracted_entities(self):
        from test_afsk import fixture
        from iqscope_audio import analyze_audio
        for payload in (OBJECT_UI,RETRACTED):
            audio,fs=fixture(payload=payload)
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);wave=root/'entity.wav';wavfile.write(wave,fs,audio.astype(np.float32))
                report=analyze_audio(wave,root/'out')
                self.assertIsNone(report['center_frequency_hz'])
                frames=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_ax25')['frames']
                self.assertEqual(len(frames),4)
                self.assertEqual(json.loads((root/'out'/report['frame_artifact']).read_text())['frames'],frames)


if __name__=='__main__':
    unittest.main()

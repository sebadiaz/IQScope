"""Published APRS position examples, negative cases and actual receiver paths."""
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

POSITION = b'4903.50N/07201.75W>'
PAYLOAD = b'@092345z'+POSITION+b'088/036/A=001234 <b>test</b>'


class AprsTests(unittest.TestCase):
    def test_published_coordinates_and_four_data_type_identifiers(self):
        for dti in b'!=/@':
            prefix = bytes([dti])+(b'092345z' if dti in b'/@' else b'')
            value = parse_aprs_position(prefix+POSITION+b'Test1234')
            self.assertEqual(value['status'], 'decoded_position')
            self.assertAlmostEqual(value['latitude_deg'], 49+3.5/60)
            self.assertAlmostEqual(value['longitude_deg'], -72-1.75/60)
            self.assertEqual(value['messaging_capability_reported'], dti in b'=@')
            self.assertEqual(value['symbol_table'], '/')
            self.assertEqual(value['symbol_code'], '>')

    def test_timestamp_components_without_inventing_calendar_dates(self):
        for raw, basis, kind in ((b'092345z', 'UTC', 'day_hour_minute'),
                                 (b'092345/', 'local_timezone_unspecified', 'day_hour_minute'),
                                 (b'234517h', 'UTC', 'hour_minute_second')):
            stamp = parse_aprs_position(b'@'+raw+POSITION)['timestamp']
            self.assertEqual(stamp['time_basis'], basis)
            self.assertEqual(stamp['format'], kind)
            self.assertEqual((stamp['hour'], stamp['minute']), (23,45))
            self.assertNotIn('year', stamp); self.assertNotIn('month', stamp)
            self.assertNotIn('unix_time', stamp)
        for raw in (b'002345z', b'322345z', b'092445z', b'092360z', b'246000h', b'234560h', b'092345Z', b'short'):
            value = parse_aprs_position(b'@'+raw+POSITION)
            self.assertEqual(value['status'], 'invalid_timestamp')
            self.assertNotIn('latitude_deg', value)

    def test_hemispheres_boundaries_and_zero_are_values(self):
        for lat, lon, expected in ((b'9000.00N', b'18000.00E', (90,180)),
                                   (b'9000.00S', b'18000.00W', (-90,-180)),
                                   (b'0000.00N', b'00000.00W', (0,0)),
                                   (b'4903.50S', b'07201.75E', (-49-3.5/60,72+1.75/60))):
            v = parse_aprs_position(b'!'+lat+b'/'+lon+b'-')
            self.assertEqual((v['latitude_deg'],v['longitude_deg']),expected)

    def test_standard_null_position_is_not_a_coordinate_fix(self):
        value = parse_aprs_position(b'!0000.00N\\00000.00W.')
        self.assertEqual(value['status'], 'null_position')
        self.assertNotIn('latitude_deg', value)
        self.assertNotIn('longitude_deg', value)

    def test_ambiguity_also_suppresses_a_fully_populated_longitude(self):
        for count, lat in enumerate((b'4903.5 N', b'4903.  N', b'490 .  N', b'49  .  N'), 1):
            value = parse_aprs_position(b'!'+lat+b'/07201.75W>')
            self.assertEqual(value['status'], 'ambiguous_position')
            self.assertEqual(value['position_ambiguity_digits'], count)
            self.assertNotIn('latitude_deg', value)
            self.assertNotIn('longitude_deg', value)
        for body in (b'4903.  N/07201.7 W>', b'4903.50N/07201.7 W>', b'49 3.50N/07201.75W>'):
            value = parse_aprs_position(b'!'+body)
            self.assertNotIn('latitude_deg', value)
            self.assertNotIn('longitude_deg', value)

    def test_invalid_coordinates_symbols_and_encodings_stay_raw(self):
        for body in (b'4960.00N/07201.75W>', b'9100.00N/07201.75W>', b'9000.01N/07201.75W>',
                     b'4903.50N/18100.00W>', b'4903.50N/18000.01W>', b'4903.50N/07260.00W>',
                     b'4903.50E/07201.75W>', b'4903.50N/07201.75N>', b'4903.50N!07201.75W>',
                     b'4903.50N/07201.75W ', b'4903.50N/07201.75W\x7f', b'4903,50N/07201.75W>',
                     b'\xff903.50N/07201.75W>', b'short'):
            value = parse_aprs_position(b'!'+body)
            self.assertNotIn('latitude_deg', value, body)
            self.assertNotIn('longitude_deg', value, body)
        for table in (b'/', b'\\', b'A', b'0'):
            self.assertEqual(parse_aprs_position(b'!4903.50N'+table+b'07201.75W>')['status'], 'decoded_position')

    def test_course_speed_and_altitude_units_and_provenance(self):
        value = parse_aprs_position(PAYLOAD)
        self.assertEqual((value['course_deg'],value['speed_knots']), (88,36))
        self.assertAlmostEqual(value['speed_m_s'], 18.52)
        self.assertEqual(value['altitude_ft'],1234)
        self.assertAlmostEqual(value['altitude_m'],376.1232)
        self.assertEqual(value['altitude_annotation'],'/A=001234')
        self.assertEqual(value['comment_and_extensions_hex'],PAYLOAD[27:].hex())
        self.assertTrue(value['comment_and_extensions'].endswith('<b>test</b>'))

    def test_unknown_course_speed_versus_real_zero_speed(self):
        for extension in (b'000/000', b'.../...', b'   /   ', b'000/036', b'361/036', b'999/999'):
            value = parse_aprs_position(b'!'+POSITION+extension)
            self.assertNotIn('speed_knots',value)
            self.assertNotIn('course_deg',value)
        value = parse_aprs_position(b'!'+POSITION+b'360/000/A=000000')
        self.assertEqual((value['course_deg'],value['speed_knots'],value['speed_m_s']), (360,0,0))
        self.assertEqual((value['altitude_ft'],value['altitude_m']), (0,0))
        self.assertNotIn('course_deg',parse_aprs_position(b'!'+POSITION+b'comment 088/036'))

    def test_weather_and_df_do_not_invent_vehicle_speed(self):
        for symbol in (b'_', b'\\'):
            value = parse_aprs_position(b'!'+POSITION[:-1]+symbol+b'225/004g010t050')
            self.assertEqual(value['status'],'decoded_position')
            self.assertNotIn('course_deg',value)
            self.assertNotIn('speed_knots',value)

    def test_malformed_or_multiple_altitudes_do_not_choose_a_value(self):
        for comment in (b'/A=00123',b'/A=-00012',b'/A=1234567',b'/A=001234 /A=005678',b'/A=broken /A=001234',b'/a=001234'):
            value = parse_aprs_position(b'!'+POSITION+comment)
            self.assertEqual(value['status'],'decoded_position')
            self.assertNotIn('altitude_ft',value)
        self.assertEqual(parse_aprs_position(b'!'+POSITION+b'hello/A=001234')['altitude_ft'],1234)

    def test_other_aprs_types_and_arbitrary_text_are_not_positions(self):
        for body in (b'', b'CQ IQSCOPE', b'T#001,123,234', b':N0CALL   :message', b'>status', b'$GPGGA,...',
                     b';OBJECT   *092345z'+POSITION, b'`mic-e', b'}third-party'):
            self.assertIsNone(parse_aprs_position(body))
        self.assertIsNone(parse_aprs_position(b'!'+POSITION+b'x'*256))

    def test_crc_and_pid_gate_and_original_octets_remain_unchanged(self):
        inputs = [candidate(hdlc(frame(payload=PAYLOAD)))]; untouched=deepcopy(inputs)
        result=decode_ax25(inputs); self.assertEqual(inputs,untouched)
        self.assertEqual(len(result['frames']),1)
        fields=result['frames'][0]['fields']
        self.assertEqual(fields['payload_hex'],PAYLOAD.hex())
        self.assertEqual(fields['text'],PAYLOAD.decode())
        self.assertEqual(fields['aprs']['status'],'decoded_position')
        self.assertEqual(decode_ax25([candidate(hdlc(frame(payload=PAYLOAD,bad=True)))])['frames'],[])
        body=bytearray(frame(payload=PAYLOAD)[:-2]);body[15]=0xCF
        other=decode_ax25([candidate(hdlc(with_fcs(bytes(body))))])['frames'][0]['fields']
        self.assertNotIn('aprs',other)
        json.dumps(result,allow_nan=False)

    def test_iq_and_afsk_audio_receiver_paths(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        from test_ax25 import fixture as iq_fixture
        from test_afsk import fixture as audio_fixture
        iq,fs=iq_fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(iq,fs,0,directory)
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
            self.assertGreaterEqual(len(frames),3)
            self.assertTrue(all(f['fields']['aprs']['altitude_ft']==1234 for f in frames))
        audio,fs=audio_fixture(payload=PAYLOAD)
        frames=decode_afsk1200(audio,fs)['frames']
        self.assertEqual(len(frames),4)
        self.assertTrue(all(f['fields']['aprs']['speed_knots']==36 for f in frames))

    def test_bpsk_g3ruh_uses_the_same_crc_gated_payload_interpretation(self):
        for bad in (False,True):
            packet=frame(payload=PAYLOAD,bad=bad)
            state=register=0; scrambled=[]
            for bit in hdlc(packet):
                state ^= int(bit=='0')
                output=state^((register>>11)&1)^((register>>16)&1)
                scrambled.append(str(output))
                register=((register<<1)|output)&0x1ffff
            source=candidate(''.join(scrambled));source['modulation']='BPSK'
            frames=decode_psk_ax25([source])['frames']
            if bad:
                self.assertEqual(frames,[])
            else:
                self.assertEqual(len(frames),1)
                self.assertEqual(frames[0]['hex'],packet.hex())
                self.assertEqual(frames[0]['frontend'],'bpsk_g3ruh')
                self.assertEqual(frames[0]['fields']['aprs']['altitude_ft'],1234)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_import_and_json_export_with_unknown_rf_center(self):
        from test_afsk import fixture
        from iqscope_audio import analyze_audio
        audio,fs=fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'aprs.wav';wavfile.write(path,fs,audio.astype(np.float32))
            report=analyze_audio(path,root/'out')
            self.assertIsNone(report['center_frequency_hz'])
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_ax25')
            self.assertEqual(len(trial['frames']),4)
            exported=json.loads((root/'out'/report['frame_artifact']).read_text())
            self.assertEqual(exported['frames'],trial['frames'])
            self.assertAlmostEqual(trial['frames'][0]['fields']['aprs']['latitude_deg'],49+3.5/60)


if __name__=='__main__':
    unittest.main()

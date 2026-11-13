"""APRS101 compressed examples, boundary abstentions and receiver integration."""
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
from test_ax25 import frame, hdlc, candidate

COMPRESSED = b'/5L!!<*e7>7P['
PAYLOAD = b'@092345z'+COMPRESSED+b' <b>compressed</b>'


def encode_integer(number):
    # Independent place-value fixture encoder, not a decoder round trip.
    digits=[]
    for divisor in (91**3,91**2,91,1):
        digit,number=divmod(number,divisor)
        digits.append(digit+33)
    return bytes(digits)


def point(latitude,longitude,table=b'/',symbol=b'>',extension=b'   '):
    return b'!'+table+encode_integer(round((90-latitude)*380926))+encode_integer(round((longitude+180)*190463))+symbol+extension


class CompressedAprsTests(unittest.TestCase):
    def test_published_position_four_identifiers_and_partial_timestamp(self):
        for dti in b'!=/@':
            payload=bytes([dti])+(b'092345z' if dti in b'/@' else b'')+COMPRESSED
            value=parse_aprs_position(payload)
            self.assertEqual(value['status'],'decoded_position')
            self.assertEqual(value['format'],'compressed')
            self.assertEqual(value['latitude_deg'],49.5)
            # APRS101 truncates 20427156.75 into four base-91 digits. Its
            # displayed -72.75 degrees is rounded, not the decoded value.
            self.assertAlmostEqual(value['longitude_deg'],-72.75,delta=1/190463)
            self.assertNotEqual(value['longitude_deg'],-72.75)
            self.assertEqual(value['compressed_position_hex'],COMPRESSED.hex())
            self.assertEqual(value['messaging_capability_reported'],dti in b'=@')
            if dti in b'/@':
                self.assertEqual(value['timestamp']['day'],9)
                self.assertNotIn('month',value['timestamp'])
        self.assertEqual(parse_aprs_position(b'@092445z'+COMPRESSED)['status'],'invalid_timestamp')

    def test_published_motion_and_reported_compression_type(self):
        value=parse_aprs_position(PAYLOAD)
        self.assertEqual(value['course_deg'],88)
        self.assertAlmostEqual(value['speed_knots'],36.2,delta=.05)
        self.assertAlmostEqual(value['speed_m_s'],value['speed_knots']*1852/3600)
        self.assertEqual(value['compression_type'],dict(raw='[',value=58,gps_fix_reported='current',nmea_source_reported='RMC',compression_origin_code=2))
        self.assertEqual(value['comment_and_extensions_hex'],b' <b>compressed</b>'.hex())
        self.assertNotIn('altitude_ft',value)

    def test_published_gga_altitude_takes_priority_over_motion_and_range(self):
        value=parse_aprs_position(b'=/5L!!<*e7OS]S')
        self.assertEqual(value['compressed_extension_status'],'altitude')
        self.assertAlmostEqual(value['altitude_ft'],10004,delta=1)
        self.assertAlmostEqual(value['altitude_m'],value['altitude_ft']*.3048)
        self.assertEqual(value['compression_type']['nmea_source_reported'],'GGA')
        self.assertNotIn('speed_knots',value)
        # c='{' means range only outside the GGA source format.
        gga=parse_aprs_position(b'!'+COMPRESSED[:10]+b'{?S')
        self.assertEqual(gga['compressed_extension_status'],'altitude')
        self.assertNotIn('radio_range_m',gga)

    def test_published_radio_range_is_not_vehicle_speed_or_measured_range(self):
        value=parse_aprs_position(b'@092345z/5L!!<*e7>{?!')
        self.assertEqual(value['compressed_extension_status'],'precalculated_radio_range')
        self.assertAlmostEqual(value['radio_range_miles'],20,delta=.2)
        self.assertAlmostEqual(value['radio_range_m'],value['radio_range_miles']*1609.344)
        self.assertNotIn('speed_knots',value)
        self.assertNotIn('altitude_ft',value)

    def test_blank_c_ignores_both_fillers_without_inventing_fix_or_speed(self):
        for fillers in (b'sT',b'  ',b'\xff\x00'):
            value=parse_aprs_position(b'!'+COMPRESSED[:10]+b' '+fillers)
            self.assertEqual(value['status'],'decoded_position')
            self.assertNotIn('compression_type',value)
            self.assertNotIn('speed_knots',value)
            self.assertNotIn('altitude_ft',value)

    def test_encoded_zero_motion_and_old_fix_are_not_missing_values(self):
        value=parse_aprs_position(b'!'+COMPRESSED[:10]+b'!!!')
        self.assertEqual((value['course_deg'],value['speed_knots'],value['speed_m_s']),(0,0,0))
        self.assertEqual(value['compression_type']['gps_fix_reported'],'old')
        self.assertEqual(value['compression_type']['nmea_source_reported'],'other')
        self.assertNotIn('fix_age_seconds',value)

    def test_compressed_symbol_overlay_mapping_and_digit_discrimination(self):
        for table,overlay in ((b'a','0'),(b'j','9'),(b'A','A'),(b'Z','Z')):
            value=parse_aprs_position(b'!'+table+COMPRESSED[1:])
            self.assertEqual(value['symbol_table'],table.decode())
            self.assertEqual(value['symbol_overlay'],overlay)
            self.assertEqual(value['latitude_deg'],49.5)
        for table in (b'0',b'9',b'k',b'z',b'!',b' '):
            self.assertNotIn('latitude_deg',parse_aprs_position(b'!'+table+COMPRESSED[1:]))

    def test_geographic_boundaries_signs_zero_and_resolution(self):
        for lat,lon in ((90,-180),(-90,180),(0,0),(-49.5,72.75)):
            value=parse_aprs_position(point(lat,lon))
            self.assertAlmostEqual(value['latitude_deg'],lat,delta=1/380926)
            self.assertAlmostEqual(value['longitude_deg'],lon,delta=1/190463)
            self.assertLess(value['encoded_resolution_degrees']['latitude'],.000003)
            self.assertNotIn('encoded_resolution_minutes',value)
        value=parse_aprs_position(point(0,0,table=b'\\',symbol=b'.'))
        self.assertEqual(value['status'],'null_position')
        self.assertNotIn('latitude_deg',value)
        self.assertNotIn('longitude_deg',value)

    def test_truncated_invalid_base91_and_out_of_range_never_create_a_point(self):
        for end in range(13):
            self.assertNotIn('latitude_deg',parse_aprs_position(b'!'+COMPRESSED[:end]))
        for index in range(1,9):
            for byte in (32,124,255):
                body=bytearray(COMPRESSED);body[index]=byte
                self.assertNotIn('latitude_deg',parse_aprs_position(b'!'+body))
        for body in (b'/{{{{'+COMPRESSED[5:],COMPRESSED[:5]+b'{{{{'+COMPRESSED[9:]):
            self.assertEqual(parse_aprs_position(b'!'+body)['status'],'invalid_coordinates')
        for symbol in (b' ',b'\x7f'):
            self.assertNotIn('latitude_deg',parse_aprs_position(b'!'+COMPRESSED[:9]+symbol+COMPRESSED[10:]))

    def test_bad_extensions_keep_valid_position_but_no_derived_extension(self):
        for extension in (b'7P ',b'7Pa',b'7P{',b'\x7cP[',b'7 [',b'7\xff['):
            value=parse_aprs_position(b'!'+COMPRESSED[:10]+extension)
            self.assertEqual(value['status'],'decoded_position')
            self.assertEqual(value['compressed_extension_status'],'invalid_base91_or_reserved_type_bits')
            for key in ('course_deg','speed_knots','altitude_ft','compression_type','radio_range_m'):
                self.assertNotIn(key,value)

    def test_weather_df_and_comment_motion_do_not_invent_vehicle_motion(self):
        for symbol in (b'_',b'\\'):
            value=parse_aprs_position(b'!'+COMPRESSED[:9]+symbol+COMPRESSED[10:])
            self.assertEqual(value['status'],'decoded_position')
            self.assertNotIn('speed_knots',value)
        value=parse_aprs_position(b'!'+COMPRESSED[:10]+b'   088/036/A=001234')
        self.assertNotIn('course_deg',value)
        self.assertEqual(value['altitude_ft'],1234)

    def test_conflicting_altitude_encodings_keep_candidates_without_a_choice(self):
        for tail in (b'/A=001234',b'/A=broken',b'/A=001234/A=005678'):
            value=parse_aprs_position(b'=/5L!!<*e7OS]S'+tail)
            self.assertEqual(value['altitude_status'],'multiple_encodings; no value selected')
            self.assertEqual(len(value['altitude_candidates']),2)
            self.assertNotIn('altitude_ft',value)
            self.assertNotIn('altitude_m',value)
            json.dumps(value,allow_nan=False)

    def test_crc_gate_immutability_and_bpsk_shared_parser(self):
        for bad in (False,True):
            packet=frame(payload=PAYLOAD,bad=bad)
            inputs=[candidate(hdlc(packet))];untouched=deepcopy(inputs)
            decoded=decode_ax25(inputs)['frames']
            self.assertEqual(inputs,untouched)
            state=register=0;bits=[]
            for bit in hdlc(packet):
                state ^= int(bit=='0')
                output=state^((register>>11)&1)^((register>>16)&1)
                bits.append(str(output));register=((register<<1)|output)&0x1ffff
            bpsk=candidate(''.join(bits));bpsk['modulation']='BPSK'
            for frames in (decoded,decode_psk_ax25([bpsk])['frames']):
                if bad:self.assertEqual(frames,[])
                else:
                    self.assertEqual(len(frames),1)
                    fields=frames[0]['fields']
                    self.assertEqual(fields['payload_hex'],PAYLOAD.hex())
                    self.assertEqual(fields['aprs']['latitude_deg'],49.5)

    def test_actual_iq_and_afsk_audio_receiver_paths(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        from test_ax25 import fixture as iq_fixture
        from test_afsk import fixture as audio_fixture
        iq,fs=iq_fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(iq,fs,0,directory)
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
            self.assertGreaterEqual(len(frames),3)
            self.assertTrue(all(f['fields']['aprs']['format']=='compressed' for f in frames))
        audio,fs=audio_fixture(payload=PAYLOAD)
        frames=decode_afsk1200(audio,fs)['frames']
        self.assertEqual(len(frames),4)
        for frame_result in frames:
            self.assertAlmostEqual(frame_result['fields']['aprs']['longitude_deg'],-72.75,delta=1/190463)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_import_and_json_export_preserve_raw_and_interpreted_values(self):
        from test_afsk import fixture
        from iqscope_audio import analyze_audio
        audio,fs=fixture(payload=PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'compressed.wav'
            wavfile.write(path,fs,audio.astype(np.float32))
            report=analyze_audio(path,root/'out')
            self.assertIsNone(report['center_frequency_hz'])
            frames=next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_ax25')['frames']
            exported=json.loads((root/'out'/report['frame_artifact']).read_text())
            self.assertEqual(exported['frames'],frames)
            self.assertEqual(len(frames),4)
            self.assertTrue(all(f['fields']['payload_hex']==PAYLOAD.hex() for f in frames))


if __name__=='__main__':
    unittest.main()

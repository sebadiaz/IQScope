"""TC19 examples and independent binary/PPM construction, with availability guards."""
from copy import deepcopy
import json
import unittest

from iqscope_adsb import enrich_adsb_frames
from iqscope_decoders import decode_adsb
from test_adsb_fields import record, replace_message
from test_decoders import reference_iq

GROUND = bytes.fromhex('8D485020994409940838175B284F')
AIR = bytes.fromhex('8DA05F219B06B6AF189400CBC33F')


def velocity_frame(subtype=1, x_sign=0, x_code=1, y_sign=0, y_code=1,
                   vertical_source=0, vertical_sign=0, vertical_code=1):
    # Independent bit-string fixture follows the field layout, not decoder
    # arithmetic. x/y also carry heading-status/heading and IAS/TAS/airspeed.
    bits = (f'10011{subtype:03b}00'+'000'+
            f'{x_sign:01b}{x_code:010b}{y_sign:01b}{y_code:010b}'+
            f'{vertical_source:01b}{vertical_sign:01b}{vertical_code:09b}00'+'00000000')
    assert len(bits) == 56
    return replace_message(GROUND, message=int(bits, 2))


def velocity(raw):
    return enrich_adsb_frames([record(raw, 0.)])[0]['fields']['velocity']


def reference_velocity_iq():
    samples = reference_iq(GROUND, count=20000, start=1000)
    samples[6000:6240] = reference_iq(AIR)[1000:1240]
    return samples


class AdsbVelocityTests(unittest.TestCase):
    def test_published_ground_vector(self):
        v = velocity(GROUND)
        self.assertEqual(v['subtype'], 1)
        self.assertEqual(v['east_velocity_kt'], -8)
        self.assertEqual(v['north_velocity_kt'], -159)
        self.assertAlmostEqual(v['ground_speed_kt'], 159.20113064925135, places=8)
        self.assertAlmostEqual(v['ground_track_deg'], 182.8803775528476, places=8)
        self.assertEqual(v['vertical_rate_ft_min'], -832)
        self.assertEqual(v['vertical_rate_source'], 'GNSS')
        self.assertNotIn('airspeed_kt', v)
        self.assertNotIn('heading_deg', v)

    def test_published_air_vector(self):
        v = velocity(AIR)
        self.assertEqual(v['subtype'], 3)
        self.assertEqual(v['airspeed_kt'], 375)
        self.assertEqual(v['airspeed_kind'], 'TAS')
        self.assertEqual(v['heading_deg'], 243.984375)
        self.assertEqual(v['heading_reference'], 'not_determined_from_tc19')
        self.assertEqual(v['vertical_rate_ft_min'], -2304)
        self.assertEqual(v['vertical_rate_source'], 'barometric')
        self.assertNotIn('ground_speed_kt', v)
        self.assertNotIn('ground_track_deg', v)

    def test_cardinal_ground_directions(self):
        cases = ((0, 1, 0, 6, 0.), (0, 6, 0, 1, 90.),
                 (0, 1, 1, 6, 180.), (1, 6, 0, 1, 270.))
        for xs, xc, ys, yc, track in cases:
            v = velocity(velocity_frame(x_sign=xs, x_code=xc, y_sign=ys, y_code=yc))
            self.assertEqual(v['ground_speed_kt'], 5.)
            self.assertEqual(v['ground_track_deg'], track)

    def test_supersonic_subtypes_change_speed_resolution(self):
        v = velocity(velocity_frame(subtype=2, x_code=4, y_code=5))
        self.assertEqual(v['speed_resolution_kt'], 4)
        self.assertEqual(v['east_velocity_kt'], 12)
        self.assertEqual(v['north_velocity_kt'], 16)
        self.assertEqual(v['ground_speed_kt'], 20.)
        self.assertAlmostEqual(v['ground_track_deg'], 36.86989764584402)
        air = velocity(velocity_frame(subtype=4, x_sign=1, x_code=0, y_sign=1, y_code=376))
        self.assertEqual(air['airspeed_kt'], 1500)
        self.assertEqual(air['airspeed_kind'], 'TAS')
        self.assertEqual(air['heading_deg'], 0.)

    def test_unavailable_components_are_not_zero_speeds(self):
        for xc, yc in ((0, 0), (0, 1), (1, 0)):
            v = velocity(velocity_frame(x_code=xc, y_code=yc, vertical_code=0))
            self.assertNotIn('ground_speed_kt', v)
            self.assertNotIn('ground_track_deg', v)
            self.assertNotIn('vertical_rate_ft_min', v)
            self.assertEqual(v['ground_track_status'], 'not_available')
            json.dumps(v, allow_nan=False)
        zero = velocity(velocity_frame())
        self.assertEqual(zero['ground_speed_kt'], 0.)
        self.assertEqual(zero['vertical_rate_ft_min'], 0)
        self.assertNotIn('ground_track_deg', zero)
        self.assertEqual(zero['ground_track_status'], 'undefined_at_zero_ground_speed')

    def test_airspeed_availability_and_heading_status_are_independent(self):
        v = velocity(velocity_frame(subtype=3, x_sign=0, x_code=694, y_code=0))
        self.assertNotIn('heading_deg', v)
        self.assertNotIn('airspeed_kt', v)
        self.assertEqual(v['heading_status'], 'not_available')
        self.assertEqual(v['horizontal_status'], 'not_available')
        zero = velocity(velocity_frame(subtype=3, x_sign=1, x_code=0, y_sign=0, y_code=1))
        self.assertEqual(zero['heading_deg'], 0.)
        self.assertEqual(zero['airspeed_kt'], 0)
        self.assertEqual(zero['airspeed_kind'], 'IAS')

    def test_vertical_sign_source_and_extreme_codes(self):
        for source, name in ((0, 'GNSS'), (1, 'barometric')):
            for sign, expected in ((0, 192), (1, -192)):
                v = velocity(velocity_frame(vertical_source=source, vertical_sign=sign, vertical_code=4))
                self.assertEqual(v['vertical_rate_ft_min'], expected)
                self.assertEqual(v['vertical_rate_source'], name)
        self.assertEqual(velocity(velocity_frame(vertical_code=511))['vertical_rate_ft_min'], 32640)
        self.assertEqual(velocity(velocity_frame(vertical_sign=1, vertical_code=1))['vertical_rate_ft_min'], 0)

    def test_crc_format_and_reserved_subtypes(self):
        corrupted = bytearray(GROUND); corrupted[6] ^= 2
        for raw in (bytes(corrupted), replace_message(GROUND, first_byte=0x93)):
            self.assertNotIn('velocity', enrich_adsb_frames([record(raw, 0.)])[0]['fields'])
        self.assertEqual(velocity(replace_message(GROUND, first_byte=0x90))['vertical_rate_ft_min'], -832)
        for subtype in (0, 5, 6, 7):
            v = velocity(velocity_frame(subtype=subtype, x_code=1023, vertical_code=511))
            self.assertEqual(v, {'subtype': subtype, 'status': 'unsupported_subtype'})

    def test_independent_ppm_receiver_and_serializable_fields(self):
        result = decode_adsb(reference_velocity_iq(), 2_000_000)
        self.assertEqual(len(result['frames']), 2)
        self.assertEqual(result['frames'][0]['fields']['velocity']['vertical_rate_ft_min'], -832)
        self.assertEqual(result['frames'][1]['fields']['velocity']['airspeed_kt'], 375)
        self.assertTrue(all(frame['evidence'][0]['result']=='pass' for frame in result['frames']))
        restored = json.loads(json.dumps(result, allow_nan=False))
        self.assertEqual(restored['frames'][1]['fields']['velocity']['airspeed_kind'], 'TAS')

    def test_enrichment_is_immutable_idempotent_and_clears_stale_values(self):
        records = [record(GROUND, 0.), record(AIR, 1.)]
        original = deepcopy(records)
        enriched = enrich_adsb_frames(records)
        self.assertEqual(records, original)
        self.assertEqual(enrich_adsb_frames(enriched), enriched)
        corrupted = bytearray(GROUND); corrupted[5] ^= 1
        enriched[0]['hex'] = bytes(corrupted).hex()
        self.assertNotIn('velocity', enrich_adsb_frames(enriched)[0]['fields'])

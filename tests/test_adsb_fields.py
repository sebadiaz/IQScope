"""Published Mode S messages, independent PPM fixtures and CPR pairing guards."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

import numpy as np

from iqscope_adsb import enrich_adsb_frames, _longitude_zones
from iqscope_decoders import decode_adsb, mode_s_remainder
from test_decoders import reference_iq

EVEN = bytes.fromhex('8D40621D58C382D690C8AC2863A7')
ODD = bytes.fromhex('8D40621D58C386435CC412692AD6')
IDENT = bytes.fromhex('8D4840D6202CC371C32CE0576098')


def record(raw, timestamp):
    return {'hex': raw.hex().upper(), 'time_seconds': timestamp,
            'sample_start': int(timestamp*2_000_000) if np.isfinite(timestamp) else None,
            'fields': {}}


def replace_message(raw, *, address=None, first_byte=None, latitude=None, longitude=None, message=None):
    # Test-frame construction uses CRC only, never the CPR decoding algorithm.
    prefix = bytearray(raw[:11])
    if address is not None:
        prefix[1:4] = bytes.fromhex(address)
    if first_byte is not None:
        prefix[0] = first_byte
    value = int.from_bytes(prefix[4:11], 'big') if message is None else message
    if latitude is not None:
        value = (value & ~(131071 << 17)) | (latitude << 17)
    if longitude is not None:
        value = (value & ~131071) | longitude
    prefix[4:11] = value.to_bytes(7, 'big')
    parity = mode_s_remainder(bytes(prefix)+bytes(3))
    return bytes(prefix)+parity.to_bytes(3, 'big')


def reference_aircraft_iq():
    # Odd is earlier, so the published even-frame coordinates are current.
    x = reference_iq(ODD, count=20000, start=1000)
    for raw, start in ((EVEN, 6000), (IDENT, 10000)):
        x[start:start+240] = reference_iq(raw)[1000:1240]
    return x


class AdsbFieldsTests(unittest.TestCase):
    def test_published_even_latest_position_and_callsign(self):
        frames = enrich_adsb_frames([record(ODD, 0.), record(EVEN, 2.), record(IDENT, 3.)])
        self.assertNotIn('latitude_deg', frames[0]['fields'])
        position = frames[1]['fields']
        self.assertAlmostEqual(position['latitude_deg'], 52.2572021484375, places=9)
        self.assertAlmostEqual(position['longitude_deg'], 3.91937255859375, places=9)
        self.assertEqual(position['cpr']['latitude_code'], 93000)
        self.assertEqual(position['cpr']['longitude_code'], 51372)
        self.assertEqual(position['position_evidence']['pair_age_seconds'], 2.)
        self.assertEqual(position['position_evidence']['even_sample_start'], 4000000)
        self.assertEqual(frames[2]['fields']['callsign'], 'KLM1023')

    def test_latest_odd_frame_is_used(self):
        frames = enrich_adsb_frames([record(EVEN, 0.), record(ODD, 1.)])
        position = frames[1]['fields']
        self.assertAlmostEqual(position['latitude_deg'], 52.26578017412606, places=9)
        self.assertAlmostEqual(position['longitude_deg'], 3.938912527901786, places=9)

    def test_age_address_parity_and_invalid_time_guards(self):
        bad_address = replace_message(ODD, address='ABCDEF')
        for first, second in (
            (record(EVEN, 0.), record(ODD, 10.0001)),
            (record(EVEN, 0.), record(bad_address, 1.)),
            (record(EVEN, 0.), record(EVEN, 1.)),
            (record(EVEN, 0.), record(ODD, float('nan'))),
        ):
            with self.subTest(second=second):
                self.assertFalse(any('latitude_deg' in f['fields'] for f in enrich_adsb_frames([first, second])))
        self.assertIn('latitude_deg', enrich_adsb_frames([record(EVEN, 0.), record(ODD, 10.)])[1]['fields'])

    def test_crc_and_unsupported_position_formats_do_not_derive_fields(self):
        corrupt = bytearray(EVEN); corrupt[8] ^= 1
        surface = replace_message(EVEN, message=(int.from_bytes(EVEN[4:11], 'big') & ((1 << 51)-1)) | (5 << 51))
        gnss = replace_message(EVEN, message=(int.from_bytes(EVEN[4:11], 'big') & ((1 << 51)-1)) | (20 << 51))
        for raw in (bytes(corrupt), surface, gnss):
            frames = enrich_adsb_frames([record(ODD, 0.), record(raw, 1.)])
            self.assertFalse(any('latitude_deg' in f['fields'] for f in frames))
        self.assertFalse(decode_adsb(reference_iq(bytes(corrupt)), 2_000_000)['frames'])

    def test_df18_control_and_address_domains_stay_separate(self):
        even0 = replace_message(EVEN, first_byte=0x90)
        odd0 = replace_message(ODD, first_byte=0x90)
        odd1 = replace_message(ODD, first_byte=0x91)
        odd3 = replace_message(ODD, first_byte=0x93)
        for other in (ODD, odd1, odd3):
            frames = enrich_adsb_frames([record(even0, 0.), record(other, 1.)])
            self.assertFalse(any('latitude_deg' in f['fields'] for f in frames))
        frames = enrich_adsb_frames([record(odd0, 0.), record(even0, 1.)])
        self.assertAlmostEqual(frames[1]['fields']['latitude_deg'], 52.2572021484375)
        self.assertNotIn('icao_hex', frames[1]['fields'])
        unsupported_position = replace_message(EVEN, first_byte=0x93)
        packet = decode_adsb(reference_iq(unsupported_position), 2_000_000)['frames'][0]
        self.assertNotIn('barometric_altitude_ft', packet['fields'])
        self.assertNotIn('latitude_deg', packet['fields'])
        # A non-ADS-B DF18 management/coarse format is not interpreted as ID.
        unsupported_id = replace_message(IDENT, first_byte=0x93)
        self.assertNotIn('callsign', enrich_adsb_frames([record(unsupported_id, 0.)])[0]['fields'])

    def test_southern_western_and_longitude_wrap(self):
        # Reflect the published CPR fractions about zero in both hemispheres.
        even_south = replace_message(EVEN, latitude=38072, longitude=79700)
        odd_south = replace_message(ODD, latitude=56914, longitude=80878)
        p = enrich_adsb_frames([record(odd_south, 0.), record(even_south, 1.)])[1]['fields']
        self.assertAlmostEqual(p['latitude_deg'], -52.2572021484375, places=8)
        self.assertAlmostEqual(p['longitude_deg'], -3.91937255859375, places=8)
        # Rotate longitude by 180 degrees: 36 even zones / 35 odd zones.
        odd_wrap = replace_message(ODD, longitude=115730)
        p = enrich_adsb_frames([record(odd_wrap, 0.), record(EVEN, 1.)])[1]['fields']
        self.assertAlmostEqual(p['longitude_deg'], -176.08062744140625, places=8)
        for lat, expected in ((0, 59), (87, 2), (-87, 2), (88, 1), (-90, 1)):
            self.assertEqual(_longitude_zones(lat), expected)

    def test_inconsistent_pair_and_reserved_callsign(self):
        even = replace_message(EVEN, latitude=0)
        odd = replace_message(ODD, latitude=65536)
        fields = enrich_adsb_frames([record(even, 0.), record(odd, 1.)])[1]['fields']
        self.assertNotIn('latitude_deg', fields)
        self.assertEqual(fields['cpr']['status'], 'inconsistent_latitude_zones')
        invalid_id = replace_message(IDENT, message=int.from_bytes(IDENT[4:11], 'big') & ~(63 << 42))
        fields = enrich_adsb_frames([record(invalid_id, 0.)])[0]['fields']
        self.assertNotIn('callsign', fields)
        self.assertEqual(fields['identification_status'], 'empty_or_reserved_character')

    def test_sorting_immutability_and_analysis_isolation(self):
        records = [record(EVEN, 1.), record(ODD, 0.)]
        original = deepcopy(records)
        enriched = enrich_adsb_frames(records)
        self.assertIn('latitude_deg', enriched[0]['fields'])
        self.assertEqual(records, original)
        self.assertEqual(enrich_adsb_frames(enriched), enriched)
        self.assertNotIn('latitude_deg', enrich_adsb_frames([record(EVEN, 2.)])[0]['fields'])

    def test_ppm_receiver_to_fields_and_json(self):
        result = decode_adsb(reference_aircraft_iq(), 2_000_000)
        self.assertEqual(len(result['frames']), 3)
        fields = [f['fields'] for f in result['frames']]
        self.assertAlmostEqual(fields[1]['latitude_deg'], 52.2572021484375)
        self.assertEqual(fields[1]['icao_hex'], '40621D')
        self.assertEqual(fields[2]['callsign'], 'KLM1023')
        self.assertTrue(all(f['evidence'][0]['result']=='pass' for f in result['frames']))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'frames.json'
            path.write_text(json.dumps(result))
            self.assertEqual(json.loads(path.read_text())['frames'][2]['fields']['callsign'], 'KLM1023')

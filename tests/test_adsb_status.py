"""Operational-status fields and causal same-domain metadata association."""
from copy import deepcopy
import json
import unittest

from iqscope_adsb import enrich_adsb_frames
from iqscope_decoders import decode_adsb, mode_s_remainder
from test_adsb_fields import EVEN, ODD, record, replace_message
from test_adsb_velocity import AIR, GROUND
from test_decoders import reference_iq

# Frozen synthetic TC31, A05F21, from the public field layout:
# v2, NICa1, NACp10, SIL3, NICbaro1, magnetic HRD, per-sample SIL.
STATUS = bytes.fromhex('8DA05F21F8000000005A3E4E0708')


def operational_frame(version=2, subtype=0, nac_p=10, sil=3, reference=1, supplement=1):
    # Independent bit-string construction: TC/ST, CC, OM, version and flags.
    bits = (f'11111{subtype:03b}'+'0'*32+
            f'{version:03b}1{nac_p:04b}00{sil:02b}1{reference:01b}{supplement:01b}0')
    assert len(bits) == 56
    return replace_message(AIR, message=int(bits, 2))


def fields(raw):
    return enrich_adsb_frames([record(raw, 0.)])[0]['fields']


def reference_status_iq():
    # Synthetic common address permits a complete status/velocity/CPR path;
    # position and velocity payloads come from separate published examples.
    odd = replace_message(ODD, address='A05F21')
    even = replace_message(EVEN, address='A05F21')
    result = reference_iq(STATUS, count=20000, start=1000)
    quality_air = replace_message(AIR, message=(int.from_bytes(AIR[4:11], 'big') & ~(7 << 43)) | (3 << 43))
    for frame, start in ((quality_air, 6000), (odd, 10000), (even, 14000)):
        result[start:start+240] = reference_iq(frame)[1000:1240]
    return result


class AdsbOperationalTests(unittest.TestCase):
    def test_frozen_v2_status_and_field_layout(self):
        self.assertEqual(mode_s_remainder(STATUS), 0)
        self.assertEqual(operational_frame(), STATUS)
        status = fields(STATUS)['operational_status']
        self.assertEqual(status['adsb_version'], 2)
        self.assertEqual(status['environment'], 'airborne')
        self.assertEqual(status['nac_p_code'], 10)
        self.assertEqual(status['horizontal_accuracy_95_bound_m'], 10.)
        self.assertEqual(status['sil_code'], 3)
        self.assertEqual(status['sil_probability_basis'], 'per_sample')
        self.assertEqual(status['heading_reference'], 'magnetic_north')
        self.assertEqual(status['nic_baro_code'], 1)
        self.assertEqual(status['nic_supplement_a'], 1)

    def test_v1_has_no_v2_sil_supplement_and_surface_has_no_baro(self):
        v1 = fields(operational_frame(version=1, reference=0))['operational_status']
        self.assertEqual(v1['heading_reference'], 'true_north')
        self.assertEqual(v1['sil_probability_basis'], 'not_determined_from_version1')
        self.assertNotIn('sil_supplement', v1)
        surface = fields(operational_frame(subtype=1))['operational_status']
        self.assertEqual(surface['environment'], 'surface')
        self.assertNotIn('nic_baro_code', surface)

    def test_declared_precision_boundaries_and_unknown_codes(self):
        # Independently convert the standard nautical-mile thresholds to SI.
        for code, nautical_miles in enumerate((10, 4, 2, 1, .5, .3, .1, .05), 1):
            s = fields(operational_frame(nac_p=code))['operational_status']
            self.assertEqual(s['nac_p_status'], 'reported_bound')
            self.assertAlmostEqual(s['horizontal_accuracy_95_bound_m'], nautical_miles*1852, places=8)
        for code, meters in ((9, 30.), (10, 10.), (11, 3.)):
            self.assertEqual(fields(operational_frame(nac_p=code))['operational_status']['horizontal_accuracy_95_bound_m'], meters)
        for code in (0, 12, 13, 14, 15):
            s = fields(operational_frame(nac_p=code))['operational_status']
            self.assertNotIn('horizontal_accuracy_95_bound_m', s)
            self.assertEqual(s['nac_p_status'], 'not_available' if code == 0 else 'reserved_code')

    def test_recent_status_resolves_heading_without_changing_angle(self):
        for bit, reference in ((0, 'true_north'), (1, 'magnetic_north')):
            frames = enrich_adsb_frames([record(operational_frame(reference=bit), 0.), record(AIR, 1.)])
            v = frames[1]['fields']['velocity']
            self.assertEqual(v['heading_deg'], 243.984375)
            self.assertEqual(v['heading_reference'], reference)
            self.assertEqual(v['operational_context']['status_age_seconds'], 1.)
            self.assertEqual(v['operational_context']['status_sample_start'], 0)

    def test_no_future_expired_cross_address_or_cross_domain_context(self):
        for status, when in ((STATUS, 2.), (STATUS, -1.),
                             (replace_message(STATUS, address='ABCDEF'), 0.),
                             (replace_message(STATUS, first_byte=0x90), 0.)):
            result = enrich_adsb_frames([record(AIR, 1.), record(status, when)])
            self.assertEqual(result[0]['fields']['velocity']['heading_reference'], 'not_determined_from_tc19')
        for control in (0, 1):
            status = replace_message(STATUS, first_byte=0x90+control)
            air = replace_message(AIR, first_byte=0x90+control)
            v = enrich_adsb_frames([record(status, 0.), record(air, 1.)])[1]['fields']['velocity']
            self.assertEqual(v['heading_reference'], 'magnetic_north')
            other = replace_message(AIR, first_byte=0x90+(1-control))
            v = enrich_adsb_frames([record(status, 0.), record(other, 1.)])[1]['fields']['velocity']
            self.assertEqual(v['heading_reference'], 'not_determined_from_tc19')
        result = enrich_adsb_frames([record(STATUS, 0.), record(AIR, 10.0001)])
        self.assertEqual(result[1]['fields']['velocity']['heading_reference'], 'not_determined_from_tc19')
        result = enrich_adsb_frames([record(STATUS, 0.), record(AIR, 10.)])
        self.assertEqual(result[1]['fields']['velocity']['heading_reference'], 'magnetic_north')

    def test_unsupported_or_surface_status_cancels_old_context(self):
        for newer in (operational_frame(version=0), operational_frame(version=3),
                      operational_frame(subtype=1), operational_frame(subtype=2)):
            frames = enrich_adsb_frames([record(STATUS, 0.), record(newer, 1.), record(AIR, 2.)])
            self.assertEqual(frames[-1]['fields']['velocity']['heading_reference'], 'not_determined_from_tc19')
        for version in (0, 3, 4, 5, 6, 7):
            s = fields(operational_frame(version=version))['operational_status']
            self.assertEqual(s['status'], 'unsupported_version')
            self.assertNotIn('heading_reference', s)
            self.assertNotIn('horizontal_accuracy_95_bound_m', s)

    def test_velocity_quality_needs_version_context(self):
        raw = int.from_bytes(GROUND[4:11], 'big')
        for code, expected in ((1, 10.), (2, 3.), (3, 1.), (4, .3)):
            message = replace_message(GROUND, address='A05F21', message=(raw & ~(7 << 43)) | (code << 43))
            standalone = fields(message)['velocity']
            self.assertEqual(standalone['velocity_accuracy_code'], code)
            self.assertNotIn('nac_v_code', standalone)
            result = enrich_adsb_frames([record(STATUS, 0.), record(message, 1.)])
            v = result[1]['fields']['velocity']
            self.assertEqual(v['nac_v_code'], code)
            self.assertEqual(v['horizontal_velocity_error_95_bound_m_s'], expected)
            self.assertNotIn('heading_reference', v)
        for code in (0, 5, 6, 7):
            message = replace_message(GROUND, address='A05F21', message=(raw & ~(7 << 43)) | (code << 43))
            v = enrich_adsb_frames([record(STATUS, 0.), record(message, 1.)])[1]['fields']['velocity']
            self.assertNotIn('horizontal_velocity_error_95_bound_m_s', v)

    def test_position_quality_is_causal_and_preserves_pair_evidence(self):
        odd = replace_message(ODD, address='A05F21')
        even = replace_message(EVEN, address='A05F21')
        records = [record(STATUS, 0.), record(odd, 1.), record(even, 2.)]
        p = enrich_adsb_frames(records)[2]['fields']
        self.assertAlmostEqual(p['latitude_deg'], 52.2572021484375)
        self.assertEqual(p['position_quality']['nac_p_code'], 10)
        self.assertEqual(p['position_quality']['horizontal_accuracy_95_bound_m'], 10.)
        self.assertEqual(p['position_evidence']['even_time_seconds'], 2.)
        late = enrich_adsb_frames([record(odd, 0.), record(even, 1.), record(STATUS, 2.)])
        self.assertNotIn('position_quality', late[1]['fields'])

    def test_crc_invalid_time_and_new_analysis_do_not_supply_context(self):
        corrupted = bytearray(STATUS); corrupted[7] ^= 1
        for raw in (bytes(corrupted), replace_message(STATUS, first_byte=0x93)):
            self.assertNotIn('operational_status', fields(raw))
            v = enrich_adsb_frames([record(raw, 0.), record(AIR, 1.)])[1]['fields']['velocity']
            self.assertEqual(v['heading_reference'], 'not_determined_from_tc19')
        v = enrich_adsb_frames([record(STATUS, float('nan')), record(AIR, 1.)])[1]['fields']['velocity']
        self.assertEqual(v['heading_reference'], 'not_determined_from_tc19')
        enrich_adsb_frames([record(STATUS, 0.)])
        self.assertEqual(fields(AIR)['velocity']['heading_reference'], 'not_determined_from_tc19')

    def test_ordering_refresh_and_input_immutability(self):
        rows = [record(AIR, 2.), record(STATUS, 0.), record(operational_frame(reference=0), 1.)]
        original = deepcopy(rows)
        enriched = enrich_adsb_frames(rows)
        self.assertEqual(rows, original)
        self.assertEqual(enriched[0]['fields']['velocity']['heading_reference'], 'true_north')
        self.assertEqual(enriched[0]['fields']['velocity']['operational_context']['status_time_seconds'], 1.)
        self.assertEqual(enrich_adsb_frames(enriched), enriched)

    def test_ppm_receiver_and_serializable_report(self):
        report = decode_adsb(reference_status_iq(), 2_000_000)
        self.assertEqual(len(report['frames']), 4)
        f = report['frames']
        self.assertEqual(f[0]['fields']['operational_status']['nac_p_code'], 10)
        self.assertEqual(f[1]['fields']['velocity']['heading_reference'], 'magnetic_north')
        self.assertEqual(f[1]['fields']['velocity']['horizontal_velocity_error_95_bound_m_s'], 1.)
        self.assertEqual(f[3]['fields']['position_quality']['sil_probability_basis'], 'per_sample')
        json.dumps(report, allow_nan=False)

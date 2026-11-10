"""Versioned NIC and conservative CPR pairing, from independent bit fixtures."""
from copy import deepcopy
import json
import unittest
from iqscope_adsb import enrich_adsb_frames
from iqscope_decoders import decode_adsb
from test_adsb_fields import EVEN, ODD, record, replace_message
from test_adsb_status import operational_frame
from test_adsb_velocity import AIR
from test_decoders import reference_iq


def status_frame(version=2, supplement=0):
    raw = operational_frame(version=version)
    bits = list(f'{int.from_bytes(raw[4:11], "big"):056b}')
    bits[43] = str(supplement)
    return replace_message(raw, message=int(''.join(bits), 2))


def position_frame(odd=False, type_code=11, supplement_bit=0):
    raw = ODD if odd else EVEN
    bits = list(f'{int.from_bytes(raw[4:11], "big"):056b}')
    bits[:5] = f'{type_code:05b}'
    bits[7] = str(supplement_bit)
    return replace_message(raw, address='A05F21', message=int(''.join(bits), 2))


def integrity(version, tc, a=0, b=0):
    rows = [record(status_frame(version, a), 0.),
            record(position_frame(type_code=tc, supplement_bit=b), 1.)]
    return enrich_adsb_frames(rows)[-1]['fields']['position_integrity']


def reference_integrity_iq():
    messages = ((status_frame(supplement=0), 1000), (position_frame(odd=True), 4000),
                (status_frame(supplement=1), 8000),
                (position_frame(supplement_bit=1), 12000), (AIR, 16000))
    samples = reference_iq(messages[0][0], count=20000, start=1000)
    for raw, start in messages[1:]:
        samples[start:start+240] = reference_iq(raw)[1000:1240]
    return samples


class AdsbIntegrityTests(unittest.TestCase):
    def test_fixed_categories_and_exact_nm_conversion(self):
        for version in (1, 2):
            for tc, nic, meters in ((9,11,7.5), (10,10,25.)):
                v = integrity(version, tc)
                self.assertEqual((v['nic_category'], v['containment_radius_bound_m']), (nic, meters))
            for tc, nic, nm in ((12,7,.2), (14,5,1), (15,4,2), (17,1,20)):
                v = integrity(version, tc)
                self.assertEqual(v['nic_category'], nic)
                self.assertAlmostEqual(v['containment_radius_bound_m'], nm*1852, places=8)

    def test_v1_ignores_legacy_bit_and_uses_status_supplement(self):
        for b in (0, 1):
            self.assertEqual(integrity(1, 11, 0, b)['nic_category'], 8)
            high = integrity(1, 11, 1, b)
            self.assertEqual((high['nic_category'], high['containment_radius_bound_m']), (9,75.))
            self.assertNotIn('nic_supplement_b', high)
            self.assertEqual(high['nic_supplement_s'], 1)
        for a, nic, nm in ((0,2,8), (1,3,4)):
            v = integrity(1, 16, a)
            self.assertEqual(v['nic_category'], nic)
            self.assertEqual(v['containment_radius_bound_m'], nm*1852)
        for a, nm in ((0,.5), (1,.6)):
            self.assertAlmostEqual(integrity(1, 13, a)['containment_radius_bound_m'], nm*1852)

    def test_v2_combinations_and_distinct_radii(self):
        for a,b,nic,radius in ((0,0,8,185.2), (1,1,9,75.)):
            v = integrity(2, 11, a, b)
            self.assertEqual((v['nic_category'],v['containment_radius_bound_m']), (nic,radius))
            self.assertEqual((v['nic_supplement_a'],v['nic_supplement_b']), (a,b))
        for a,b,nm in ((0,1,.3), (0,0,.5), (1,1,.6)):
            v = integrity(2, 13, a, b)
            self.assertEqual(v['nic_category'], 6)
            self.assertAlmostEqual(v['containment_radius_bound_m'], nm*1852)
        for a,b,nic,nm in ((0,0,2,8), (1,1,3,4)):
            v = integrity(2, 16, a, b)
            self.assertEqual(v['nic_category'], nic)
            self.assertEqual(v['containment_radius_bound_m'], nm*1852)

    def test_reserved_combinations_have_no_bound(self):
        for tc,a,b in ((11,0,1),(11,1,0),(13,1,0),(16,0,1),(16,1,0),
                       (9,1,0),(10,0,1),(12,1,1),(14,0,1),(15,1,0),(17,1,1),(18,0,1)):
            v = integrity(2, tc, a, b)
            self.assertEqual(v['status'], 'reserved_combination')
            self.assertNotIn('nic_category', v)
            self.assertNotIn('containment_radius_bound_m', v)
        self.assertEqual(integrity(1, 9, 1)['status'], 'reserved_combination')

    def test_pair_keeps_worse_older_member_and_provenance(self):
        rows = [record(status_frame(),0.), record(position_frame(odd=True),1.),
                record(status_frame(supplement=1),2.), record(position_frame(supplement_bit=1),3.)]
        p = enrich_adsb_frames(rows)[-1]['fields']
        self.assertAlmostEqual(p['latitude_deg'],52.2572021484375)
        self.assertEqual(p['position_integrity']['nic_category'],9)
        pair = p['position_integrity_pair']
        self.assertEqual(pair['nic_category'],8)
        self.assertAlmostEqual(pair['containment_radius_bound_m'],.1*1852)
        self.assertEqual(pair['members']['odd']['operational_context']['status_time_seconds'],0.)
        self.assertEqual(pair['members']['even']['operational_context']['status_time_seconds'],2.)

    def test_same_nic_different_radii_uses_largest(self):
        rows = [record(status_frame(),0.), record(position_frame(odd=True,type_code=13,supplement_bit=1),1.),
                record(status_frame(supplement=1),2.), record(position_frame(type_code=13,supplement_bit=1),3.)]
        p = enrich_adsb_frames(rows)[-1]['fields']['position_integrity_pair']
        self.assertEqual(p['nic_category'],6)
        self.assertAlmostEqual(p['members']['odd']['containment_radius_bound_m'],.3*1852)
        self.assertAlmostEqual(p['members']['even']['containment_radius_bound_m'],.6*1852)
        self.assertAlmostEqual(p['containment_radius_bound_m'],.6*1852)

    def test_incomplete_pair_or_reserved_member_stays_unknown(self):
        scenarios = ([record(position_frame(odd=True),0.),record(position_frame(),1.)],
                     [record(position_frame(odd=True),0.),record(status_frame(supplement=1),.5),record(position_frame(supplement_bit=1),1.)],
                     [record(status_frame(),0.),record(position_frame(odd=True,supplement_bit=1),1.),record(position_frame(),2.)])
        for rows in scenarios:
            p = enrich_adsb_frames(rows)[-1]['fields']
            self.assertIn('latitude_deg',p)
            self.assertEqual(p['position_integrity_pair']['status'],'incomplete_or_uninterpreted_member')
            self.assertNotIn('containment_radius_bound_m',p['position_integrity_pair'])
            self.assertNotIn('nic_category',p['position_integrity_pair'])

    def test_zero_category_does_not_mean_zero_meters(self):
        for version in (1,2):
            v=integrity(version,18)
            self.assertEqual(v['nic_category'],0)
            self.assertEqual(v['status'],'not_available')
            self.assertNotIn('containment_radius_bound_m',v)
        rows=[record(status_frame(),0.),record(position_frame(odd=True,type_code=18),1.),record(position_frame(),2.)]
        p=enrich_adsb_frames(rows)[-1]['fields']['position_integrity_pair']
        self.assertEqual(p['nic_category'],0)
        self.assertEqual(p['status'],'not_available')
        self.assertNotIn('containment_radius_bound_m',p)

    def test_each_half_keeps_own_version(self):
        rows=[record(status_frame(version=1,supplement=1),0.),record(position_frame(odd=True),1.),
              record(status_frame(),2.),record(position_frame(),3.)]
        p=enrich_adsb_frames(rows)[-1]['fields']['position_integrity_pair']
        self.assertEqual(p['members']['odd']['adsb_version'],1)
        self.assertEqual(p['members']['odd']['nic_category'],9)
        self.assertEqual(p['members']['even']['adsb_version'],2)
        self.assertEqual(p['members']['even']['nic_category'],8)
        self.assertEqual(p['nic_category'],8)

    def test_expired_context_and_unsupported_formats(self):
        rows=[record(status_frame(),0.),record(position_frame(odd=True),11.),record(position_frame(),12.)]
        p=enrich_adsb_frames(rows)[-1]['fields']
        self.assertIn('latitude_deg',p)
        self.assertEqual(p['position_integrity']['status'],'operational_context_required')
        self.assertEqual(p['position_integrity_pair']['status'],'incomplete_or_uninterpreted_member')
        for tc in (5,20,21,22):
            p=enrich_adsb_frames([record(status_frame(),0.),record(position_frame(type_code=tc),1.)])[-1]['fields']
            self.assertNotIn('position_integrity',p)

    def test_immutability_idempotence_and_independent_members(self):
        rows=[record(status_frame(),0.),record(position_frame(odd=True),1.),record(position_frame(),2.)]
        original=deepcopy(rows); result=enrich_adsb_frames(rows)
        self.assertEqual(rows,original)
        self.assertEqual(enrich_adsb_frames(result),result)
        json.dumps(result,allow_nan=False)
        result[-1]['fields']['position_integrity_pair']['members']['odd']['operational_context']['status_time_seconds']=999
        self.assertEqual(result[1]['fields']['position_integrity']['operational_context']['status_time_seconds'],0.)

    def test_ppm_receiver_to_pair_integrity(self):
        result=decode_adsb(reference_integrity_iq(),2_000_000)
        self.assertEqual(len(result['frames']),5)
        p=result['frames'][3]['fields']
        self.assertAlmostEqual(p['latitude_deg'],52.2572021484375)
        self.assertEqual(p['position_integrity']['nic_category'],9)
        self.assertEqual(p['position_integrity_pair']['nic_category'],8)
        self.assertAlmostEqual(p['position_integrity_pair']['containment_radius_bound_m'],.1*1852)
        self.assertTrue(all(f['evidence'][0]['result']=='pass' for f in result['frames']))

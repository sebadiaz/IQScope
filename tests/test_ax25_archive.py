import base64
from copy import deepcopy
import json
import unittest

from iqscope_web.ax25_archive import MAX_ARCHIVE_BYTES,open_ax25_archive
from iqscope_web.live_ax25_history import LiveAX25History
from test_ax25 import frame
from test_kiss import read_kiss


def saved_history(packets=None):
    history=LiveAX25History('saved-session')
    frames=[dict(hex=p.hex(),fcs_valid=True,frontend='fm_iq_afsk1200',time_seconds=.1+i*.5,
                 time_end_seconds=.4+i*.5,channel={'offset_hz':32000})
            for i,p in enumerate([frame()] if packets is None else packets)]
    history.observe('saved-session',frames,48000,145000000,0,192000)
    return history.snapshot()


def reopen(history):
    return open_ax25_archive(json.dumps(history,ensure_ascii=False).encode('utf-8'))


class AX25ArchiveTests(unittest.TestCase):
    def test_reopens_own_export_and_preserves_kiss_order_and_escaping(self):
        packets=[frame(b'>caf\xc3\xa9'),frame(bytes.fromhex('c0dbdcdd'))]
        original=saved_history(packets)
        result=reopen(original)
        self.assertEqual(result['source_kind'],'ax25_history_archive')
        self.assertEqual([e['hex'] for e in result['history']['events']],[p.hex() for p in reversed(packets)])
        self.assertEqual(read_kiss(base64.b64decode(result['kiss_base64'])),[(0,0,p[:-2]) for p in packets])
        self.assertEqual(reopen(result['history'])['history'],result['history'])
        tied=deepcopy(original)
        for key in ('sample_index_estimate','end_sample_index_estimate','minimum_observed_sample_index','maximum_observed_sample_index'):
            tied['events'][1][key]=tied['events'][0][key]
        # Equal declared positions preserve archive order rather than reversing
        # simultaneous observations from distinct channels/frames.
        self.assertEqual(read_kiss(base64.b64decode(reopen(tied)['kiss_base64'])),
                         [(0,0,p[:-2]) for p in reversed(packets)])

    def test_rebuilds_fields_and_coordinates_instead_of_trusting_derived_values(self):
        original=saved_history()
        event=original['events'][0]
        event.update(fields={'text':'forged text','aprs':{'latitude_deg':90}},fcs_valid=False,
                     frequency_hz=1,time_seconds_estimate=-100,rf_center_known=False)
        loaded=reopen(original)['history']['events'][0]
        self.assertEqual(loaded['fields']['text'],'CQ IQSCOPE')
        self.assertNotIn('aprs',loaded['fields'])
        self.assertTrue(loaded['fcs_valid'])
        self.assertEqual(loaded['frequency_hz'],145032000)
        self.assertEqual(loaded['time_seconds_estimate'],.1)
        self.assertTrue(loaded['rf_center_known'])

    def test_rejects_a_changed_frame_despite_claimed_valid_fcs(self):
        archive=saved_history()
        archive['events'][0]['hex']=frame(bad=True).hex()
        with self.assertRaisesRegex(ValueError,'invalid FCS'):
            reopen(archive)

    def test_connected_mode_ambiguity_remains_unselected(self):
        packet=bytes.fromhex('9664b2b28840f49c64a4a2404072ae6496a0a240e546f046460de132')
        loaded=reopen(saved_history([packet]))['history']['events'][0]
        self.assertIsNone(loaded['fields']['pid'])
        self.assertEqual(loaded['fields']['payload_hex'],'')
        self.assertEqual([c['mode'] for c in loaded['fields']['control_candidates']],['modulo_8','modulo_128'])
        self.assertNotIn('text',loaded['fields'])

    def test_empty_history_and_unknown_rf_center_are_supported(self):
        archive=saved_history([])
        self.assertEqual(reopen(archive)['history']['events'],[])
        self.assertEqual(reopen(archive)['kiss_base64'],'')
        archive=saved_history();archive['events'][0]['center_frequency_hz']=0
        loaded=reopen(archive)['history']['events'][0]
        self.assertFalse(loaded['rf_center_known'])
        self.assertEqual(loaded['frequency_hz'],32000)

    def test_rejects_wrong_formats_budget_excess_and_duplicate_identifiers(self):
        original=saved_history()
        for key,value in [('schema_version','9'),('family','LoRa'),('time_reference','UTC'),
                          ('position_kind','unknown'),('capacity',129)]:
            archive=deepcopy(original);archive[key]=value
            with self.assertRaises(ValueError):reopen(archive)
        archive=deepcopy(original);archive['events']*=2
        with self.assertRaisesRegex(ValueError,'duplicate'):reopen(archive)
        for data in (b'x'*(MAX_ARCHIVE_BYTES+1),b'{',b'[]',b'\xff',b'['*1500+b']'*1500):
            with self.assertRaises(ValueError):open_ax25_archive(data)
        with self.assertRaises(ValueError):
            open_ax25_archive(b'{"huge":'+b'9'*1000+b'}')

    def test_rejects_invalid_declared_metadata(self):
        original=saved_history()
        for key,value in [('sample_rate',float('nan')),('sample_rate',True),('sample_rate',0),
                          ('center_frequency_hz',float('inf')),('channel_offset_hz',float('nan')),
                          ('observation_count',0),('sample_index_estimate',-1),
                          ('end_sample_index_estimate',0),('maximum_observed_sample_index',999999)]:
            archive=deepcopy(original);archive['events'][0][key]=value
            with self.assertRaises(ValueError):reopen(archive)

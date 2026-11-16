from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np

from iqscope_scan import scan_file
from iqscope_scan_events import ScanEventCatalogue
from iqscope_lora_payload import decode_payload
from test_ax25 import frame,with_fcs
from test_lora_payload import HELLO
from test_scan import lightweight_analyzer


def ax25(time=.2,packet=None,offset=2000):
    return dict(hex=(frame() if packet is None else packet).hex(),fcs_valid=True,frontend='fm_iq_afsk1200',
                time_seconds=time,time_end_seconds=time+.1,channel=dict(offset_hz=offset))


def report(frames,decoder='afsk1200_fm_ax25',start=0,end=24000):
    return dict(source_window=dict(start_sample=start,end_sample=end),
                wideband_trials=[dict(decoder=decoder,frames=frames)])


class ScanEventTests(unittest.TestCase):
    def test_overlap_groups_estimates_retains_provenance_and_exports_exact_bytes(self):
        catalogue=ScanEventCatalogue(24000,145000000)
        original=report([ax25(.4)]);saved=deepcopy(original)
        catalogue.observe(original,1,'window-001')
        catalogue.observe(report([ax25(.2,offset=2100)],start=4800,end=28800),2,'window-002')
        self.assertEqual(original,saved)
        result=catalogue.snapshot();event=result['events'][0]
        self.assertEqual((result['event_count'],result['accepted_observations'],result['merged_observations']),(1,2,1))
        self.assertEqual(event['source_sample_estimate'],9600)
        self.assertEqual([o['window_index'] for o in event['observations']],[1,2])
        self.assertEqual(event['observations'][1]['report_artifact'],'window-002/report.json')
        self.assertEqual(event['byte_scope'],'full_frame_with_fcs')
        with tempfile.TemporaryDirectory() as directory:
            catalogue.write(directory,result)
            self.assertEqual((Path(directory)/event['binary_artifact']).read_bytes(),frame())
            self.assertEqual(json.loads((Path(directory)/'scan-events.json').read_text()),result)

    def test_identical_retransmissions_channels_and_frontends_stay_separate(self):
        catalogue=ScanEventCatalogue(24000,0)
        other=ax25(.2);other['frontend']='different_frontend'
        catalogue.observe(report([ax25(.2),ax25(.6),ax25(.2,offset=4000),other]),1,'window-001')
        self.assertEqual(catalogue.snapshot()['event_count'],4)
        self.assertTrue(all(not e['rf_center_known'] for e in catalogue.snapshot()['events']))

    def test_matching_stays_anchored_without_cumulative_drift(self):
        catalogue=ScanEventCatalogue(24000,0)
        catalogue.observe(report([ax25(.2),ax25(.2015),ax25(.203)]),1,'window-001')
        events=catalogue.snapshot()['events']
        self.assertEqual([e['observation_count'] for e in events],[2,1])
        self.assertEqual(events[0]['matching_tolerance_samples'],40)

    def test_bad_crc_layout_claims_and_nonfinite_or_outside_times_are_rejected(self):
        catalogue=ScanEventCatalogue(24000,0)
        invalid=[ax25(packet=frame(bad=True)),ax25(packet=with_fcs(b'\x01'+frame()[:-2][1:])),
                 ax25(-.2),ax25(.95),ax25(float('nan'))]
        unclaimed=ax25();unclaimed['fcs_valid']=False;invalid.append(unclaimed)
        missing=ax25();del missing['time_end_seconds'];invalid.append(missing)
        catalogue.observe(report(invalid),1,'window-001')
        result=catalogue.snapshot()
        self.assertEqual(result['rejected_observations'],7)
        self.assertEqual(result['events'],[])

    def test_connected_mode_fields_are_reparsed_and_application_stays_unselected(self):
        packet=bytes.fromhex('9664b2b28840f49c64a4a2404072ae6496a0a240e546f046460de132')
        incoming=ax25(packet=packet);incoming['fields']={'text':'forged derived content'}
        catalogue=ScanEventCatalogue(24000,0);catalogue.observe(report([incoming]),1,'window-001')
        event=catalogue.snapshot()['events'][0]
        self.assertEqual(event['hex'],packet.hex())
        self.assertEqual(event['fields']['frame_type'],'I')
        self.assertIsNone(event['fields']['pid']);self.assertEqual(event['fields']['payload_hex'],'')
        self.assertEqual(len(event['fields']['control_candidates']),2)
        self.assertNotIn('text',event['fields'])

    def test_adsb_crc_format_and_source_index_are_rechecked(self):
        packet='8D40621D58C382D690C8AC2863A7'
        valid=dict(hex=packet,time_seconds=.1,sample_start=200000)
        corrupted=dict(valid,hex=packet[:-1]+'6')
        wrong_time=dict(valid,sample_start=199999)
        catalogue=ScanEventCatalogue(2000000,1090000000)
        catalogue.observe(report([valid,corrupted,wrong_time],decoder='adsb_1090es',end=2000000),1,'window-001')
        catalogue.observe(report([dict(valid,time_seconds=.05,sample_start=100000)],decoder='adsb_1090es',
                                 start=100000,end=2100000),2,'window-002')
        result=catalogue.snapshot();event=result['events'][0]
        self.assertEqual(result['event_count'],1);self.assertEqual(result['rejected_observations'],2)
        self.assertEqual(event['observation_count'],2)
        self.assertEqual(event['fields']['address_hex'],'40621D')
        self.assertEqual(event['byte_scope'],'full_frame_with_crc')

    def test_lora_payload_crc_parameters_and_byte_scope_are_preserved(self):
        valid=decode_payload(HELLO[8],8)
        valid.update(time_seconds=.1,parameters=dict(spreading_factor=8,bandwidth_hz=125000,chirp_polarity=1),sync_word='12',
                     experimental_mode=True,quarter_chirp_validated=False,corrected_payload_codeword_bits=1)
        bad=deepcopy(valid);bad['payload_hex']='00454c4c4f'
        unclaimed=deepcopy(valid);unclaimed['status']='payload_without_crc'
        other=deepcopy(valid);other['parameters']['chirp_polarity']=-1
        catalogue=ScanEventCatalogue(250000,0)
        catalogue.observe(report([valid,bad,unclaimed,other],decoder='lora_preamble',end=250000),1,'window-001')
        catalogue.observe(report([dict(valid,time_seconds=.05)],decoder='lora_preamble',start=12500,end=262500),2,'window-002')
        result=catalogue.snapshot()
        self.assertEqual(result['event_count'],2);self.assertEqual(result['rejected_observations'],2)
        self.assertEqual(result['events'][0]['observation_count'],2)
        self.assertEqual(result['events'][0]['byte_scope'],'payload_without_phy_crc')
        self.assertEqual(result['events'][0]['integrity']['received_crc'],0x8332)
        self.assertEqual(result['events'][0]['experimental_observations'],2)
        self.assertEqual(result['events'][0]['inferred_boundary_observations'],2)
        self.assertEqual(result['events'][0]['observations'][0]['decoder_evidence']['corrected_payload_codeword_bits'],1)
        self.assertEqual(bytes.fromhex(result['events'][0]['hex']),b'HELLO')

    def test_catalogue_reference_and_per_window_limits_are_explicit(self):
        catalogue=ScanEventCatalogue(24000,0,capacity=1,reference_capacity=1,window_budget=3)
        catalogue.observe(report([ax25(.2),ax25(.2),ax25(.6),ax25(.8)]),1,'window-001')
        result=catalogue.snapshot()
        self.assertEqual(result['event_count'],1);self.assertEqual(result['accepted_observations'],2)
        self.assertEqual(result['deferred_observations'],2);self.assertEqual(result['deferred_references'],1)
        self.assertEqual(result['events'][0]['observation_count'],2)
        self.assertEqual(len(result['events'][0]['observations']),1)
        for kwargs in [dict(capacity=0),dict(capacity=129),dict(reference_capacity=33),dict(window_budget=True)]:
            with self.assertRaises(ValueError):ScanEventCatalogue(24000,0,**kwargs)

    def test_interpretation_warnings_and_snapshots_do_not_upgrade_source_evidence(self):
        catalogue=ScanEventCatalogue(24000,0)
        incoming=report([ax25()]);incoming['interpretation_status']='unverified_byte_order_and_header_layout'
        catalogue.observe(incoming,1,'window-001');result=catalogue.snapshot()
        event=result['events'][0]
        self.assertEqual(event['input_interpretation_status'],incoming['interpretation_status'])
        self.assertEqual(event['observations'][0]['input_interpretation_status'],incoming['interpretation_status'])
        event['fields']['source']['callsign']='MUTATED'
        self.assertNotEqual(catalogue.snapshot()['events'][0]['fields']['source']['callsign'],'MUTATED')

    def test_partial_scan_catalogue_survives_cancellation_and_later_decoder_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.cf32';np.zeros(12000,dtype='<c8').tofile(source)
            stop=threading.Event()
            def analyzer(*args,**kwargs):
                if kwargs['start_sample']>=4800:raise ValueError('later test failure')
                output=lightweight_analyzer(*args,**kwargs)
                observed=ax25((3000-kwargs['start_sample'])/24000)
                observed['time_end_seconds']=observed['time_seconds']+.02
                output['wideband_trials'][0]['frames']=[observed]
                return output
            def progress(value):
                if value['completed_windows']==2:stop.set()
            cancelled=scan_file(source,root/'cancelled',24000,seconds=.2,cancel_event=stop,on_progress=progress,analyzer=analyzer)
            failed=scan_file(source,root/'failed',24000,seconds=.2,analyzer=analyzer)
            for result,folder,status in [(cancelled,'cancelled','cancelled'),(failed,'failed','failed_window')]:
                self.assertEqual(result['status'],status)
                event=result['event_catalogue']['events'][0]
                self.assertEqual(event['source_sample_estimate'],3000)
                self.assertEqual(event['observation_count'],2)
                self.assertEqual(json.loads((root/folder/'scan-events.json').read_text()),result['event_catalogue'])
                self.assertEqual((root/folder/event['binary_artifact']).read_bytes(),frame())

    def test_actual_adsb_and_lora_iq_pipelines_enter_the_catalogue(self):
        from test_adsb_fields import reference_aircraft_iq
        from test_lora import synchronized_preamble
        lora,rate=synchronized_preamble(sf=8,offset=0,cfo_bins=0,data_symbols=HELLO[8])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,x,fs,count in [('adsb',reference_aircraft_iq(),2000000,3),('lora',lora,rate,1)]:
                with self.subTest(family=name):
                    source=root/(name+'.cf32');x.astype('<c8').tofile(source)
                    result=scan_file(source,root/name,fs,seconds=1,max_windows=1)
                    catalogue=result['event_catalogue']
                    self.assertEqual(catalogue['event_count'],count)
                    self.assertEqual(catalogue['rejected_observations'],0)
                    for event in catalogue['events']:
                        self.assertEqual((root/name/event['binary_artifact']).read_bytes(),bytes.fromhex(event['hex']))

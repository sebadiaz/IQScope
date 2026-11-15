import unittest

from iqscope_web.live_ax25_history import LiveAX25History
from test_ax25 import frame, with_fcs
from test_kiss import read_kiss


def received(time=.1, packet=None, offset=32000):
    return dict(hex=(frame() if packet is None else packet).hex(),fcs_valid=True,
                frontend='fm_iq_afsk1200',time_seconds=time,time_end_seconds=time+.3,
                channel=dict(offset_hz=offset))


def observe(history, frames, start=0, end=20000, session='a', fs=10000, center=145000000):
    return history.observe(session,frames,fs,center,start,end)


class LiveAX25HistoryTests(unittest.TestCase):
    def test_overlapping_windows_merge_same_event_and_export_original_bytes(self):
        history=LiveAX25History('a')
        first=received(1);second=received(.5,offset=32100)
        observe(history,[first])
        result=observe(history,[second],start=5000,end=25000)
        self.assertEqual(result['merged_observations'],1)
        event=history.snapshot()['events'][0]
        self.assertEqual(first['live_event_id'],second['live_event_id'])
        self.assertEqual(event['observation_count'],2)
        self.assertEqual(event['sample_index_estimate'],10000)
        self.assertEqual(read_kiss(history.kiss()),[(0,0,frame()[:-2])])
        self.assertNotIn('wire_artifact',event)

    def test_identical_retransmissions_and_distinct_channels_stay_separate(self):
        history=LiveAX25History('a')
        observe(history,[received(.1),received(.5),received(.1,offset=34000)])
        self.assertEqual(len(history.snapshot()['events']),3)
        self.assertEqual(len(read_kiss(history.kiss())),3)

    def test_first_observation_bounds_matching_without_cumulative_drift(self):
        history=LiveAX25History('a')
        # Two nominal symbols at 10 kS/s round to 17 samples. Each comparison
        # stays anchored to the first retained estimate, not to the latest one.
        observe(history,[received(.1),received(.1016),received(.1032)])
        events=history.snapshot()['events']
        self.assertEqual(len(events),2)
        first=next(e for e in events if e['sample_index_estimate']==1000)
        self.assertEqual(first['observation_count'],2)

    def test_invalid_fcs_layout_frontend_and_capture_bounds_are_rejected(self):
        history=LiveAX25History('a')
        wrong=received(packet=frame(bad=True))
        bad_layout=received(packet=with_fcs(b'\x01'+frame()[:-2][1:]))
        outside=received(1.9)
        wrong_frontend=received();wrong_frontend['frontend']='audio_afsk1200'
        nonfinite=received(float('nan'))
        missing=received();del missing['time_end_seconds']
        unclaimed=received();unclaimed['fcs_valid']=False
        result=observe(history,[wrong,bad_layout,outside,wrong_frontend,nonfinite,missing,unclaimed])
        self.assertEqual(result['skipped_frames'],7)
        self.assertEqual(history.snapshot()['events'],[])
        self.assertEqual(history.kiss(),b'')

    def test_connected_frames_keep_their_unselected_application_interpretations(self):
        history=LiveAX25History('a')
        packets=[bytes.fromhex(h) for h in (
            '9664b2b28840f49c64a4a2404072ae6496a0a240e546f046460de132',
            '9c64a4a2404072ae6496a0a240e1b1373c')]
        frames=[received(.1+i*.5,packet=p) for i,p in enumerate(packets)]
        frames[0]['fields']={'text':'not derived from the received bytes'}
        observe(history,frames)
        events=history.snapshot()['events']
        info=next(e for e in events if e['fields']['frame_type']=='I')
        self.assertEqual([c['mode'] for c in info['fields']['control_candidates']],['modulo_8','modulo_128'])
        self.assertIsNone(info['fields']['pid'])
        self.assertEqual(info['fields']['payload_hex'],'')
        self.assertNotIn('text',info['fields'])
        self.assertEqual(read_kiss(history.kiss()),[(0,0,p[:-2]) for p in packets])

    def test_capacity_evicts_oldest_and_snapshots_do_not_mutate_history(self):
        history=LiveAX25History('a',capacity=2)
        observe(history,[received(.9,frame(b'>late')),received(.1,frame(b'>old')),received(.5,frame(b'>middle'))])
        result=history.snapshot()
        self.assertEqual([e['sample_index_estimate'] for e in result['events']],[9000,5000])
        self.assertEqual(result['evicted_events'],1)
        result['events'][0]['fields']['source']['callsign']='MUTATE'
        self.assertEqual(history.snapshot()['events'][0]['fields']['source']['callsign'],'N0CALL')
        self.assertEqual(read_kiss(history.kiss()),[(0,0,frame(b'>middle')[:-2]),(0,0,frame(b'>late')[:-2])])

    def test_reset_rejects_a_finishing_old_session(self):
        history=LiveAX25History('a');observe(history,[received()])
        revision=history.version();history.reset('b')
        self.assertGreater(history.version(),revision)
        self.assertFalse(observe(history,[received()])['recorded'])
        self.assertEqual(history.snapshot()['events'],[])
        self.assertEqual(history.kiss(),b'')
        self.assertEqual(observe(history,[received()],session='b')['new_event_estimates'],1)

    def test_source_metadata_and_per_observation_budget_are_bounded(self):
        history=LiveAX25History('a')
        for args in ((0,0,100),(float('nan'),0,100),(10000,-1,100),(10000,0,1.5)):
            fs,start,end=args
            with self.assertRaises(ValueError):
                observe(history,[],fs=fs,start=start,end=end)
        frames=[received(.1+i*.4) for i in range(130)]
        result=observe(history,frames,end=600000)
        self.assertEqual(result['deferred_frames'],2)
        self.assertEqual(result['retained_events'],128)

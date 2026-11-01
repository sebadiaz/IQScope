import unittest
from iqscope_web.live_history import LiveLoRaHistory


def frame(time=.1,payload='48454c4c4f'):
    return {'status':'payload_crc_valid','payload_hex':payload,'text':'HELLO','time_seconds':time,
            'coding_rate':'4/5','quarter_chirp_validated':False,
            'parameters':{'spreading_factor':7,'bandwidth_hz':125000,'symbol_seconds':.001024,'chirp_polarity':1}}


class LiveHistoryTests(unittest.TestCase):
    def test_overlapping_windows_and_modes_merge_one_event(self):
        h=LiveLoRaHistory('a')
        first=frame(.1);second=frame(.05)
        h.observe('a',[first],250000,0,50000,'standard')
        result=h.observe('a',[second],250000,12500,62500,'experimental_guarded')
        self.assertEqual(result['merged_observations'],1)
        e=h.snapshot()['events'][0]
        self.assertEqual(e['observation_count'],2)
        self.assertEqual(e['modes'],['standard','experimental_guarded'])
        self.assertEqual(first['live_event_id'],second['live_event_id'])
        self.assertEqual(e['sample_index_estimate'],25000)

    def test_same_bytes_at_distinct_times_are_not_collapsed(self):
        h=LiveLoRaHistory('a')
        h.observe('a',[frame(.1),frame(.2)],250000,0,100000,'standard')
        self.assertEqual(len(h.snapshot()['events']),2)

    def test_rejected_crc_and_outside_window_do_not_enter_history(self):
        h=LiveLoRaHistory('a');bad=frame();bad['status']='payload_crc_mismatch'
        r=h.observe('a',[bad,frame(.5)],250000,0,50000,'standard')
        self.assertEqual(r['skipped_frames'],2)
        self.assertEqual(h.snapshot()['events'],[])

    def test_reset_ignores_a_finishing_old_session(self):
        h=LiveLoRaHistory('a');h.observe('a',[frame()],250000,0,50000,'standard')
        h.reset('b')
        r=h.observe('a',[frame()],250000,0,50000,'standard')
        self.assertFalse(r['recorded'])
        self.assertEqual(h.snapshot()['events'],[])
        h.observe('b',[frame()],250000,0,50000,'standard')
        self.assertEqual(len(h.snapshot()['events']),1)

    def test_capacity_discards_oldest_and_response_is_independent(self):
        h=LiveLoRaHistory('a',capacity=2)
        h.observe('a',[frame(.3),frame(.1),frame(.2)],250000,0,100000,'standard')
        result=h.snapshot()
        self.assertEqual([e['sample_index_estimate'] for e in result['events']],[75000,50000])
        self.assertEqual(result['evicted_events'],1)
        result['events'][0]['parameters']['spreading_factor']=12
        self.assertEqual(h.snapshot()['events'][0]['parameters']['spreading_factor'],7)

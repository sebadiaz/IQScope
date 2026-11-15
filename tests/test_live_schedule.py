import unittest

from iqscope_web.live import live_analysis_schedule


def state(fs=256000, total=None, buffered=None, session='a', connected=True):
    limit=min(4*fs,8000000)
    return dict(sample_rate=fs,window_sample_limit=limit,received_samples=limit if total is None else total,
                buffered_samples=limit if buffered is None else buffered,session_id=session,connected=connected)


def cursor(end=1024000, session='a', mode=False, fs=256000):
    return dict(end_sample=end,session_id=session,experimental_lora=mode,sample_rate=fs)


class LiveScheduleTests(unittest.TestCase):
    def test_half_window_step_at_all_rates_respects_sample_cap(self):
        for fs in (256000,1024000,2048000,2400000):
            s=state(fs);p=cursor(end=s['received_samples'],fs=fs)
            policy=live_analysis_schedule(s,p)
            self.assertEqual(policy['step_samples'],min(4*fs,8000000)//2)
            self.assertEqual(policy['target_overlap_samples'],policy['step_samples'])
            self.assertAlmostEqual(policy['step_seconds'],min(2,4000000/fs))
            self.assertFalse(policy['due'])

    def test_exact_sample_threshold_and_unchanged_window(self):
        previous=cursor()
        for advance in (0,1,511999,512000,512001):
            policy=live_analysis_schedule(state(total=1024000+advance),previous)
            self.assertEqual(policy['due'],advance>=512000)
            self.assertEqual(policy['next_end_sample'],1536000)

    def test_mode_change_rechecks_same_samples_then_waits(self):
        self.assertTrue(live_analysis_schedule(state(),cursor(),True)['due'])
        policy=live_analysis_schedule(state(),cursor(mode=True),True)
        self.assertFalse(policy['due'])
        self.assertEqual(policy['reason'],'waiting_for_samples')
        self.assertTrue(live_analysis_schedule(state(),cursor(mode=True),False)['due'])

    def test_session_and_rate_changes_do_not_reuse_an_old_cursor(self):
        for previous in (cursor(session='old'),cursor(fs=1024000)):
            policy=live_analysis_schedule(state(),previous)
            self.assertTrue(policy['due'])
            self.assertEqual(policy['reason'],'first_window')

    def test_initial_fill_and_disconnected_receiver_never_trigger(self):
        for count in (0,1024,63999,64000):
            policy=live_analysis_schedule(state(total=count,buffered=count))
            self.assertEqual(policy['due'],count>=64000)
        self.assertFalse(live_analysis_schedule(state(connected=False))['due'])

    def test_counter_behind_cursor_does_not_cause_repeated_analyses(self):
        policy=live_analysis_schedule(state(total=500000),cursor())
        self.assertFalse(policy['due'])
        self.assertEqual(policy['reason'],'waiting_for_samples')

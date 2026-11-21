import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from iqscope_iq_windows import read_iq_window
from iqscope_scan import plan_windows,scan_file


def lightweight_analyzer(path,out,sample_rate=None,seconds=10,start_sample=0,experimental_lora=False):
    x,fs,center,window=read_iq_window(path,sample_rate,seconds,start_sample=start_sample)
    report=dict(sample_rate=fs,center_frequency_hz=center,source_window=window,signals=[],
                wideband_trials=[dict(decoder='afsk1200_fm_ax25',frames=[],budget_exhausted=True)])
    out=Path(out);out.mkdir(parents=True)
    (out/'report.json').write_text(json.dumps(report))
    return report


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'source.cf32';np.zeros(12000,dtype='<c8').tofile(self.path)

    def tearDown(self):self.temp.cleanup()

    def test_planner_has_overlap_and_covers_a_subminimum_final_tail(self):
        self.assertEqual(plan_windows(12000,0,4000,8),[(0,4000),(2000,6000),(4000,8000),(6000,10000),(8000,12000)])
        self.assertEqual(plan_windows(1025,0,1024,8),[(0,1024),(1,1025)])
        for args in [(1000,0,1024,8),(10000,-1,2000,8),(10000,0,1000,8),
                     (10000,0,8000001,8),(10000,0,2000,0),(10000,0,2000,33),(10000,0,2000,True)]:
            with self.assertRaises(ValueError):plan_windows(*args)

    def test_window_budget_checkpoint_and_resume_do_not_claim_whole_file(self):
        first=scan_file(self.path,self.root/'first',24000,seconds=.1,max_windows=2,analyzer=lightweight_analyzer)
        self.assertEqual(first['status'],'window_budget_exhausted')
        self.assertEqual(first['coverage']['end_sample'],3600)
        self.assertEqual(first['next_start_sample'],2400)
        self.assertFalse(first['coverage']['whole_file_read'])
        self.assertTrue(first['windows'][0]['decoder_limits'][0]['budget_exhausted'])
        resumed=scan_file(self.path,self.root/'resumed',24000,seconds=.1,start_sample=first['next_start_sample'],max_windows=16,analyzer=lightweight_analyzer)
        self.assertEqual(resumed['status'],'source_end_reached')
        self.assertEqual(resumed['coverage']['unvisited_prefix_samples'],2400)
        self.assertTrue(resumed['coverage']['from_requested_start_read_to_end'])
        self.assertFalse(resumed['coverage']['whole_file_read'])
        self.assertIsNone(resumed['next_start_sample'])

    def test_cancellation_preserves_completed_window_and_exact_resume_position(self):
        stop=threading.Event()
        def progress(value):
            if value['completed_windows']==1:stop.set()
        result=scan_file(self.path,self.root/'cancelled',24000,seconds=.1,cancel_event=stop,on_progress=progress,analyzer=lightweight_analyzer)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(len(result['windows']),1)
        self.assertEqual(result['next_start_sample'],1200)
        self.assertEqual(json.loads((self.root/'cancelled/scan-report.json').read_text()),result)
        self.assertTrue((self.root/'cancelled'/result['windows'][0]['report_artifact']).is_file())

    def test_cancel_before_first_window_has_zero_read_coverage(self):
        stop=threading.Event();stop.set()
        result=scan_file(self.path,self.root/'empty',24000,seconds=.1,cancel_event=stop,analyzer=lightweight_analyzer)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['coverage']['read_samples'],0)
        self.assertEqual(result['next_start_sample'],0)

    def test_decoder_failure_and_source_change_preserve_previous_checkpoint(self):
        calls=[]
        def fail(*args,**kwargs):
            if calls:raise ValueError('test source failure')
            calls.append(1);return lightweight_analyzer(*args,**kwargs)
        result=scan_file(self.path,self.root/'failed',24000,seconds=.1,analyzer=fail)
        self.assertEqual(result['status'],'failed_window')
        self.assertEqual(result['error'],'test source failure')
        self.assertEqual(result['next_start_sample'],1200)
        self.assertEqual(result['coverage']['end_sample'],2400)
        def changed(*args,**kwargs):
            report=lightweight_analyzer(*args,**kwargs);report['sample_rate']=48000;return report
        result=scan_file(self.path,self.root/'changed',24000,seconds=.1,analyzer=changed)
        self.assertEqual(result['status'],'failed_window')
        self.assertEqual(result['coverage']['read_samples'],0)

    def test_actual_standard_decoder_pipeline_and_output_isolation(self):
        out=self.root/'actual'
        result=scan_file(self.path,out,24000,seconds=.1,max_windows=2)
        self.assertEqual(result['status'],'window_budget_exhausted')
        for record in result['windows']:
            report=json.loads((out/record['report_artifact']).read_text())
            self.assertEqual(report['source_sample_start'],record['start_sample'])
            self.assertEqual(len(report['wideband_trials']),19)
        with self.assertRaisesRegex(ValueError,'empty'):scan_file(self.path,out,24000,seconds=.1)

    def test_cli_emits_a_resumable_scan_report(self):
        from iqscope import main
        capture=io.StringIO();out=self.root/'cli'
        with patch('sys.argv',['iqscope','scan',str(self.path),'--sample-rate','24000','--seconds','.1',
                               '--start-seconds','.1','--max-windows','1','--out',str(out)]),patch('sys.stdout',capture):
            main()
        result=json.loads(capture.getvalue())
        self.assertEqual(result['status'],'window_budget_exhausted')
        self.assertEqual(result['start_sample'],2400)
        self.assertEqual(result['next_start_sample'],3600)
        self.assertEqual(json.loads((out/'scan-report.json').read_text()),result)
        capture=io.StringIO()
        with patch('sys.argv',['iqscope','scan',str(self.path),'--sample-rate','24000','--seconds','.1',
                               '--start-sample',str(result['next_start_sample']),'--max-windows','1',
                               '--out',str(self.root/'cli-resumed')]),patch('sys.stdout',capture):
            main()
        self.assertEqual(json.loads(capture.getvalue())['start_sample'],3600)

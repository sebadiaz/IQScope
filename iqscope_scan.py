"""Bounded automatic IQ file traversal; each decoder window stays independent."""
import json
import math
import os
from pathlib import Path

from iqscope_formats import MAX_SAMPLES
from iqscope_iq_windows import iq_source_info


def plan_windows(total, start, width, limit):
    if (any(type(v) is not int for v in (total,start,width,limit)) or start<0
            or total-start<1024 or not 1024<=width<=MAX_SAMPLES or not 1<=limit<=32):
        raise ValueError('Invalid bounded scan window plan')
    result=[];position=start
    for _ in range(limit+1):
        end=min(total,position+width)
        result.append((position,end))
        if end==total:break
        position=min(position+width//2,total-1024)
    return result


def scan_file(path,out,sample_rate=None,seconds=10,start_seconds=0,start_sample=None,
              max_windows=8,experimental_lora=False,cancel_event=None,on_progress=None,analyzer=None):
    if analyzer is None:
        from iqscope import analyze
        analyzer=analyze
    info=iq_source_info(path,sample_rate);fs=info['sample_rate'];total=info['total_samples']
    if not math.isfinite(seconds) or not 0<seconds<=120:
        raise ValueError('Scan window duration must be finite and at most 120 seconds')
    if not math.isfinite(start_seconds) or start_seconds<0 or not math.isfinite(start_seconds*fs):
        raise ValueError('Invalid scan start time')
    if start_sample is not None:
        if type(start_sample) is not int or start_sample<0 or start_seconds!=0:
            raise ValueError('Choose a start time or a nonnegative integer start sample')
        start=start_sample
    else:start=math.floor(start_seconds*fs)
    width=MAX_SAMPLES if fs*seconds>=MAX_SAMPLES else int(fs*seconds)
    plan=plan_windows(total,start,width,max_windows)
    out=Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Choose an empty scan output directory')
    out.mkdir(parents=True,exist_ok=True)
    result=dict(schema_version='0.1',source_kind='iq_file_scan',source=str(path),
        sample_rate=fs,center_frequency_hz=info['center_frequency_hz'],total_samples=total,
        start_sample=start,window_sample_limit=width,step_samples=width//2,
        requested_window_seconds=seconds,window_budget=max_windows,windows=[],
        status='running',next_start_sample=start,
        limitations=['IQ read coverage only; each decoder has its own duration, candidate and frame budgets.',
                     'Overlapping windows can repeat packet observations; counts are not unique packets.',
                     'No cross-window DSP, connection state or application reassembly.'])

    def checkpoint():
        end=result['windows'][-1]['end_sample'] if result['windows'] else start
        result['coverage']=dict(start_sample=start,end_sample=end,read_samples=end-start,
            unvisited_prefix_samples=start,unvisited_tail_samples=total-end,
            whole_file_read=start==0 and end==total,from_requested_start_read_to_end=end==total)
        pending=out/'scan-report.json.tmp'
        pending.write_text(json.dumps(result,indent=2))
        os.replace(pending,out/'scan-report.json')
        if on_progress:on_progress(dict(completed_windows=len(result['windows']),window_budget=max_windows,
                                       read_through_sample=end,read_through_seconds=end/fs,status=result['status']))

    checkpoint()
    for index,(position,end) in enumerate(plan[:max_windows],1):
        if cancel_event is not None and cancel_event.is_set():
            result['status']='cancelled';result['next_start_sample']=position;break
        directory=f'window-{index:03d}'
        try:
            report=analyzer(path,out/directory,sample_rate=sample_rate,seconds=seconds,
                            start_sample=position,experimental_lora=experimental_lora)
            w=report['source_window']
            if (report['sample_rate']!=fs or report['center_frequency_hz']!=info['center_frequency_hz']
                    or w['total_samples']!=total or w['start_sample']!=position or w['end_sample']!=end):
                raise ValueError('Source layout changed while scanning')
        except (ValueError,OSError,KeyError) as error:
            result['status']='failed_window';result['error']=str(error)
            result['next_start_sample']=position;break
        crc_decoders={'adsb_1090es','ax25_ui','afsk1200_fm_ax25','afsk1200_ax25','lora_preamble'}
        observations=sum(len(t.get('frames',[])) for t in report['wideband_trials'] if t['decoder'] in crc_decoders)
        limits=[dict(decoder=t['decoder'],budget_exhausted=bool(t.get('budget_exhausted')),
                     duration_limited=bool(t.get('duration_limited')))
                for t in report['wideband_trials'] if t.get('budget_exhausted') or t.get('duration_limited')]
        result['windows'].append(dict(index=index,start_sample=position,end_sample=end,
            start_seconds=position/fs,end_seconds=end/fs,signal_count=len(report['signals']),
            crc_frame_observations=observations,decoder_limits=limits,
            interpretation_status=report.get('interpretation_status'),
            report_artifact=f'{directory}/report.json',artifact_prefix=directory+'/'))
        result['next_start_sample']=plan[index][0] if index<len(plan) else None
        if end==total:
            result['status']='source_end_reached';result['next_start_sample']=None;checkpoint();break
        checkpoint()
    else:result['status']='window_budget_exhausted'
    checkpoint()
    return result

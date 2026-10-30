"""Bounded, annotation-free temporal selection and merging for LoRa trials."""
import numpy as np

WINDOW_BUDGET=8
ENERGY_SAMPLE_BUDGET=262144


def select_lora_windows(x,fs):
    count=len(x)
    window_size=int(fs)
    maximum_bandwidth=max(b for b in (125000,250000,500000) if b<=fs)
    shortest_search=256*128/maximum_bandwidth
    windows=[{'start_sample':0,'end_sample':min(count,window_size),'reason':'prefix'}]
    evidence={'window_budget':WINDOW_BUDGET,'window_seconds_limit':1,
              'energy_sample_budget':ENERGY_SAMPLE_BUDGET,'energy_samples':0,
              'energy_event_count':0,'selection_uses_annotations':False}
    if count/fs<=shortest_search:
        return windows,dict(evidence,energy_status='not_needed',window_budget_reached=False)
    stride=max(1,int(np.ceil(count/ENERGY_SAMPLE_BUDGET)))
    sampled=np.asarray(x[::stride],dtype=np.complex128)
    width=max(16,int(round(.002*fs/stride)))
    blocks=len(sampled)//width
    events=[]
    evidence.update(energy_samples=len(sampled),energy_stride_samples=stride,
                    energy_block_seconds=width*stride/fs)
    if blocks>=4 and np.all(np.isfinite(sampled)):
        power=np.mean(abs(sampled[:blocks*width].reshape(blocks,width))**2,axis=1)
        median=float(np.median(power));mad=float(np.median(abs(power-median)))
        threshold=max(2*float(np.quantile(power,.2)),median+6*mad)
        mask=power>threshold
        starts=np.flatnonzero(mask & ~np.r_[False,mask[:-1]])
        for begin in starts:
            end=int(begin)+1
            while end<len(mask) and mask[end]:
                end+=1
            if end-int(begin)<2:
                continue
            onset=int(begin)*width*stride
            contrast=float(np.max(power[int(begin):end])/max(threshold,1e-30))
            events.append((contrast,onset))
        evidence.update(energy_status='profiled',energy_threshold=threshold,
                        energy_event_count=len(events))
    else:
        evidence['energy_status']='insufficient_or_nonfinite_samples'
    guard=max(1,int(.02*fs))
    omitted=False
    for contrast,onset in sorted(events,key=lambda event:(-event[0],event[1])):
        start=max(0,onset-guard)
        if any(abs(start-w['start_sample'])<guard for w in windows):
            continue
        if len(windows)==WINDOW_BUDGET:
            omitted=True
            break
        windows.append({'start_sample':start,'end_sample':min(count,start+window_size),
                        'reason':'energy_rise','onset_sample':onset,'energy_contrast':contrast})
    # Distributed probes supplement a flat or inconclusive envelope; they do not
    # imply complete coverage of every BW/SF configuration.
    for start in (count//2,max(0,count-int(shortest_search*fs))):
        if len(windows)==WINDOW_BUDGET:
            break
        if count-start<1024 or any(abs(start-w['start_sample'])<guard for w in windows):
            continue
        windows.append({'start_sample':start,'end_sample':min(count,start+window_size),
                        'reason':'distributed_probe'})
    return windows,dict(evidence,window_budget_reached=omitted)


def interval_coverage(intervals,span):
    end=0.0;covered=0.0;largest_gap=0.0
    for first,last in sorted(intervals):
        first=max(0.0,min(span,first));last=max(first,min(span,last))
        largest_gap=max(largest_gap,max(0.0,first-end))
        covered+=max(0.0,last-max(first,end))
        end=max(end,last)
    largest_gap=max(largest_gap,max(0.0,span-end))
    return covered,largest_gap


def _same_event(first,second):
    if first['parameters']!=second['parameters']:
        return False
    if abs(first['time_seconds']-second['time_seconds'])>4*first['parameters']['symbol_seconds']:
        return False
    a=first.get('payload',{}).get('payload_hex');b=second.get('payload',{}).get('payload_hex')
    return not (a is not None and b is not None and a!=b)


def scan_lora_windows(x,fs,detect_window):
    windows,selection=select_lora_windows(x,fs)
    candidates=[];searches=[];coherent=[];results=[];input_intervals=[]
    for index,window in enumerate(windows):
        start=window['start_sample'];end=window['end_sample'];offset=start/fs
        result=detect_window(x[start:end],fs)
        results.append(result)
        window.update(index=index,start_seconds=offset,end_seconds=end/fs)
        input_intervals.append((offset,end/fs))
        for candidate in result['candidates']:
            candidate['time_seconds']+=offset
            candidate.update(analysis_window_index=index,analysis_window_start_sample=start,
                             analysis_window_start_seconds=offset)
            for key,field in (('synchronization','time_seconds'),('sync_word','opposite_chirp_start_seconds'),
                              ('data_symbols','candidate_data_start_seconds')):
                if field in candidate[key]:
                    candidate[key][field]+=offset
            candidates.append(candidate)
        for search in result.get('search_windows',[]):
            searches.append(dict(search,analysis_window_index=index,start_seconds=offset,
                                 end_seconds=offset+search['examined_seconds']))
        coherent.extend(dict(search,analysis_window_index=index) for search in result.get('coherent_searches',[]))
    # Display/merge priority is independent of the phase/parameter selection
    # inside each detector trial. Preserve contradictory CRC-valid bytes.
    def rank(candidate):
        payload=candidate['payload']['status']=='payload_crc_valid'
        header=candidate['explicit_header']['status']=='header_checksum_valid'
        return (payload,header,candidate['score'])
    merged=[]
    for candidate in sorted(candidates,key=rank,reverse=True):
        if not any(_same_event(candidate,old) for old in merged):
            merged.append(candidate)
    merged.sort(key=lambda candidate:(candidate['time_seconds'],-candidate['score']))
    frames=[]
    for candidate in merged:
        payload=candidate['payload']
        if payload['status']!='payload_crc_valid':
            continue
        time=candidate['data_symbols']['candidate_data_start_seconds']
        if any(frame['payload_hex']==payload['payload_hex'] and frame['parameters']==candidate['parameters']
               and abs(frame['time_seconds']-time)<candidate['parameters']['symbol_seconds'] for frame in frames):
            continue
        frames.append(dict(payload,time_seconds=time,parameters=candidate['parameters'],
                           sync_word=candidate['sync_word'].get('value_hex'),
                           analysis_window_index=candidate['analysis_window_index']))
    frames.sort(key=lambda frame:frame['time_seconds'])
    span=len(x)/fs;coverage=[]
    configurations=sorted({(search['bandwidth_hz'],search['spreading_factor']) for search in searches})
    for bandwidth,sf in configurations:
        intervals=[(s['start_seconds'],s['end_seconds']) for s in searches
                   if s['bandwidth_hz']==bandwidth and s['spreading_factor']==sf]
        covered,gap=interval_coverage(intervals,span)
        coverage.append({'bandwidth_hz':bandwidth,'spreading_factor':sf,'searched_seconds':covered,
                         'source_fraction':min(1.0,covered/span),'maximum_unsearched_seconds':gap,
                         'coverage_complete':gap<=1/fs,'whole_preamble_gap':gap>=6*2**sf/bandwidth})
    partial=any(item['whole_preamble_gap'] for item in coverage)
    covered_input,_=interval_coverage(input_intervals,span)
    temporal=dict(selection,window_count=len(windows),windows=windows,partial=partial,
                  source_span_seconds=span,input_union_seconds=covered_input,
                  processed_input_seconds=sum(last-first for first,last in input_intervals),
                  candidate_budget=6*WINDOW_BUDGET)
    limitations=next((r['limitations'][:] for r in results if 'limitations' in r),[])
    limitations=[text for text in limitations if not text.startswith('First second only;')]
    limitations.extend(['At most eight one-second input windows selected from prefix, bounded energy profiling and distributed probes; no guarantee of complete file coverage.',
        'At most 256 symbols per BW/SF/window; coverage is reported separately per configuration. Unsearched periods can contain signals.',
        'Eight-phase local timing refinement requires SF7-10 and >=2 samples/chip; clock drift is not tracked. Chip indices remain relative to their analysis window.'])
    applicable=any(r['status']!='not_applicable' for r in results)
    return {'decoder':'lora_preamble','family':'LoRa-compatible CSS preamble',
            'status':'crc_valid_payload' if frames else ('repeated_chirp_candidate' if merged else ('no_consistent_candidate' if applicable else 'not_applicable')),
            'candidates':merged,'trials':sum(r.get('trials',0) for r in results),
            'analyzed_seconds':temporal['processed_input_seconds'],'source_span_seconds':span,
            'search_windows':searches,'search_coverage':coverage,'coherent_searches':coherent,
            'temporal_search':temporal,'sample_budget_reached':partial,'limitations':limitations,
            **({'frames':frames} if frames else {})}

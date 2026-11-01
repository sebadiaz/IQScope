"""Bounded LoRa event estimates on a receiver-session sample timeline."""
from copy import deepcopy
import math
import threading
import uuid


class LiveLoRaHistory:
    def __init__(self,session_id,capacity=128):
        if not 1<=capacity<=128:
            raise ValueError('History capacity must be 1..128')
        self.lock=threading.Lock()
        self.capacity=capacity
        self.session_id=session_id
        self.events=[]
        self.evicted=0
        self.revision=0

    def reset(self,session_id):
        with self.lock:
            self.session_id=session_id
            self.events=[]
            self.evicted=0
            self.revision+=1

    def observe(self,session_id,frames,fs,start_sample,end_sample,mode):
        if not math.isfinite(fs) or fs<=0:
            raise ValueError('Sample rate must be finite and positive')
        with self.lock:
            if session_id!=self.session_id:
                return {'recorded':False,'reason':'different_receiver_session'}
            new=merged=skipped=0
            for frame in frames:
                payload=frame.get('payload_hex','')
                params=frame.get('parameters',{})
                time=frame.get('time_seconds',float('nan'))
                symbol=params.get('symbol_seconds',float('nan'))
                try:
                    valid_bytes=bytes.fromhex(payload)
                except (ValueError,TypeError):
                    valid_bytes=b''
                if (frame.get('status')!='payload_crc_valid' or not 2<=len(valid_bytes)<=255
                        or not math.isfinite(time) or not math.isfinite(symbol) or symbol<=0):
                    skipped+=1
                    continue
                position=start_sample+round(time*fs)
                if not start_sample<=position<end_sample:
                    skipped+=1
                    continue
                tolerance=max(1,round(symbol*fs))
                payload=valid_bytes.hex()
                found=next((e for e in self.events if e['payload_hex']==payload
                    and e['parameters']==params and e['coding_rate']==frame.get('coding_rate')
                    and abs(e['sample_index_estimate']-position)<=tolerance),None)
                if found is None:
                    found={'id':uuid.uuid4().hex,'sample_index_estimate':position,
                        'time_seconds_estimate':position/fs,'sample_rate':fs,'parameters':deepcopy(params),
                        'coding_rate':frame.get('coding_rate'),'payload_hex':payload,
                        'observation_count':0,'modes':[],
                        'minimum_observed_sample_index':position,'maximum_observed_sample_index':position,
                        'quarter_chirp_confirmed_in_any_observation':False}
                    if 'text' in frame:found['text']=frame['text']
                    self.events.append(found)
                    new+=1
                else:
                    merged+=1
                found['observation_count']+=1
                if mode not in found['modes']:found['modes'].append(mode)
                found['minimum_observed_sample_index']=min(found['minimum_observed_sample_index'],position)
                found['maximum_observed_sample_index']=max(found['maximum_observed_sample_index'],position)
                found['quarter_chirp_confirmed_in_any_observation']|=bool(frame.get('quarter_chirp_validated',False))
                frame['live_event_id']=found['id']
                self.revision+=1
                if len(self.events)>self.capacity:
                    oldest=min(self.events,key=lambda e:e['sample_index_estimate'])
                    self.events.remove(oldest)
                    self.evicted+=1
            return {'recorded':True,'new_event_estimates':new,'merged_observations':merged,
                    'skipped_frames':skipped,'retained_events':len(self.events),'evicted_events':self.evicted}

    def version(self):
        with self.lock:
            return self.revision

    def snapshot(self):
        with self.lock:
            return {'schema_version':'0.1','family':'LoRa','position_kind':'estimated_data_symbol_start',
                'session_id':self.session_id,'revision':self.revision,'capacity':self.capacity,
                'evicted_events':self.evicted,
                'events':deepcopy(sorted(self.events,key=lambda e:e['sample_index_estimate'],reverse=True)),
                'time_reference':'received_samples_in_session',
                'matching_rule':'Same bytes, PHY parameters and coding rate within one symbol of the first retained observation; heuristic event estimate.',
                'limitations':['LoRa CRC does not authenticate the sender.',
                    'Only retained events are compared; identical overlapping transmitters may be indistinguishable.',
                    'History is in memory, resets on receiver restart and is not a continuous archive.']}

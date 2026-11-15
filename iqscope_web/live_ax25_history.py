"""Bounded FCS-checked FM AX.25 event estimates across live snapshots."""
from copy import deepcopy
import math
import threading
import uuid

from iqscope_ax25 import encode_kiss_frame
from iqscope_ax25_link import parse_link


class LiveAX25History:
    def __init__(self, session_id, capacity=128):
        if type(capacity) is not int or not 1<=capacity<=128:
            raise ValueError('History capacity must be 1..128')
        self.lock=threading.Lock()
        self.capacity=capacity
        self.session_id=session_id
        self.events=[]
        self.evicted=0
        self.revision=0

    def reset(self, session_id):
        with self.lock:
            self.session_id=session_id
            self.events=[]
            self.evicted=0
            self.revision+=1

    def observe(self, session_id, frames, fs, center_hz, start_sample, end_sample):
        if (not math.isfinite(fs) or fs<=0 or not math.isfinite(center_hz)
                or type(start_sample) is not int or type(end_sample) is not int
                or not 0<=start_sample<=end_sample):
            raise ValueError('Invalid live source interval or sample rate')
        with self.lock:
            if session_id!=self.session_id:
                return dict(recorded=False,reason='different_receiver_session')
            new=merged=skipped=0
            for frame in frames[:128]:
                try:
                    packet=bytes.fromhex(frame['hex'])
                    time=float(frame['time_seconds']);end=float(frame['time_end_seconds'])
                    offset=float(frame['channel']['offset_hz'])
                    if (frame.get('fcs_valid') is not True or frame.get('frontend')!='fm_iq_afsk1200'
                            or not all(math.isfinite(v) for v in (time,end,offset)) or end<=time):
                        raise ValueError('Incomplete FM frame evidence')
                    encode_kiss_frame(packet)  # Recheck length and FCS, without repair.
                    fields=parse_link(packet[:-2])
                    position=start_sample+round(time*fs)
                    end_position=start_sample+math.ceil(end*fs)
                    if fields is None or not start_sample<=position<end_position<=end_sample:
                        raise ValueError('Unsupported frame or outside the captured interval')
                except (KeyError,ValueError,TypeError,OverflowError):
                    skipped+=1
                    continue
                tolerance=max(1,round(2*fs/1200))
                found=next((e for e in self.events if e['hex']==packet.hex()
                    and e['sample_rate']==fs and e['center_frequency_hz']==center_hz
                    and abs(e['sample_index_estimate']-position)<=tolerance
                    and abs(e['channel_offset_hz']-offset)<=500),None)
                if found is None:
                    found=dict(id=uuid.uuid4().hex,hex=packet.hex(),fields=fields,
                        sample_index_estimate=position,end_sample_index_estimate=end_position,
                        time_seconds_estimate=position/fs,sample_rate=fs,
                        center_frequency_hz=center_hz,channel_offset_hz=offset,
                        frequency_hz=center_hz+offset,rf_center_known=center_hz!=0,
                        observation_count=0,minimum_observed_sample_index=position,
                        maximum_observed_sample_index=position,fcs_valid=True,
                        frontend='fm_iq_afsk1200')
                    self.events.append(found)
                    new+=1
                else:
                    merged+=1
                found['observation_count']+=1
                found['minimum_observed_sample_index']=min(found['minimum_observed_sample_index'],position)
                found['maximum_observed_sample_index']=max(found['maximum_observed_sample_index'],position)
                frame['live_event_id']=found['id']
                self.revision+=1
                if len(self.events)>self.capacity:
                    self.events.remove(min(self.events,key=lambda e:e['sample_index_estimate']))
                    self.evicted+=1
            return dict(recorded=True,new_event_estimates=new,merged_observations=merged,
                        skipped_frames=skipped,deferred_frames=max(0,len(frames)-128),
                        retained_events=len(self.events),evicted_events=self.evicted)

    def version(self):
        with self.lock:
            return self.revision

    def snapshot(self):
        with self.lock:
            return dict(schema_version='0.1',family='AX.25 FM',session_id=self.session_id,
                revision=self.revision,capacity=self.capacity,evicted_events=self.evicted,
                events=deepcopy(sorted(self.events,key=lambda e:e['sample_index_estimate'],reverse=True)),
                time_reference='received_samples_in_session',position_kind='estimated_first_frame_data_symbol',
                matching_rule='Same full frame/FCS, sample rate and center; within two nominal 1200-baud symbols of first observation and 500 Hz channel offset.',
                field_scope='Reparsed from each accepted frame; no link-state inference or cross-window APRS calibration.',
                limitations=['Event matching is heuristic; simultaneous indistinguishable transmitters can merge.',
                             'FCS does not authenticate a sender. I-frame control-mode candidates remain unresolved.',
                             'Memory-only history resets on receiver restart and evicts oldest events; not a continuous archive.'])

    def kiss(self):
        with self.lock:
            return b''.join(encode_kiss_frame(bytes.fromhex(e['hex']))
                            for e in sorted(self.events,key=lambda e:e['sample_index_estimate']))

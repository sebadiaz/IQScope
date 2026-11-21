"""Bounded CRC-rechecked event estimates within one automatic IQ file pass."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path

from iqscope_adsb import mode_s_remainder
from iqscope_ax25 import encode_kiss_frame
from iqscope_ax25_link import parse_link
from iqscope_lora_payload import payload_crc
from iqscope_ais import checked_ais_packet
from iqscope_rds import checked_rds_group

CRC_DECODERS=frozenset(('adsb_1090es','ais_gmsk','rds_fm','ax25_ui','afsk1200_fm_ax25','afsk1200_ax25','lora_preamble'))


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Nonfinite event metadata')
    return value


def _packet(frame,decoder,fs):
    """Recheck bytes, preserve PHY scope, and choose conservative matching rules."""
    if decoder=='lora_preamble':
        raw=bytes.fromhex(frame['payload_hex'])
        if (not 2<=len(raw)<=255 or frame['status']!='payload_crc_valid'
                or type(frame['received_crc']) is not int or payload_crc(raw)!=frame['received_crc']):
            raise ValueError('Invalid LoRa payload CRC')
        p=frame['parameters'];sf=p['spreading_factor'];bw=p['bandwidth_hz'];polarity=p['chirp_polarity']
        if type(sf) is not int or not 7<=sf<=10 or bw not in (125000,250000,500000) or polarity not in (-1,1):
            raise ValueError('Unsupported LoRa event parameters')
        parameters=dict(spreading_factor=sf,bandwidth_hz=bw,chirp_polarity=polarity,
                        coding_rate_index=frame['coding_rate_index'],sync_word=frame.get('sync_word'))
        if type(parameters['coding_rate_index']) is not int or not 1<=parameters['coding_rate_index']<=4:
            raise ValueError('Unsupported LoRa coding rate')
        return dict(hex=raw.hex(),family='LoRa PHY',byte_scope='payload_without_phy_crc',
                    validation='Payload CRC16 rechecked; explicit-header validation is supplied by the source decoder.',
                    fields=parameters,matching_parameters=parameters,tolerance=max(1,round(fs*(1<<sf)/bw)),
                    integrity=dict(algorithm='LoRa payload CRC16',received_crc=frame['received_crc'],calculated_crc=payload_crc(raw)),
                    offset=0,channel_tolerance=0,frontend='centered_lora')
    raw=bytes.fromhex(frame['hex'])
    if decoder=='rds_fm':
        if frame.get('crc_valid') is not True:raise ValueError('RDS CRC claim missing')
        fields=checked_rds_group(raw);offset=_number(frame['channel']['offset_hz'])
        return dict(hex=raw.hex(),family='RDS',byte_scope='four_26bit_blocks_with_offset_crc',
                    validation='Four RDS offset/CRC-10 checks rechecked; declared fields, no cross-window text assembly.',
                    fields=fields,matching_parameters={},tolerance=max(1,round(2*fs/1187.5)),
                    offset=offset,channel_tolerance=5000,frontend='fm_57khz_biphase_dbpsk')
    if decoder=='ais_gmsk':
        if frame.get('fcs_valid') is not True:raise ValueError('AIS FCS claim missing')
        fields=checked_ais_packet(raw);offset=_number(frame['channel']['offset_hz'])
        return dict(hex=raw.hex(),family='AIS',byte_scope='full_frame_with_fcs',
                    validation='AIS CRC-16/X-25 and message fields rechecked; transmitter declarations, no cross-window vessel state.',
                    fields=fields,matching_parameters={},tolerance=max(1,round(2*fs/9600)),
                    offset=offset,channel_tolerance=1000,frontend='gmsk_fm_nrzi')
    if decoder=='adsb_1090es':
        if len(raw)!=14 or raw[0]>>3 not in (17,18) or mode_s_remainder(raw):
            raise ValueError('Invalid ADS-B CRC24 or downlink format')
        fields=dict(downlink_format=raw[0]>>3,address_hex=raw[1:4].hex().upper(),type_code=raw[4]>>3)
        if fields['downlink_format']==18:fields['control_field']=raw[0]&7
        return dict(hex=raw.hex(),family='Mode S / ADS-B',byte_scope='full_frame_with_crc',
                    validation='DF17/18 CRC24 rechecked; no cross-window CPR or status association.',
                    fields=fields,matching_parameters={},tolerance=max(1,round(fs/1e6)),
                    offset=0,channel_tolerance=0,frontend='ppm')
    if frame.get('fcs_valid') is not True:
        raise ValueError('AX.25 FCS claim missing')
    encode_kiss_frame(raw)  # Strict length/FCS verification, no repair.
    fields=parse_link(raw[:-2])
    if fields is None or (decoder!='afsk1200_fm_ax25' and fields['frame_type']!='UI'):
        raise ValueError('Unsupported AX.25 frame layout')
    frontend=frame.get('frontend','generic_fsk')
    channel=frame.get('channel') or {}
    offset=_number(channel.get('offset_hz',0))
    # Generic FSK/BPSK records do not carry a symbol rate: merge only within
    # one source sample. The FM/AFSK path has a known nominal 1200-baud clock.
    afsk=decoder in ('afsk1200_fm_ax25','afsk1200_ax25')
    return dict(hex=raw.hex(),family='AX.25',byte_scope='full_frame_with_fcs',
                validation='CRC-16/X-25 and address/control layout rechecked; no connection state or application reassembly.',
                fields=fields,matching_parameters={},tolerance=max(1,round(2*fs/1200)) if afsk else 1,
                offset=offset,channel_tolerance=500 if afsk else 0,frontend=frontend)


class ScanEventCatalogue:
    def __init__(self,fs,center_hz,capacity=128,reference_capacity=32,window_budget=512):
        if (_number(fs)<=0 or not math.isfinite(_number(center_hz))
                or type(capacity) is not int or not 1<=capacity<=128
                or type(reference_capacity) is not int or not 1<=reference_capacity<=32
                or type(window_budget) is not int or not 1<=window_budget<=512):
            raise ValueError('Invalid scan catalogue limits')
        self.fs=fs;self.center=center_hz;self.capacity=capacity
        self.reference_capacity=reference_capacity;self.window_budget=window_budget
        self.events=[];self.rules={}
        self.accepted=0;self.merged=0;self.rejected=0;self.deferred=0;self.deferred_references=0

    def observe(self,report,index,directory):
        window=report['source_window'];start=window['start_sample'];end=window['end_sample']
        examined=0
        for trial_index,trial in enumerate(report['wideband_trials']):
            decoder=trial['decoder']
            if decoder not in CRC_DECODERS:continue
            frames=trial.get('frames',[])
            for frame_index,frame in enumerate(frames):
                if examined>=self.window_budget:
                    self.deferred+=len(frames)-frame_index;break
                examined+=1
                try:
                    packet=_packet(frame,decoder,self.fs)
                    time=_number(frame['time_seconds'])
                    position=start+round(time*self.fs)
                    if not 0<=time or not start<=position<end:
                        raise ValueError('Event outside the source window')
                    end_position=None
                    evidence={}
                    if decoder=='lora_preamble':
                        evidence={key:deepcopy(frame[key]) for key in ('experimental_mode','quarter_chirp_validated',
                            'boundary_method','corrected_spillover_bits','corrected_payload_codeword_bits',
                            'soft_symbol_corrections') if key in frame}
                    if decoder=='adsb_1090es':
                        local=frame['sample_start']
                        if type(local) is not int or local!=position-start:
                            raise ValueError('Inconsistent ADS-B source index')
                    elif decoder!='lora_preamble':
                        end_time=_number(frame['time_end_seconds'])
                        end_position=start+math.ceil(end_time*self.fs)
                        if end_time<=time or not position<end_position<=end:
                            raise ValueError('Invalid packet event end')
                except (KeyError,TypeError,ValueError,OverflowError):
                    self.rejected+=1;continue
                interpretation=report.get('interpretation_status')
                key=(decoder,packet['frontend'],packet['hex'],json.dumps(packet['matching_parameters'],sort_keys=True),interpretation)
                found=next((e for e in self.events if self.rules[e['id']]==key
                    and abs(e['source_sample_estimate']-position)<=e['matching_tolerance_samples']
                    and abs(e['channel_offset_hz']-packet['offset'])<=e['matching_channel_tolerance_hz']),None)
                if found is None:
                    if len(self.events)>=self.capacity:
                        self.deferred+=1;continue
                    event_id=f'event-{len(self.events)+1:04d}'
                    found=dict(id=event_id,decoder=decoder,family=packet['family'],frontend=packet['frontend'],
                        hex=packet['hex'],byte_scope=packet['byte_scope'],validation=packet['validation'],
                        integrity=packet.get('integrity',{}),
                        fields=packet['fields'],input_interpretation_status=interpretation,
                        source_sample_estimate=position,source_seconds_estimate=position/self.fs,
                        source_end_sample_estimate=end_position,channel_offset_hz=packet['offset'],
                        frequency_hz=self.center+packet['offset'],rf_center_known=self.center!=0,
                        matching_tolerance_samples=packet['tolerance'],matching_channel_tolerance_hz=packet['channel_tolerance'],
                        minimum_observed_sample=position,maximum_observed_sample=position,
                        observation_count=0,observations=[],deferred_references=0,
                        experimental_observations=0,inferred_boundary_observations=0,
                        binary_artifact=f'events/{event_id}.bin')
                    self.events.append(found);self.rules[event_id]=key
                else:self.merged+=1
                self.accepted+=1;found['observation_count']+=1
                found['experimental_observations']+=int(evidence.get('experimental_mode') is True)
                found['inferred_boundary_observations']+=int(evidence.get('quarter_chirp_validated') is False)
                found['minimum_observed_sample']=min(found['minimum_observed_sample'],position)
                found['maximum_observed_sample']=max(found['maximum_observed_sample'],position)
                if len(found['observations'])<self.reference_capacity:
                    found['observations'].append(dict(window_index=index,trial_index=trial_index,frame_index=frame_index,
                        report_artifact=f'{directory}/report.json',source_sample_estimate=position,
                        window_relative_seconds=time,channel_offset_hz=packet['offset'],input_interpretation_status=interpretation,
                        decoder_evidence=evidence))
                else:found['deferred_references']+=1;self.deferred_references+=1

    def snapshot(self):
        return dict(schema_version='0.1',source_kind='iq_file_scan_events',sample_rate=self.fs,
            center_frequency_hz=self.center,capacity=self.capacity,reference_capacity=self.reference_capacity,
            per_window_observation_budget=self.window_budget,event_count=len(self.events),
            accepted_observations=self.accepted,merged_observations=self.merged,rejected_observations=self.rejected,
            deferred_observations=self.deferred,deferred_references=self.deferred_references,
            supported_decoders=sorted(CRC_DECODERS),events=deepcopy(sorted(self.events,key=lambda e:e['source_sample_estimate'])),
            time_reference='source_file_samples',position_kind='decoder_frame_start_estimate',
            matching_rule='Same decoder/frontend, bytes and PHY parameters; source time and channel stay within tolerances anchored to the first observation.',
            limitations=['Event grouping is heuristic, not a count of unique physical packets or transmitters.',
                         'CRC verifies received byte integrity, not emitter authenticity.',
                         'Only supported CRC-checked frames are indexed; other results remain in window reports.',
                         'No cross-window DSP, link state, APRS calibration or CPR reconstruction.',
                         'Catalogue and references are bounded; deferred observations remain in window reports.',
                         'A resumed pass creates a separate catalogue. Input-format interpretation warnings still apply.'])

    def write(self,out,snapshot):
        out=Path(out)
        for event in snapshot['events']:
            path=out/event['binary_artifact'];path.parent.mkdir(exist_ok=True)
            if not path.exists():
                pending=path.with_suffix('.bin.tmp');pending.write_bytes(bytes.fromhex(event['hex']));os.replace(pending,path)
        pending=out/'scan-events.json.tmp';pending.write_text(json.dumps(snapshot,indent=2));os.replace(pending,out/'scan-events.json')

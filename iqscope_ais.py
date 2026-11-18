"""Bounded AIS GMSK/NRZI reception with strict HDLC FCS; no bit repair."""
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np
from scipy import signal

from iqscope_ax25 import crc_x25,unstuff


def parse_ais(payload):
    """Parse supported logical MSB-first fields from LSB-first wire octets."""
    if not isinstance(payload,bytes) or not 5<=len(payload)<=126:return None
    bits=''.join(f'{v:08b}' for v in payload)
    def u(start,width):return int(bits[start:start+width],2)
    def signed(start,width):
        value=u(start,width)
        return value-(1<<width) if value&(1<<(width-1)) else value
    kind=u(0,6);mmsi=u(8,30)
    if not 1<=kind<=63 or not 1<=mmsi<=999999999:return None
    lengths={1:21,2:21,3:21,4:21,5:53,11:21,18:21,19:39,27:12}
    if kind in lengths and len(payload)!=lengths[kind]:return None
    if kind==24:
        if len(payload)<6 or u(38,2)>1:return None
        if u(38,2)==0:
            if len(payload)!=20 and not (len(payload)==21 and payload[-1]==0):return None
        elif len(payload)!=21:return None
    fields=dict(message_type=kind,repeat_indicator=u(6,2),mmsi=mmsi,mmsi_text=f'{mmsi:09d}',
                payload_hex=payload.hex(),payload_bits=len(bits),interpretation='header_only')

    def position(lon_start,lon_width,lat_start,lat_width,scale):
        lon=signed(lon_start,lon_width);lat=signed(lat_start,lat_width)
        fields.update(raw_longitude=lon,raw_latitude=lat,coordinate_units_per_degree=scale,
            longitude_deg=lon/scale if abs(lon)<=180*scale else None,
            latitude_deg=lat/scale if abs(lat)<=90*scale else None,
            position_status='reported' if abs(lon)<=180*scale and abs(lat)<=90*scale else
                'not_available' if lon==181*scale or lat==91*scale else 'out_of_range')

    def navigation(speed,course,heading,second):
        sog=u(speed,10);cog=u(course,12);hdg=u(heading,9);stamp=u(second,6)
        fields.update(raw_speed_over_ground=sog,speed_over_ground_knots=sog/10 if sog<1023 else None,
            speed_status='not_available' if sog==1023 else 'at_least' if sog==1022 else 'reported',
            raw_course_over_ground=cog,course_over_ground_deg=cog/10 if cog<3600 else None,
            course_status='reported' if cog<3600 else 'not_available' if cog==3600 else 'reserved',
            raw_true_heading=hdg,true_heading_deg=hdg if hdg<360 else None,
            heading_status='reported' if hdg<360 else 'not_available' if hdg==511 else 'reserved',
            raw_utc_second=stamp,utc_second=stamp if stamp<60 else None,
            utc_second_status='reported' if stamp<60 else ('not_available','manual','estimated','inoperative')[stamp-60])

    def text(start,count):
        alphabet='@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !"#$%&\'()*+,-./0123456789:;<=>?'
        return ''.join(alphabet[u(start+6*i,6)] for i in range(count)).rstrip('@ ')

    if kind in (1,2,3):
        fields.update(interpretation='class_a_position',navigation_status=u(38,4),raw_rate_of_turn=signed(42,8),
                      position_accuracy_flag=bool(u(60,1)),raim_flag=bool(u(148,1)))
        position(61,28,89,27,600000);navigation(50,116,128,137)
    elif kind in (18,19):
        fields.update(interpretation='class_b_position',position_accuracy_flag=bool(u(56,1)))
        position(57,28,85,27,600000);navigation(46,112,124,133)
        if kind==19:fields.update(ship_name=text(143,20),ship_type=u(263,8))
    elif kind in (4,11):
        fields.update(interpretation='base_station_position',position_accuracy_flag=bool(u(78,1)),
                      raw_utc=dict(year=u(38,14),month=u(52,4),day=u(56,5),hour=u(61,5),minute=u(66,6),second=u(72,6)))
        position(79,28,107,27,600000)
    elif kind==27:
        fields.update(interpretation='long_range_position',position_accuracy_flag=bool(u(38,1)),
                      raim_flag=bool(u(39,1)),navigation_status=u(40,4))
        position(44,18,62,17,600)
        sog=u(79,6);cog=u(85,9)
        fields.update(raw_speed_over_ground=sog,speed_over_ground_knots=sog if sog<63 else None,
                      speed_status='reported' if sog<63 else 'not_available',raw_course_over_ground=cog,
                      course_over_ground_deg=cog if cog<360 else None,
                      course_status='reported' if cog<360 else 'not_available' if cog==511 else 'reserved')
    elif kind==5:
        fields.update(interpretation='static_voyage',imo_number=u(40,30),callsign=text(70,7),
                      ship_name=text(112,20),ship_type=u(232,8),destination=text(302,20))
    elif kind==24:
        part=u(38,2);fields.update(interpretation='static_data',part_number=part)
        if part==0:fields['ship_name']=text(40,20)
        else:fields.update(ship_type=u(40,8),callsign=text(90,7))
    return fields


def checked_ais_packet(packet):
    if not isinstance(packet,bytes) or not 7<=len(packet)<=128 or crc_x25(packet[:-2])!=int.from_bytes(packet[-2:],'little'):
        raise ValueError('Invalid AIS packet length or FCS')
    fields=parse_ais(packet[:-2])
    if fields is None:raise ValueError('Unsupported AIS header or message length')
    return fields


def _channel(x,fs,offset):
    mixed=x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
    down=max(1,math.ceil(fs/96000))
    y=signal.resample_poly(mixed,1,down) if down>1 else mixed
    rate=fs/down;ratio=Fraction(48000/rate).limit_denominator(4096)
    y=signal.resample_poly(y,ratio.numerator,ratio.denominator)
    rate*=ratio.numerator/ratio.denominator
    y=signal.convolve(y,signal.firwin(129,10000,fs=rate),mode='same')
    discriminator=np.angle(y[1:]*np.conj(y[:-1]))*rate/(2*np.pi)
    # Symmetric integrate-and-dump approximation; all filtering is centered.
    frequency=signal.convolve(discriminator,np.ones(5)/5,mode='same')
    return frequency,rate,dict(tuning_offset_hz=float(offset),input_sample_rate=float(fs),
        sample_rate=float(rate),decimation=down,resample_numerator=ratio.numerator,resample_denominator=ratio.denominator,
        discriminator_start_seconds=.5/rate,filter_delay_compensated=True,edge_padding='zero')


def search_ais(x,fs,bands,center_hz=0,max_channels=4,max_seconds=10,max_frames=128,max_flag_pairs=6000):
    result=dict(decoder='ais_gmsk',family='AIS / GMSK',frames=[],channels_examined=[],nominal_baud=9600,
        frame_budget=max_frames,flag_pair_budget=max_flag_pairs,channel_budget=min(4,max(0,max_channels)),
        validation_scope='CRC-16/X-25, supported AIS header/length and partial message fields; declared content, not authenticated positions',
        limitations=['24 kS/s to 2.4 MS/s, at most ten seconds and eight million input samples per trial.',
            'At most four RF/spectral/baseband channel hypotheses; fixed nominal 9600 baud, twenty sample phases.',
            'Requires 20 of 24 alternating training bits, exact HDLC flags, strict stuffing, byte alignment and FCS; no bit repair.',
            'No collision cancellation, adaptive clock tracking, slot scheduling, binary-application decoding or cross-window vessel state.',
            'Positions, MMSI and static text are transmitter declarations; CRC does not authenticate an emitter.'])
    if (not math.isfinite(fs) or not 24000<=fs<=2400000 or not math.isfinite(center_hz)
            or not np.iscomplexobj(x) or np.ndim(x)!=1 or len(x)<fs*.01):
        return dict(result,status='not_applicable')
    count=min(len(x),int(fs*min(10,max(0,max_seconds))),8000000)
    samples=np.asarray(x[:count])
    if len(samples)<fs*.01 or not np.all(np.isfinite(samples)):return dict(result,status='not_applicable')
    offsets=[]
    def add(offset,origin):
        if abs(offset)+10000<fs/2 and all(abs(offset-v[0])>2000 for v in offsets):offsets.append((float(offset),origin))
    if center_hz:
        for rf in (161975000,162025000):add(rf-center_hz,'declared_rf_ais_channel')
    for band in sorted(bands,key=lambda b:b.get('spectral_snr_db',0),reverse=True):
        offset=band.get('offset_hz',float('nan'))
        if 6000<=band.get('bandwidth_hz',0)<=24000 and math.isfinite(offset):add(offset,'spectral')
    if fs<=96000:add(0,'baseband')
    selected=offsets[:result['channel_budget']]
    frames=[];examined=0;crc_rejected=0;structure_rejected=0;training_rejected=0;exhausted=False
    for channel_index,(offset,origin) in enumerate(selected):
        if len(frames)>=max_frames or examined>=max_flag_pairs:exhausted=True;break
        frequency,rate,metadata=_channel(samples,fs,offset)
        step=rate/9600;grid=np.arange(len(frequency));quota=max(1,(max_flag_pairs-examined)//(len(selected)-channel_index))
        used=0;accepted=0;phases=0
        for phase in np.arange(20)*step/20:
            if used>=quota or len(frames)>=max_frames:exhausted=True;break
            phases+=1;times=np.arange(phase,len(frequency)-1,step)
            tones=np.interp(times,grid,frequency)>0
            bits=bytes((tones[1:]==tones[:-1]).astype('u1')+48).decode('ascii')
            flags=[];cursor=0
            while True:
                pos=bits.find('01111110',cursor)
                if pos<0:break
                flags.append(pos);cursor=pos+1
            for start,end in zip(flags,flags[1:]):
                if not 56<=end-start<=1240 or start<24:continue
                training=bits[start-24:start]
                errors=min(sum(a!=b for a,b in zip(training,'01'*12)),sum(a!=b for a,b in zip(training,'10'*12)))
                if errors>4:training_rejected+=1;continue
                if used>=quota or len(frames)>=max_frames:exhausted=True;break
                used+=1;examined+=1
                packet=unstuff(bits[start+8:end])
                if packet is None or not 7<=len(packet)<=128:structure_rejected+=1;continue
                if crc_x25(packet[:-2])!=int.from_bytes(packet[-2:],'little'):crc_rejected+=1;continue
                fields=parse_ais(packet[:-2])
                if fields is None:structure_rejected+=1;continue
                time=float((phase+(start+9)*step+.5)/rate)
                end_time=float((phase+(end+8.5)*step+.5)/rate)
                if end_time>len(samples)/fs:continue
                if any(f['hex']==packet.hex() and abs(f['time_seconds']-time)<2/9600
                       and abs(f['channel']['offset_hz']-offset)<1000 for f in frames):continue
                frequency_hz=center_hz+offset
                rf_channel=next((name for name,hz in [('A',161975000),('B',162025000)] if center_hz and abs(frequency_hz-hz)<=1000),None)
                frames.append(dict(decoder='ais_gmsk',frontend='gmsk_fm_nrzi',hex=packet.hex(),fcs_valid=True,
                    fcs='CRC-16/X-25',fields=fields,time_seconds=time,time_end_seconds=end_time,
                    channel=dict(offset_hz=offset,frequency_hz=float(frequency_hz),rf_center_known=center_hz!=0,
                                 ais_channel=rf_channel,frequency_estimate=origin),
                    timing=dict(nominal_baud=9600,phase_sample=float(phase),sample_rate=float(rate),
                                training_bits=24,training_bit_mismatches=errors),
                    validation_scope=result['validation_scope']))
                accepted+=1
        result['channels_examined'].append(dict(metadata,origin=origin,accepted_frames=accepted,phases_examined=phases,
            flag_pairs_examined=used,flag_pair_budget=quota,budget_exhausted=used>=quota))
    frames.sort(key=lambda f:f['time_seconds'])
    return dict(result,status='validated_frames' if frames else 'no_valid_frames',frames=frames,
        analyzed_seconds=len(samples)/fs,duration_limited=count<len(x),deferred_channel_count=max(0,len(offsets)-len(selected)),
        flag_pairs_examined=examined,crc_rejected=crc_rejected,structure_rejected=structure_rejected,
        training_rejected=training_rejected,budget_exhausted=exhausted)


def write_ais_artifacts(trial,out):
    if not trial['frames']:return
    out=Path(out)
    for frame in trial['frames']:checked_ais_packet(bytes.fromhex(frame['hex']))
    for index,frame in enumerate(trial['frames'],1):
        frame['wire_artifact']=f'ais-frame-{index:03d}.bin';frame['payload_artifact']=f'ais-message-{index:03d}.bin'
        raw=bytes.fromhex(frame['hex']);(out/frame['wire_artifact']).write_bytes(raw)
        (out/frame['payload_artifact']).write_bytes(raw[:-2])
    trial['artifact']='ais-frames.json';(out/trial['artifact']).write_text(json.dumps(trial,indent=2))

"""Read-only, bounded AX.25 history import with fresh FCS/layout checks."""
import base64
import json
import math

from iqscope_ax25 import encode_kiss_frame
from iqscope_ax25_link import parse_link

MAX_ARCHIVE_BYTES=1024*1024


def _integer(value, name, maximum=10**15):
    if type(value) is not int or not 0<=value<=maximum:
        raise ValueError('Invalid archive '+name)
    return value


def _number(value, name):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Invalid archive '+name)
    return value


def open_ax25_archive(data):
    if len(data)>MAX_ARCHIVE_BYTES:
        raise ValueError('AX.25 archive exceeds 1 MiB')
    def limited_integer(value):
        if len(value)>20:
            raise ValueError('Archive integer is too large')
        return int(value)
    try:
        original=json.loads(data,parse_int=limited_integer)
        if (not isinstance(original,dict) or original.get('schema_version')!='0.1'
                or original.get('family')!='AX.25 FM'
                or original.get('time_reference')!='received_samples_in_session'
                or original.get('position_kind')!='estimated_first_frame_data_symbol'):
            raise ValueError('Expected an IQScope AX.25 FM history JSON')
        session=original['session_id']
        if not isinstance(session,str) or not 1<=len(session)<=128 or not session.isprintable():
            raise ValueError('Invalid archive session')
        capacity=_integer(original['capacity'],'capacity',128)
        frames=original['events']
        if not capacity or not isinstance(frames,list) or len(frames)>capacity:
            raise ValueError('Invalid archive event count')
        events=[];seen=set()
        for event in frames:
            event_id=event['id']
            if (not isinstance(event_id,str) or not 1<=len(event_id)<=64
                    or not all(c in '0123456789abcdefABCDEF-' for c in event_id) or event_id in seen):
                raise ValueError('Invalid or duplicate archive event identifier')
            seen.add(event_id)
            packet=bytes.fromhex(event['hex'])
            encode_kiss_frame(packet)  # Recheck FCS and supported frame length.
            fields=parse_link(packet[:-2])
            if fields is None:
                raise ValueError('Unsupported AX.25 address/control layout')
            rate=_number(event['sample_rate'],'sample rate')
            if not 20000<=rate<=2400000:
                raise ValueError('Unsupported archive FM IQ sample rate')
            start=_integer(event['sample_index_estimate'],'frame start')
            end=_integer(event['end_sample_index_estimate'],'frame end')
            low=_integer(event['minimum_observed_sample_index'],'minimum frame start')
            high=_integer(event['maximum_observed_sample_index'],'maximum frame start')
            count=_integer(event['observation_count'],'observation count',10**9)
            if not count or not low<=start<=high or end<=start or high-low>2*max(1,round(2*rate/1200)):
                raise ValueError('Invalid archive timing or observation count')
            center=_number(event['center_frequency_hz'],'RF center')
            offset=_number(event['channel_offset_hz'],'channel offset')
            frequency=center+offset
            if not math.isfinite(frequency):
                raise ValueError('Invalid archive frequency')
            events.append(dict(id=event_id,hex=packet.hex(),fields=fields,fcs_valid=True,
                sample_index_estimate=start,end_sample_index_estimate=end,
                time_seconds_estimate=start/rate,sample_rate=rate,
                minimum_observed_sample_index=low,maximum_observed_sample_index=high,
                observation_count=count,center_frequency_hz=center,channel_offset_hz=offset,
                frequency_hz=frequency,rf_center_known=center!=0,
                frontend='archive_declared_fm_iq_afsk1200'))
        events.sort(key=lambda e:e['sample_index_estimate'],reverse=True)
        history=dict(schema_version='0.1',family='AX.25 FM',session_id=session,capacity=capacity,
            revision=_integer(original['revision'],'revision'),
            evicted_events=_integer(original['evicted_events'],'eviction count'),events=events,
            time_reference='received_samples_in_session',position_kind='estimated_first_frame_data_symbol')
        kiss=b''.join(encode_kiss_frame(bytes.fromhex(e['hex']))
                      for e in sorted(events,key=lambda e:e['sample_index_estimate']))
        return dict(source_kind='ax25_history_archive',history=history,
                    kiss_base64=base64.b64encode(kiss).decode('ascii'),
                    validation_scope='Frame FCS and address/control layouts rechecked from archived bytes. Timing, RF settings and observation counts are archive declarations; original IQ is unavailable. No link-state or cross-window APRS calibration reconstructed.')
    except (KeyError,TypeError,UnicodeDecodeError,RecursionError,OverflowError) as error:
        raise ValueError('Malformed IQScope AX.25 archive') from error

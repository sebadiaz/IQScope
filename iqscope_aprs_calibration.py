"""Declared APRS telemetry definitions with bounded, causal association.

No authentication, unit conversion, cross-trial or cross-window state.
"""
from copy import deepcopy
from itertools import groupby
import math
import re

from iqscope_aprs import parse_aprs_telemetry

_TARGET = re.compile(r'([A-Z0-9]{1,6})(?:-([0-9]|1[0-5]))?')
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_WIDTHS = (7,6,5,5,4,5,4,3,3,3,2,2,2)
_KINDS = ('PARM','UNIT','EQNS','BITS')


def parse_aprs_definition(payload):
    """Read only the four telemetry-definition messages, retaining their target."""
    if not isinstance(payload,(bytes,bytearray)) or len(payload)>256 or len(payload)<16 or payload[0]!=58 or payload[10]!=58:
        return None
    body=bytes(payload[11:])
    if body[:5] not in tuple((kind+'.').encode() for kind in _KINDS):
        return None
    kind=body[:4].decode()
    definition=dict(kind=kind,addressee_raw=bytes(payload[1:10]).decode('ascii',errors='replace'))
    result=dict(data_type_identifier=':',requested_profile='classic_telemetry_definition',
                status='invalid_telemetry_definition',definition=definition,
                validation_scope='APRS definition syntax only; no sender authentication or independently verified calibration')
    target=_TARGET.fullmatch(definition['addressee_raw'].rstrip(' '))
    if target is None:
        return result
    definition['target']=dict(callsign=target[1],ssid=int(target[2] or 0))
    if b'{' in body:
        body,identifier=body.split(b'{',1)
        if not re.fullmatch(rb'[A-Za-z0-9]{1,5}',identifier):
            return result
        definition['message_id']=identifier.decode()
    if len(body)>67 or any(byte<32 or byte>126 or byte in b'|~' for byte in body):
        return result
    text=body[5:].decode('ascii')
    definition['body_hex']=body.hex()
    if kind in ('PARM','UNIT'):
        values=text.split(',')
        if len(values)>13 or any(len(value)>limit for value,limit in zip(values,_WIDTHS)):
            return result
        definition['values']=values
    elif kind=='EQNS':
        tokens=text.split(',')
        if len(tokens)>15 or any(not _NUMBER.fullmatch(token) for token in tokens):
            return result
        values=[float(token) for token in tokens]
        if not all(math.isfinite(value) for value in values):
            return result
        definition['coefficient_tokens']=tokens
        definition['coefficients']=[values[i:i+3] if len(values[i:i+3])==3 else None for i in range(0,15,3)]
    else:
        if not re.fullmatch(r'[01]{8}(?:,[^|~{]{0,23})?',text):
            return result
        definition.update(sense_bits=[int(c) for c in text[:8]],project_title=text[9:] if len(text)>8 else '')
    result['status']='decoded_telemetry_definition'
    return result


def _finite(value):
    try:
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:
        return False


def _station(address):
    if not isinstance(address,dict):
        return None
    call,ssid=address.get('callsign'),address.get('ssid')
    if not isinstance(call,str) or not re.fullmatch(r'[A-Z0-9]{1,6}',call) or type(ssid) is not int or not 0<=ssid<=15:
        return None
    return call,ssid


def _domain(frame):
    fields=frame.get('fields',{})
    source=_station(fields.get('source'))
    if source is None:
        return None
    channel=frame.get('channel') or {}
    frontend=frame.get('frontend','recovered_2fsk')
    if not isinstance(channel,dict) or not isinstance(frontend,str) or not frontend:
        return None
    physical=tuple((key,channel[key]) for key in ('frequency_hz','offset_hz','audio_frequency_hz') if key in channel)
    if any(not _finite(value) for _,value in physical):
        return None
    if not physical:
        candidate=frame.get('candidate_index')
        if type(candidate) is not int or candidate<0:
            return None
        physical=(('candidate_index',candidate),)
    return source,frontend,physical


def enrich_aprs_telemetry_frames(frames,max_age_seconds=600):
    """Return independent frames with declared metadata from this trial only.

    Definition end must precede sample start. Equal-time conflicts invalidate
    that definition type; a shorter or malformed replacement never backfills
    old slots. Each definition expires separately. Raw values are reparsed.
    """
    if not _finite(max_age_seconds) or not 0<=max_age_seconds<=3600:
        raise ValueError('Definition age budget must be finite and between 0 and 3600 seconds')
    output=deepcopy(frames)
    events=[]
    for index,frame in enumerate(output):
        fields=frame.get('fields',{})
        if fields.get('pid')!=0xf0:
            continue
        try:
            payload=bytes.fromhex(fields.get('payload_hex',''))
        except (ValueError,TypeError):
            continue
        parsed=parse_aprs_telemetry(payload) or parse_aprs_definition(payload)
        if parsed is None:
            continue
        fields['aprs']=parsed
        key=_domain(frame)
        start,end=frame.get('time_seconds'),frame.get('time_end_seconds')
        timed=_finite(start) and _finite(end) and 0<=start<end
        valid=frame.get('fcs_valid') is True and key is not None and isinstance(frame.get('hex'),str)
        if 'definition' in parsed:
            definition=parsed['definition']
            own=key is not None and _station(definition.get('target'))==key[0]
            definition['association_eligibility']='self_addressed_claim' if own else 'different_or_invalid_source'
            if not valid or not own:
                if own:definition['association_eligibility']='unusable_frame_context'
                continue
            if not timed:
                definition['association_eligibility']='unusable_definition_timing'
                continue
            events.append((end,1,index,key))
        elif parsed['status']=='decoded_telemetry':
            t=parsed['telemetry']
            t['definition_context']=dict(status='no_eligible_definitions',max_age_seconds=max_age_seconds,
                scope='same source/SSID, frontend and channel; self-addressed definitions fully received before sample; this trial only')
            if valid and timed:
                events.append((start,0,index,key))
            else:
                t['definition_context']['status']='unusable_frame_context'
    state={}
    for when,group in groupby(sorted(events),key=lambda event:event[0]):
        pending={}
        for _,kind,index,key in group:
            frame=output[index];parsed=frame['fields']['aprs']
            if kind==1:
                definition=parsed['definition'];slot=(key,definition['kind'])
                pending.setdefault(slot,[]).append(index)
                continue
            t=parsed['telemetry'];context=t['definition_context']
            selected={};rejected={}
            for name in _KINDS:
                entry=state.get((key,name))
                if entry is None:
                    continue
                age=when-entry['end']
                if age>max_age_seconds:
                    rejected[name]='expired'
                elif entry['status']!='decoded_telemetry_definition':
                    rejected[name]=entry['status']
                elif age>0:
                    selected[name]=entry
            if rejected:context['excluded_definitions']=rejected
            if not selected:
                continue
            context.update(status='associated_declared_metadata',definitions={name:dict(
                frame_index=entry['index'],frame_hex=output[entry['index']]['hex'],
                received_end_seconds=entry['end'],age_seconds=when-entry['end']) for name,entry in selected.items()})
            def label(name,slot):
                values=selected.get(name,{}).get('definition',{}).get('values',[])
                return values[slot] if slot<len(values) and values[slot] else None
            analog=[]
            for slot,raw in enumerate(t['analog_raw']):
                channel=dict(channel=slot+1,raw_value=raw)
                for name,field in (('PARM','name'),('UNIT','unit')):
                    value=label(name,slot)
                    if value is not None:channel[field]=value
                coeffs=selected.get('EQNS',{}).get('definition',{}).get('coefficients',[None]*5)[slot]
                if coeffs is not None:
                    a,b,c=coeffs;value=(a*raw+b)*raw+c
                    channel['coefficients']=coeffs
                    if math.isfinite(value):
                        channel.update(value=value,value_status='declared_polynomial; unit label not converted')
                    else:channel['value_status']='non_finite_result; no value selected'
                analog.append(channel)
            sense=selected.get('BITS',{}).get('definition',{}).get('sense_bits')
            digital=[]
            for slot,raw in enumerate(t['digital_bits']):
                channel=dict(channel=slot+1,raw_bit=raw)
                for name,field in (('PARM','name'),('UNIT','label')):
                    value=label(name,slot+5)
                    if value is not None:channel[field]=value
                if sense is not None:
                    channel.update(declared_sense=sense[slot],matches_declared_sense=raw==sense[slot])
                digital.append(channel)
            t.update(analog_channels=analog,digital_channels=digital,
                     interpretation_status='raw values retained; eligible declared metadata associated; no authentication or unit conversion')
            if 'BITS' in selected:t['project_title']=selected['BITS']['definition']['project_title']
        # Samples at this timestamp are handled before definitions at it.
        for slot,indices in pending.items():
            index=indices[0];parsed=output[index]['fields']['aprs']
            conflict=len({output[i]['fields']['payload_hex'] for i in indices})>1
            state[slot]=dict(index=index,end=when,definition=parsed['definition'],
                             status='conflicting_equal_time_definitions' if conflict else parsed['status'])
    return output

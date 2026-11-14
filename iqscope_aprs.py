"""Bounded APRS position and telemetry syntax, without identity claims.

The enclosing AX.25 decoder checks FCS before calling this payload parser.
This module alone provides syntax interpretation, not packet validation.
"""
import re

_LAT = re.compile(r'[0-9]{2}[0-9 ]{2}\.[0-9 ]{2}[NS]')
_LON = re.compile(r'[0-9]{3}[0-9 ]{2}\.[0-9 ]{2}[EW]')
_TIME = re.compile(r'[0-9]{6}[zh/]')
_COURSE_SPEED = re.compile(rb'([0-9]{3})/([0-9]{3})')
_ALTITUDE = re.compile(rb'/A=([0-9]{6})(?![0-9])')
_TELEMETRY = re.compile(rb'T#([0-9]{3},|MIC,?)((?:[0-9]{3},){5})([01]{8})([\s\S]*)')


def parse_aprs_comment_telemetry(comment):
    """Decode one base-91 telemetry block; retain comment and extension bytes.

    Only an empty suffix or unapplied W/w DAO syntax is supported. Multiple
    delimiters, malformed pairs and other suffixes never yield partial values.
    This helper alone supplies syntax, not position or enclosing FCS validation.
    """
    if not isinstance(comment,(bytes,bytearray)) or len(comment)>256 or b'|' not in comment:
        return None
    result=dict(status='unsupported_or_malformed_comment_telemetry')
    if comment.count(b'|')!=2:
        return dict(result,status='ambiguous_or_incomplete_comment_telemetry')
    start,end=comment.index(b'|'),comment.rindex(b'|')
    block=bytes(comment[start+1:end]);suffix=bytes(comment[end+1:])
    result.update(extension_hex=bytes(comment[start:end+1]).hex(),
                  extension_span=dict(start=start,end=end+1,reference='position_comment_bytes'))
    if not 4<=len(block)<=14 or len(block)%2:
        return result
    values=[_base91(block[i:i+2]) for i in range(0,len(block),2)]
    if any(value is None for value in values):
        return result
    if suffix and not (re.fullmatch(rb'!W[0-9]{2}!',suffix) or re.fullmatch(rb'!w[!-{]{2}!',suffix)):
        return dict(result,status='unsupported_comment_telemetry_suffix')
    telemetry=dict(encoding='base91_comment',sequence=dict(raw=block[:2].decode('ascii'),
        kind='base91_counter',value=values[0]),analog_raw=values[1:6],
        interpretation_status='raw values only; names, units, calibration and bit sense not applied',
        extension_hex=result['extension_hex'],extension_span=result['extension_span'],
        comment=bytes(comment).decode('utf-8',errors='replace'),comment_hex=bytes(comment).hex())
    if len(values)==7:
        word=values[-1];bits=[(word>>bit)&1 for bit in range(8)]
        telemetry.update(digital_word_raw=word,digital_wire_hex=block[-2:].hex(),
            digital_bits=bits,digital_raw=''.join(map(str,bits)),digital_reserved_value=word>>8,
            digital_bit_order='canonical B1 through B8; B1 is the least significant bit of the received word')
    else:
        telemetry['digital_status']='not_transmitted'
    if suffix:
        telemetry['trailing_extension_status']='DAO syntax retained, not applied to coordinates'
    return dict(result,status='decoded_comment_telemetry',telemetry=telemetry)


def parse_aprs_telemetry(payload):
    """Classic five-channel unsigned 8-bit T# reports, without calibration.

    Definitions in other packets are not applied. A received 1 does not imply
    an active input, and a raw zero is a value rather than a missing sample.
    As with position parsing, the enclosing AX.25 receiver checks FCS separately.
    """
    if not isinstance(payload,(bytes,bytearray)) or not payload.startswith(b'T#') or len(payload)>256:
        return None
    result=dict(data_type_identifier='T', requested_profile='classic_t_hash_8bit',
                status='unsupported_or_malformed_telemetry',
                validation_scope='APRS payload syntax only; enclosing AX.25 FCS is separate; telemetry values and sender not independently verified')
    match=_TELEMETRY.fullmatch(payload)
    if match is None:
        return result
    sequence, analog, digital, comment=match.groups()
    values=[int(token) for token in analog.split(b',')[:-1]]
    if any(value>255 for value in values):
        return dict(result,status='invalid_telemetry_analog_range')
    raw_sequence=sequence.rstrip(b',').decode('ascii')
    counter=dict(raw=raw_sequence,kind='MIC' if raw_sequence=='MIC' else 'counter')
    if raw_sequence!='MIC':
        counter['value']=int(raw_sequence)
    result.update(status='decoded_telemetry',telemetry=dict(
        sequence=counter, analog_raw=values, digital_raw=digital.decode('ascii'),
        digital_bits=[byte-48 for byte in digital],
        digital_bit_order='left to right: B1 through B8; no active-bit sense applied',
        interpretation_status='raw values only; names, units, calibration and bit sense not applied',
        comment=comment.decode('utf-8',errors='replace'), comment_hex=comment.hex()))
    return result


def _timestamp(raw):
    if not _TIME.fullmatch(raw):
        return None
    a, b, c = (int(raw[i:i+2]) for i in (0, 2, 4))
    value = dict(raw=raw, calendar_status='incomplete; no calendar date inferred')
    if raw[-1] in 'z/':
        if not (1 <= a <= 31 and b < 24 and c < 60):
            return None
        value.update(format='day_hour_minute', day=a, hour=b, minute=c,
                     time_basis='UTC' if raw[-1]=='z' else 'local_timezone_unspecified')
    else:
        if not (a < 24 and b < 60 and c < 60):
            return None
        value.update(format='hour_minute_second', hour=a, minute=b, second=c, time_basis='UTC')
    return value


def _coordinate(raw, degrees_count, maximum):
    degrees = int(raw[:degrees_count])
    digits = raw[degrees_count:degrees_count+2]+raw[degrees_count+3:degrees_count+5]
    first_blank = digits.find(' ')
    ambiguity = 0 if first_blank < 0 else len(digits)-first_blank
    if ambiguity and any(c != ' ' for c in digits[first_blank:]):
        return None
    minutes_hundredths = int(digits.replace(' ', '0'))
    if (degrees > maximum or minutes_hundredths >= 6000
            or degrees == maximum and (minutes_hundredths or ambiguity)):
        return None
    value = degrees+minutes_hundredths/6000
    if raw[-1] in 'SW':
        value = -value
    return value, ambiguity


def _outside_comment_telemetry(tail):
    if b'|' not in tail:
        return tail
    first,last=tail.index(b'|'),tail.rindex(b'|')
    end=len(tail) if first==last else last+1
    # Keep offsets and separators: removing bytes could fabricate an annotation
    # by joining text on opposite sides of a telemetry block.
    return tail[:first]+b' '*(end-first)+tail[end:]


def _altitude_annotation(value, tail):
    tail=_outside_comment_telemetry(tail)
    annotations = tail.count(b'/A=')
    if annotations:
        value['altitude_status'] = 'multiple_annotations' if annotations > 1 else 'unsupported_or_malformed_annotation'
        altitude = _ALTITUDE.search(tail)
        if annotations == 1 and altitude:
            feet = int(altitude.group(1))
            value.update(altitude_status='decoded', altitude_ft=feet, altitude_m=feet*.3048,
                         altitude_source='comment_annotation',
                         altitude_reference='not_determined_from_annotation',
                         altitude_annotation=altitude.group(0).decode('ascii'))


def _extensions(value, tail):
    # Weather/DF symbols give this same syntax a different meaning.
    if value['symbol_code'] in ('_', '\\'):
        value['course_speed_status'] = 'not_interpreted_for_weather_or_DF_symbol'
    elif tail[:7] in (b'000/000', b'.../...', b'   /   '):
        value.update(course_speed_status='not_available', course_speed_raw=tail[:7].decode('ascii'))
    else:
        motion = _COURSE_SPEED.match(tail)
        if motion:
            course, speed = map(int, motion.groups())
            value['course_speed_raw'] = tail[:7].decode('ascii')
            value['course_speed_status'] = 'invalid_course' if not 1 <= course <= 360 else 'decoded'
            if 1 <= course <= 360:
                value.update(course_deg=course, speed_knots=speed, speed_m_s=speed*1852/3600)
    _altitude_annotation(value, tail)


def _base91(data):
    value = 0
    for byte in data:
        if not 33 <= byte <= 123:
            return None
        value = value*91+byte-33
    return value


def _compressed_extensions(value, cst):
    if cst[0] == 32:
        value['compressed_extension_status'] = 'not_transmitted; csT ignored'
        return
    c, s, kind = (byte-33 for byte in cst)
    if not (0 <= c <= 90 and 0 <= s <= 90 and 0 <= kind < 64):
        value['compressed_extension_status'] = 'invalid_base91_or_reserved_type_bits'
        return
    source = (kind >> 3) & 3
    value['compression_type'] = dict(raw=chr(cst[2]), value=kind,
        gps_fix_reported='current' if kind & 32 else 'old',
        nmea_source_reported=('other','GLL','GGA','RMC')[source],
        compression_origin_code=kind & 7)
    if source == 2:
        feet = 1.002**(c*91+s)
        value.update(compressed_extension_status='altitude', altitude_status='decoded',
                     altitude_ft=feet, altitude_m=feet*.3048,
                     altitude_source='compressed_csT', altitude_reference='not_determined_from_encoding')
    elif c == 90:
        miles = 2*1.08**s
        value.update(compressed_extension_status='precalculated_radio_range',
                     radio_range_miles=miles, radio_range_m=miles*1609.344,
                     radio_range_scope='transmitted model value, not measured reception range')
    elif value['symbol_code'] in ('_', '\\'):
        value['compressed_extension_status'] = 'not_interpreted_for_weather_or_DF_symbol'
    else:
        speed = 1.08**s-1
        value.update(compressed_extension_status='course_speed', course_speed_status='decoded',
                     course_deg=c*4, speed_knots=speed, speed_m_s=speed*1852/3600)


def _compressed_position(result, data):
    result = dict(result, requested_profile='compressed_station_position', format='compressed')
    if len(data) < 13:
        return dict(result, status='incomplete_compressed_position')
    core, tail = bytes(data[:13]), bytes(data[13:])
    table, symbol = chr(core[0]), chr(core[9])
    result.update(compressed_position_hex=core.hex(), symbol_table=table, symbol_code=symbol,
                  compressed_extension_hex=core[10:13].hex(),
                  comment_and_extensions_hex=tail.hex(), comment_and_extensions=tail.decode('utf-8',errors='replace'))
    if not (table in ('/', '\\') or 'A' <= table <= 'Z' or 'a' <= table <= 'j') or not 33 <= core[9] <= 126:
        return dict(result, status='invalid_symbol')
    if 'a' <= table <= 'j':
        result['symbol_overlay'] = str(ord(table)-ord('a'))
    elif 'A' <= table <= 'Z':
        result['symbol_overlay'] = table
    latitude, longitude = _base91(core[1:5]), _base91(core[5:9])
    if latitude is None or longitude is None:
        return dict(result, status='invalid_base91_coordinates')
    if latitude > 180*380926 or longitude > 360*190463:
        return dict(result, status='invalid_coordinates')
    lat, lon = 90-latitude/380926, -180+longitude/190463
    if lat == 0 and lon == 0 and table == '\\' and symbol == '.':
        return dict(result, status='null_position')
    result.update(status='decoded_position', latitude_deg=lat, longitude_deg=lon,
                  encoded_resolution_degrees={'latitude':1/380926,'longitude':1/190463},
                  coordinate_datum='WGS84 protocol default; not independently verified')
    _compressed_extensions(result, core[10:13])
    # A textual /A= annotation and csT altitude are independent received claims.
    # Preserve both, but choose neither as the main altitude if both occur.
    if b'/A=' in _outside_comment_telemetry(tail) and 'altitude_ft' in result:
        annotation = {}
        _altitude_annotation(annotation, tail)
        result['altitude_candidates'] = [
            {key:result[key] for key in ('altitude_ft','altitude_m','altitude_source','altitude_reference')},
            dict(annotation, altitude_source='comment_annotation')]
        for key in ('altitude_ft','altitude_m','altitude_source','altitude_reference'):
            result.pop(key, None)
        result['altitude_status'] = 'multiple_encodings; no value selected'
    else:
        _altitude_annotation(result, tail)
    return result


def _named_entity(payload):
    kind = 'object' if payload[0] == ord(';') else 'item'
    header = dict(data_type_identifier=chr(payload[0]), requested_profile=kind+'_position',
                  position_subject='named_entity', status='invalid_entity_header',
                  validation_scope='APRS payload syntax only; enclosing AX.25 FCS is separate; named entity and reporting station not independently verified')
    if kind == 'object':
        if len(payload) < 18 or payload[10] not in b'*_':
            return header
        name, marker, position = bytes(payload[1:10]), payload[10], bytes(payload[18:])
        nested = b'@'+bytes(payload[11:18])+position
    else:
        boundary = next((i for i in range(1,min(11,len(payload))) if payload[i] in b'!_'), None)
        if boundary is None or not 4 <= boundary <= 10:
            return header
        name, marker, position = bytes(payload[1:boundary]), payload[boundary], bytes(payload[boundary+1:])
        nested = b'!'+position
    if any(not 32 <= byte <= 126 for byte in name):
        return header
    killed = marker == ord('_')
    header.update(entity=dict(kind=kind, name=name.decode('ascii'), name_hex=name.hex(),
                              marker=chr(marker), state_reported='killed' if killed else 'live'),
                  entity_position_hex=position.hex())
    parsed = _parse_position_report(nested)
    for key in ('timestamp', 'timestamp_raw'):
        if key in parsed:
            header[key] = parsed[key]
    accepted = parsed['status'] in ('decoded_position','ambiguous_position','null_position')
    if killed:
        # A packet may report a withdrawal without authenticating its authority.
        # Retain the source bytes; do not expose an active point or update history.
        return dict(header, status='retracted_entity' if accepted else 'unresolved_entity_retraction',
                    reported_position_status=parsed['status'], reported_position_format=parsed.get('format'))
    if parsed.get('symbol_code') == 'l' and parsed.get('symbol_table') != '/':
        return dict(header, status='unsupported_area_entity', reported_position_status=parsed['status'])
    # The synthetic wrapper DTI must not claim an entity's messaging capability.
    parsed.pop('messaging_capability_reported', None)
    status = parsed['status']
    parsed.update(header, status=status)
    return parsed


def _parse_position_report(payload):
    """Interpret station positions, objects and items; retain raw source elsewhere.

    Uncompressed or base-91 compressed; no Mic-E/NMEA fallback.
    Ambiguous coordinates and the standard null position never produce a point.
    """
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > 256 or payload[0] not in b'!=/@;)':
        return None
    if payload[0] in b';)':
        return _named_entity(payload)
    dti = chr(payload[0])
    result = dict(data_type_identifier=dti, requested_profile='uncompressed_station_position',
                  status='unsupported_or_malformed_position_format',
                  messaging_capability_reported=dti in '=@',
                  validation_scope='APRS payload syntax only; enclosing AX.25 FCS is separate; broadcast position and identity not independently verified')
    offset = 1
    if dti in '/@':
        raw = payload[1:8].decode('ascii', errors='replace')
        stamp = _timestamp(raw)
        if stamp is None:
            return dict(result, status='invalid_timestamp', timestamp_raw=raw)
        result['timestamp'] = stamp
        offset = 8
    else:
        result['timestamp'] = {'status': 'not_transmitted'}
    if len(payload) > offset and not 48 <= payload[offset] <= 57:
        return _compressed_position(result, payload[offset:])
    if len(payload) < offset+19:
        return result
    try:
        core = payload[offset:offset+19].decode('ascii')
    except UnicodeDecodeError:
        return result
    lat, table, lon, symbol = core[:8], core[8], core[9:18], core[18]
    if not _LAT.fullmatch(lat) or not _LON.fullmatch(lon):
        return result
    result.update(format='uncompressed', latitude_raw=lat, longitude_raw=lon,
                  symbol_table=table, symbol_code=symbol)
    if not (table in ('/', '\\') or '0' <= table <= '9' or 'A' <= table <= 'Z') or not 33 <= ord(symbol) <= 126:
        return dict(result, status='invalid_symbol')
    latitude, longitude = _coordinate(lat, 2, 90), _coordinate(lon, 3, 180)
    if latitude is None or longitude is None:
        return dict(result, status='invalid_coordinates')
    lat_value, lat_ambiguity = latitude
    lon_value, lon_ambiguity = longitude
    tail = bytes(payload[offset+19:])
    result['comment_and_extensions_hex'] = tail.hex()
    result['comment_and_extensions'] = tail.decode('utf-8', errors='replace')
    if lon_ambiguity and lon_ambiguity != lat_ambiguity:
        return dict(result, status='inconsistent_position_ambiguity')
    if lat_ambiguity:
        # APRS latitude ambiguity also applies to longitude, even with no
        # longitude blanks. Do not export the apparent precise longitude.
        return dict(result, status='ambiguous_position', position_ambiguity_digits=lat_ambiguity)
    if lat == '0000.00N' and lon == '00000.00W' and table == '\\' and symbol == '.':
        return dict(result, status='null_position')
    result.update(status='decoded_position', latitude_deg=lat_value, longitude_deg=lon_value,
                  encoded_resolution_minutes=.01, coordinate_datum='WGS84 protocol default; not independently verified')
    _extensions(result, tail)
    return result


def parse_aprs_position(payload):
    """Read supported positions and optional station-comment telemetry.

    The comment extension is not assigned to objects/items or unsupported
    position formats. Ambiguous/null station positions may still carry data.
    """
    result=_parse_position_report(payload)
    if (result is None or 'entity' in result
            or result['status'] not in ('decoded_position','ambiguous_position','null_position')):
        return result
    comment=bytes.fromhex(result.get('comment_and_extensions_hex',''))
    extension=parse_aprs_comment_telemetry(comment)
    if extension is not None:
        result['comment_telemetry_status']=extension['status']
        if 'telemetry' in extension:
            result['telemetry']=extension['telemetry']
    return result

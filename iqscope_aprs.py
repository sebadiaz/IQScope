"""Bounded APRS station-position syntax, without identity claims.

The enclosing AX.25 decoder checks FCS before calling this payload parser.
This module alone provides syntax interpretation, not packet validation.
"""
import re

_LAT = re.compile(r'[0-9]{2}[0-9 ]{2}\.[0-9 ]{2}[NS]')
_LON = re.compile(r'[0-9]{3}[0-9 ]{2}\.[0-9 ]{2}[EW]')
_TIME = re.compile(r'[0-9]{6}[zh/]')
_COURSE_SPEED = re.compile(rb'([0-9]{3})/([0-9]{3})')
_ALTITUDE = re.compile(rb'/A=([0-9]{6})(?![0-9])')


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


def _altitude_annotation(value, tail):
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
    if b'/A=' in tail and 'altitude_ft' in result:
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


def parse_aprs_position(payload):
    """Interpret only !, =, /, @ station positions; retain raw source elsewhere.

    Uncompressed or base-91 compressed; no Mic-E/object/NMEA fallback.
    Ambiguous coordinates and the standard null position never produce a point.
    """
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > 256 or payload[0] not in b'!=/@':
        return None
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

"""Bounded APRS uncompressed station-position syntax, without identity claims.

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
    annotations = tail.count(b'/A=')
    if annotations:
        value['altitude_status'] = 'multiple_annotations' if annotations > 1 else 'unsupported_or_malformed_annotation'
        altitude = _ALTITUDE.search(tail)
        if annotations == 1 and altitude:
            feet = int(altitude.group(1))
            value.update(altitude_status='decoded', altitude_ft=feet, altitude_m=feet*.3048,
                         altitude_reference='not_determined_from_annotation',
                         altitude_annotation=altitude.group(0).decode('ascii'))


def parse_aprs_position(payload):
    """Interpret only !, =, /, @ station positions; retain raw source elsewhere.

    No compressed/Mic-E/object/NMEA fallback and no guessed date or reference.
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

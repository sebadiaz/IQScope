"""ADS-B identification, airborne velocity and global airborne CPR from CRC-valid DF17/18 frames.

State is local to one analysis. Times are capture-relative, not UTC. These
fields describe received broadcasts and are not authenticated navigation data.
"""
from copy import deepcopy
import math

MAX_PAIR_AGE_SECONDS = 10.
_DERIVED = ('callsign', 'identification_status', 'cpr', 'latitude_deg',
            'longitude_deg', 'position_evidence', 'velocity')


def mode_s_remainder(frame):
    """Mode S CRC polynomial; excludes address/parity overlays."""
    value = int.from_bytes(frame, 'big')
    for bit in range(len(frame)*8-1, 23, -1):
        if value & (1 << bit):
            value ^= 0x1FFF409 << (bit-24)
    return value & 0xFFFFFF


def _longitude_zones(latitude):
    latitude = abs(latitude)
    if latitude == 0:
        return 59
    if latitude == 87:
        return 2
    if latitude > 87:
        return 1
    argument = 1-(1-math.cos(math.pi/30))/math.cos(math.radians(latitude))**2
    return min(59, math.floor(2*math.pi/math.acos(max(-1., min(1., argument)))))


def _global_position(even, odd, newest_odd):
    ye, xe = even[0]/131072., even[1]/131072.
    yo, xo = odd[0]/131072., odd[1]/131072.
    j = math.floor(59*ye-60*yo+.5)
    latitudes = [6*((j % 60)+ye), (360/59)*((j % 59)+yo)]
    latitudes = [latitude-360 if latitude >= 270 else latitude for latitude in latitudes]
    if any(abs(latitude) > 90 for latitude in latitudes):
        return None
    zones = [_longitude_zones(latitude) for latitude in latitudes]
    if zones[0] != zones[1]:
        return None
    nl = zones[int(newest_odd)]
    m = math.floor(xe*(nl-1)-xo*nl+.5)
    ni = max(nl-int(newest_odd), 1)
    longitude = (360/ni)*((m % ni)+(xo if newest_odd else xe))
    if longitude >= 180:
        longitude -= 360
    return latitudes[int(newest_odd)], longitude


def _callsign(message):
    chars = []
    for shift in range(42, -1, -6):
        value = (message >> shift) & 63
        if 1 <= value <= 26:
            chars.append(chr(64+value))
        elif 48 <= value <= 57:
            chars.append(chr(value))
        elif value == 32:
            chars.append(' ')
        else:
            return None
    return ''.join(chars).strip() or None


def _airborne_velocity(message):
    """Decode TC19 without assuming heading reference or aircraft state."""
    subtype = (message >> 48) & 7
    value = {'subtype': subtype}
    if subtype not in (1, 2, 3, 4):
        return dict(value, status='unsupported_subtype')
    value['status'] = 'decoded'
    scale = 4 if subtype in (2, 4) else 1
    value['speed_resolution_kt'] = scale
    if subtype in (1, 2):
        east_code, north_code = (message >> 32) & 1023, (message >> 21) & 1023
        value['horizontal_kind'] = 'ground_speed'
        if east_code:
            value['east_velocity_kt'] = (east_code-1)*scale*(-1 if (message >> 42) & 1 else 1)
        if north_code:
            value['north_velocity_kt'] = (north_code-1)*scale*(-1 if (message >> 31) & 1 else 1)
        if east_code and north_code:
            east, north = value['east_velocity_kt'], value['north_velocity_kt']
            value['ground_speed_kt'] = math.hypot(east, north)
            value['horizontal_status'] = 'available'
            if east or north:
                value['ground_track_deg'] = math.degrees(math.atan2(east, north)) % 360
                value['ground_track_status'] = 'available'
            else:
                value['ground_track_status'] = 'undefined_at_zero_ground_speed'
        else:
            value['horizontal_status'] = 'partial_components' if east_code or north_code else 'not_available'
            value['ground_track_status'] = 'not_available'
    else:
        value['horizontal_kind'] = 'airspeed'
        value['airspeed_kind'] = 'TAS' if (message >> 31) & 1 else 'IAS'
        air_code = (message >> 21) & 1023
        if air_code:
            value['airspeed_kt'] = (air_code-1)*scale
        value['horizontal_status'] = 'available' if air_code else 'not_available'
        if (message >> 42) & 1:
            value['heading_deg'] = ((message >> 32) & 1023)*360/1024
            value['heading_status'] = 'available'
            # True/magnetic reference requires operational-status/profile
            # context not decoded by this per-message receiver.
            value['heading_reference'] = 'not_determined_from_tc19'
        else:
            value['heading_status'] = 'not_available'
    vertical_code = (message >> 10) & 511
    value['vertical_rate_status'] = 'available' if vertical_code else 'not_available'
    if vertical_code:
        value['vertical_rate_ft_min'] = (vertical_code-1)*64*(-1 if (message >> 19) & 1 else 1)
        value['vertical_rate_source'] = 'barometric' if (message >> 20) & 1 else 'GNSS'
    return value


def enrich_adsb_frames(frames):
    """Return independent enriched records; no state crosses analysis windows.

    Recheck CRC before deriving fields; DF18 only CF0/1 ADS-B formats.
    Pair only TC9-18 airborne barometric
    position messages with identical DF/control/address, opposite parity, valid
    relative times and age <=10 seconds. No surface or local CPR fallback.
    """
    result = deepcopy(frames)
    timed = []
    for index, record in enumerate(result):
        fields = record.setdefault('fields', {})
        for key in _DERIVED:
            fields.pop(key, None)
        try:
            raw = bytes.fromhex(record['hex'])
        except (KeyError, TypeError, ValueError):
            continue
        if len(raw) != 14 or raw[0] >> 3 not in (17, 18) or mode_s_remainder(raw):
            continue
        df = raw[0] >> 3
        if df == 18 and (raw[0] & 7) not in (0, 1):
            continue
        message = int.from_bytes(raw[4:11], 'big')
        tc = message >> 51
        if 1 <= tc <= 4:
            callsign = _callsign(message)
            fields['identification_status'] = 'decoded' if callsign else 'empty_or_reserved_character'
            if callsign:
                fields['callsign'] = callsign
        if tc == 19:
            fields['velocity'] = _airborne_velocity(message)
        if not 9 <= tc <= 18:
            continue
        parity = (message >> 34) & 1
        latitude, longitude = (message >> 17) & 131071, message & 131071
        fields['cpr'] = {'format': 'odd' if parity else 'even',
                         'latitude_code': latitude, 'longitude_code': longitude,
                         'status': 'awaiting_recent_opposite_parity'}
        timestamp = record.get('time_seconds')
        if (not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0):
            fields['cpr']['status'] = 'invalid_capture_time'
            continue
        # DF18 control fields have distinct address semantics. Do not merge
        # these or mix rebroadcast and direct DF17 observations.
        key = (df, raw[0] & 7 if df == 18 else None, raw[1:4])
        timed.append((timestamp, index, key, parity, latitude, longitude))
    cache = {}
    for timestamp, index, key, parity, latitude, longitude in sorted(timed):
        fields = result[index]['fields']
        states = cache.setdefault(key, {})
        states[parity] = (timestamp, latitude, longitude, index)
        other = states.get(1-parity)
        if other is None:
            continue
        if timestamp-other[0] > MAX_PAIR_AGE_SECONDS:
            del states[1-parity]
            continue
        even, odd = states[0], states[1]
        newest_odd = odd[0] > even[0]
        position = _global_position(even[1:3], odd[1:3], newest_odd)
        if position is None:
            fields['cpr']['status'] = 'inconsistent_latitude_zones'
            continue
        fields['latitude_deg'], fields['longitude_deg'] = position
        fields['cpr']['status'] = 'global_airborne_position'
        fields['position_evidence'] = {
            'method': 'global_airborne_cpr',
            'pair_age_seconds': abs(even[0]-odd[0]),
            'even_time_seconds': even[0], 'odd_time_seconds': odd[0],
            'even_sample_start': result[even[3]].get('sample_start'),
            'odd_sample_start': result[odd[3]].get('sample_start'),
            'position_time_seconds': max(even[0], odd[0]),
            'scope': 'derived_from_crc_valid_pair; broadcast not authenticated; no navigation-integrity claim',
        }
    return result

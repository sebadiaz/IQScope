"""ADS-B identification, airborne velocity and global airborne CPR from CRC-valid DF17/18 frames.

State is local to one analysis. Times are capture-relative, not UTC. These
fields describe received broadcasts and are not authenticated navigation data.
"""
from copy import deepcopy
import math

MAX_PAIR_AGE_SECONDS = 10.
_DERIVED = ('callsign', 'identification_status', 'cpr', 'latitude_deg',
            'longitude_deg', 'position_evidence', 'velocity', 'operational_status', 'position_quality',
            'position_integrity', 'position_integrity_pair')


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
    value['velocity_accuracy_code'] = (message >> 43) & 7
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
            # context; a later causal pass can attach a recent TC31 reference.
            value['heading_reference'] = 'not_determined_from_tc19'
        else:
            value['heading_status'] = 'not_available'
    vertical_code = (message >> 10) & 511
    value['vertical_rate_status'] = 'available' if vertical_code else 'not_available'
    if vertical_code:
        value['vertical_rate_ft_min'] = (vertical_code-1)*64*(-1 if (message >> 19) & 1 else 1)
        value['vertical_rate_source'] = 'barometric' if (message >> 20) & 1 else 'GNSS'
    return value


_NAC_P_HORIZONTAL_BOUND_M = {
    1: 18520., 2: 7408., 3: 3704., 4: 1852., 5: 926., 6: 555.6,
    7: 185.2, 8: 92.6, 9: 30., 10: 10., 11: 3.,
}
_NAC_V_HORIZONTAL_BOUND_M_S = {1: 10., 2: 3., 3: 1., 4: .3}
MAX_OPERATIONAL_STATUS_AGE_SECONDS = 10.


def _operational_status(message):
    """Interpret only defined v1/v2 common fields of airborne/surface TC31."""
    subtype = (message >> 48) & 7
    value = {'subtype': subtype}
    if subtype not in (0, 1):
        return dict(value, status='unsupported_subtype')
    version = (message >> 13) & 7
    value['version_code'] = version
    value['environment'] = 'airborne' if subtype == 0 else 'surface'
    value['capability_class_code'] = (message >> 32) & 65535
    value['operational_mode_code'] = (message >> 16) & 65535
    if version not in (1, 2):
        return dict(value, status='unsupported_version')
    value.update(status='decoded', adsb_version=version)
    nac_p = (message >> 8) & 15
    value['nac_p_code'] = nac_p
    value['nac_p_status'] = 'not_available' if nac_p == 0 else 'reserved_code'
    if nac_p in _NAC_P_HORIZONTAL_BOUND_M:
        value['nac_p_status'] = 'reported_bound'
        value['horizontal_accuracy_95_bound_m'] = _NAC_P_HORIZONTAL_BOUND_M[nac_p]
    value['sil_code'] = (message >> 4) & 3
    value['sil_probability_basis'] = ('per_sample' if (message >> 1) & 1 else 'per_hour') if version == 2 else 'not_determined_from_version1'
    value['heading_reference'] = 'magnetic_north' if (message >> 2) & 1 else 'true_north'
    value['nic_supplement_a'] = (message >> 12) & 1
    if subtype == 0:
        value['nic_baro_code'] = (message >> 3) & 1
    if version == 2:
        value['sil_supplement'] = (message >> 1) & 1
    return value


def _airborne_integrity(message, status, evidence):
    """Interpret defined airborne NIC/Rc combinations; keep reserved bits unknown."""
    version, tc = status['adsb_version'], message >> 51
    a, b = status['nic_supplement_a'], (message >> 48) & 1
    value = {'status': 'reserved_combination', 'type_code': tc,
             'adsb_version': version, 'operational_context': evidence.copy(),
             'scope': 'transmitter_declared_NIC_and_containment_bound'}
    fixed = {9:(11,7.5), 10:(10,25.), 12:(7,370.4), 14:(5,1852.),
             15:(4,3704.), 17:(1,37040.), 18:(0,None)}
    if version == 1:
        value['nic_supplement_s'] = a
        variable = {11:((8,185.2),(9,75.)), 13:((6,926.),(6,1111.2)),
                    16:((2,14816.),(3,7408.))}
        if tc in variable:
            category, radius = variable[tc][a]
        elif a == 0 and tc in fixed:
            category, radius = fixed[tc]
        else:
            return value
    elif version == 2:
        value.update(nic_supplement_a=a, nic_supplement_b=b)
        variable = {11:{(0,0):(8,185.2),(1,1):(9,75.)},
                    13:{(0,0):(6,926.),(0,1):(6,555.6),(1,1):(6,1111.2)},
                    16:{(0,0):(2,14816.),(1,1):(3,7408.)}}
        if tc in variable and (a,b) in variable[tc]:
            category, radius = variable[tc][a,b]
        elif tc in fixed and (a,b) == (0,0):
            category, radius = fixed[tc]
        else:
            return value
    else:
        return dict(value, status='unsupported_version')
    value['nic_category'] = category
    value['status'] = 'reported_bound' if radius is not None else 'not_available'
    if radius is not None:
        value['containment_radius_bound_m'] = radius
    return value


def _combine_cpr_integrity(records, pairs):
    """Keep the weakest category and largest radius from two interpreted halves."""
    for index, even_index, odd_index in pairs:
        members = {}
        for parity, source_index in (('even', even_index), ('odd', odd_index)):
            source = records[source_index]
            member = deepcopy(source['fields']['position_integrity'])
            member.update(message_hex=source['hex'], time_seconds=source.get('time_seconds'),
                          sample_start=source.get('sample_start'))
            members[parity] = member
        combined = {'status': 'incomplete_or_uninterpreted_member',
                    'method': 'minimum_NIC_and_maximum_Rc_across_CPR_pair', 'members': members,
                    'scope': 'declared_pair_integrity_not_measured_error_or_authentication'}
        values = list(members.values())
        if all(v['status'] in ('reported_bound', 'not_available') for v in values):
            category = min(v['nic_category'] for v in values)
            combined['nic_category'] = category
            if category == 0:
                combined['status'] = 'not_available'
            else:
                combined['status'] = 'reported_bound'
                combined['containment_radius_bound_m'] = max(v['containment_radius_bound_m'] for v in values)
        records[index]['fields']['position_integrity_pair'] = combined


def _apply_operational_context(records, events):
    """Causal, same-domain, recent airborne status only; never backfill."""
    cache = {}
    for timestamp, index, key, type_code, message in sorted(events):
        fields = records[index]['fields']
        if type_code == 31:
            status = fields['operational_status']
            if status.get('status') == 'decoded' and status.get('environment') == 'airborne':
                cache[key] = (timestamp, index)
            else:
                # A newer surface or unsupported status cancels an old context.
                cache.pop(key, None)
            continue
        previous = cache.get(key)
        if previous is None:
            continue
        status_time, status_index = previous
        age = timestamp-status_time
        if age > MAX_OPERATIONAL_STATUS_AGE_SECONDS:
            cache.pop(key, None)
            continue
        status = records[status_index]['fields']['operational_status']
        evidence = {
            'adsb_version': status['adsb_version'],
            'status_time_seconds': status_time, 'status_age_seconds': age,
            'status_sample_start': records[status_index].get('sample_start'),
            'status_hex': records[status_index]['hex'],
        }
        velocity = fields.get('velocity')
        if velocity and velocity.get('status') == 'decoded':
            velocity['operational_context'] = evidence.copy()
            if 'heading_deg' in velocity:
                velocity['heading_reference'] = status['heading_reference']
            nac_v = velocity['velocity_accuracy_code']
            velocity['nac_v_code'] = nac_v
            velocity['nac_v_status'] = 'not_available' if nac_v == 0 else 'reserved_code'
            if nac_v in _NAC_V_HORIZONTAL_BOUND_M_S:
                velocity['nac_v_status'] = 'reported_bound'
                velocity['horizontal_velocity_error_95_bound_m_s'] = _NAC_V_HORIZONTAL_BOUND_M_S[nac_v]
        if 9 <= type_code <= 18:
            fields['position_integrity'] = _airborne_integrity(message, status, evidence)
        if 'latitude_deg' in fields:
            quality = {
                'nac_p_code': status['nac_p_code'], 'nac_p_status': status['nac_p_status'],
                'sil_code': status['sil_code'], 'sil_probability_basis': status['sil_probability_basis'],
                'operational_context': evidence.copy(),
                'scope': 'transmitter_declared_categories_not_measured_error_or_receiver_validation',
            }
            if 'horizontal_accuracy_95_bound_m' in status:
                quality['horizontal_accuracy_95_bound_m'] = status['horizontal_accuracy_95_bound_m']
            fields['position_quality'] = quality


def enrich_adsb_frames(frames):
    """Return independent enriched records; no state crosses analysis windows.

    Recheck CRC before deriving fields; DF18 only CF0/1 ADS-B formats.
    Pair only TC9-18 airborne barometric
    position messages with identical DF/control/address, opposite parity, valid
    relative times and age <=10 seconds. No surface or local CPR fallback.
    """
    result = deepcopy(frames)
    timed = []
    operational_events = []
    cpr_pairs = []
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
        if tc == 31:
            fields['operational_status'] = _operational_status(message)
        if tc in (19, 31) or 9 <= tc <= 18:
            event_time = record.get('time_seconds')
            if isinstance(event_time, (int, float)) and math.isfinite(event_time) and event_time >= 0:
                domain = (df, raw[0] & 7 if df == 18 else None, raw[1:4])
                operational_events.append((event_time, index, domain, tc, message))
        if not 9 <= tc <= 18:
            continue
        fields['position_integrity'] = {'status': 'operational_context_required', 'type_code': tc}
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
        cpr_pairs.append((index, even[3], odd[3]))
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
    _apply_operational_context(result, operational_events)
    _combine_cpr_integrity(result, cpr_pairs)
    return result

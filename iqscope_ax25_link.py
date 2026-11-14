"""Bounded AX.25 I/S/U inspection without guessing a connection's control mode."""
from iqscope_ax25 import _address_header, parse_ui


def _information_candidate(body, extended):
    size = 2 if extended else 1
    if len(body)<size+1 or len(body)-size-1>256:
        return None
    control = body[:size]
    value = dict(mode='modulo_128' if extended else 'modulo_8', control_hex=control.hex(),
                 n_s=control[0]>>1 if extended else (control[0]>>1)&7,
                 n_r=control[1]>>1 if extended else control[0]>>5,
                 poll_final_bit=bool(control[1]&1) if extended else bool(control[0]&16),
                 pid=body[size], interpretation_status='candidate only; control mode not established')
    if body[size]==255:
        return dict(value, payload_status='PID_escape_not_interpreted',
                    body_after_pid_hex=body[size+1:].hex())
    payload = body[size+1:]
    value['payload_hex'] = payload.hex()
    if body[size]==240:
        value['text'] = ''.join(c if c.isprintable() or c in '\r\n\t' else '\ufffd'
                               for c in payload.decode('utf-8',errors='replace'))
    return value


def parse_link(data):
    """Caller checks FCS. UI remains strict; I layouts never establish session state."""
    ui = parse_ui(data)
    if ui is not None:
        return ui
    header = _address_header(data)
    if header is None:
        return None
    addresses,cursor = header
    if len(data)<=cursor:
        return None
    body = data[cursor:]
    control = body[0]
    if control&0xef==3:
        return None  # A malformed UI must not become an opaque U frame.
    fields = dict(destination=addresses[0], source=addresses[1], via=addresses[2:],
                  control=control, pid=None, payload_hex='', link_body_hex=body.hex(),
                  application_status='not_selected; no link/session state reconstructed')
    if not control&1:
        candidates = [v for mode in (False,True) if (v:=_information_candidate(body,mode)) is not None]
        if not candidates:
            return None
        return dict(fields, frame_type='I', control_mode_status='not_established',
                    control_candidates=candidates)
    if control&3==1:
        kind = ('RR','RNR','REJ','SREJ')[(control>>2)&3]
        if len(body)==1:
            return dict(fields, frame_type='S', supervisory_function=kind,
                        control_mode_status='single_octet_supervisory_layout', control_mode='modulo_8',
                        n_r=control>>5, poll_final_bit=bool(control&16))
        if len(body)==2 and not control&0xf0:
            return dict(fields, frame_type='S', supervisory_function=kind,
                        control_mode_status='two_octet_supervisory_layout', control_mode='modulo_128',
                        n_r=body[1]>>1, poll_final_bit=bool(body[1]&1))
        return None  # Extended SREJ information lists are outside this profile.
    kind = {0x2f:'SABM',0x6f:'SABME',0x43:'DISC',0x63:'UA',0x0f:'DM',
            0x87:'FRMR',0xaf:'XID',0xe3:'TEST'}.get(control&0xef)
    if kind is None or len(body)>257:
        return None
    if kind in ('SABM','SABME','DISC','UA','DM') and len(body)!=1:
        return None
    if kind=='FRMR' and len(body) not in (4,6):
        return None
    return dict(fields, frame_type='U', unnumbered_function=kind,
                control_mode_status='unnumbered_layout_only; does not establish observed link state',
                poll_final_bit=bool(control&16), link_information_hex=body[1:].hex())

import unittest

from iqscope_ax25 import decode_ax25, parse_ui
from iqscope_ax25_link import parse_link
from test_ax25 import with_fcs, hdlc, candidate, frame

HEADER = bytes.fromhex('82a0a4a64040609c608682989863')


def packet(body):
    return with_fcs(HEADER+body)


class Ax25LinkTests(unittest.TestCase):
    def test_i_mode_hypotheses_never_select_application_content(self):
        raw=packet(b'\x44\xf0; example\r')
        fields=parse_link(raw[:-2])
        self.assertEqual(fields['frame_type'],'I')
        self.assertIsNone(fields['pid'])
        self.assertEqual(fields['payload_hex'],'')
        self.assertNotIn('text',fields)
        normal,extended=fields['control_candidates']
        self.assertEqual((normal['n_s'],normal['n_r'],normal['pid']),(2,2,240))
        self.assertEqual(normal['text'],'; example\r')
        self.assertEqual((extended['n_s'],extended['n_r'],extended['pid']),(34,120,59))
        self.assertIsNone(parse_ui(raw[:-2]))
        self.assertEqual(decode_ax25([candidate(hdlc(raw))])['frames'],[])
        accepted=decode_ax25([candidate(hdlc(raw))],allow_link_frames=True)['frames']
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]['decoder'],'ax25_link')

    def test_short_supervisory_and_extended_supervisory_layouts(self):
        for body,mode in ((b'\xb1','modulo_8'),(b'\x01\x0b','modulo_128')):
            raw=packet(body)
            fields=parse_link(raw[:-2])
            self.assertEqual((fields['frame_type'],fields['supervisory_function']),('S','RR'))
            self.assertEqual((fields['control_mode'],fields['n_r'],fields['poll_final_bit']),(mode,5,True))
            result=decode_ax25([candidate(hdlc(raw))],allow_link_frames=True)
            self.assertEqual(len(result['frames']),1,result)
            self.assertTrue(result['frames'][0]['fcs_valid'])
        self.assertEqual(len(packet(b'\xb1')),17)
        self.assertIsNone(parse_link(HEADER+b'\x61\x00'))
        self.assertIsNone(parse_link(HEADER+b'\x01\x00\x00'))

    def test_unnumbered_commands_do_not_establish_a_session(self):
        for octet,kind in ((0x3f,'SABM'),(0x6f,'SABME'),(0x43,'DISC'),(0x63,'UA'),(0x0f,'DM')):
            fields=parse_link(HEADER+bytes([octet]))
            self.assertEqual((fields['frame_type'],fields['unnumbered_function']),('U',kind))
            self.assertIn('does not establish',fields['control_mode_status'])
            self.assertIsNone(parse_link(HEADER+bytes([octet])+b'x'))
        self.assertEqual(parse_link(HEADER+b'\xe3<test>')['link_information_hex'],b'<test>'.hex())
        self.assertIsNone(parse_link(HEADER+b'\x87xx'))
        self.assertEqual(parse_link(HEADER+b'\x87xxx')['unnumbered_function'],'FRMR')

    def test_ui_retains_existing_parser_and_rejects_malformed_headers(self):
        raw=frame(b'>unchanged')
        self.assertEqual(parse_link(raw[:-2]),parse_ui(raw[:-2]))
        self.assertIsNone(parse_link(HEADER+b'\x03'))
        self.assertIsNone(parse_link(bytes([HEADER[0]|1])+HEADER[1:]+b'\xb1'))

    def test_link_frames_still_require_the_original_fcs(self):
        raw=packet(b'\x44\xf0example')
        damaged=raw[:-1]+bytes([raw[-1]^1])
        self.assertEqual(decode_ax25([candidate(hdlc(damaged))],allow_link_frames=True)['frames'],[])

    def test_escaped_pid_is_preserved_without_an_invented_payload(self):
        fields=parse_link(HEADER+b'\x00\xff\x23data')
        normal=fields['control_candidates'][0]
        self.assertEqual(normal['payload_status'],'PID_escape_not_interpreted')
        self.assertNotIn('payload_hex',normal)
        self.assertEqual(normal['body_after_pid_hex'],b'\x23data'.hex())

    def test_control_layouts_and_information_lengths_are_bounded(self):
        self.assertIsNone(parse_link(HEADER+b'\x00'))
        self.assertIsNone(parse_link(HEADER+b'\x00\xf0'+b'x'*258))
        fields=parse_link(HEADER+b'\x00\xf0'+b'x'*257)
        self.assertEqual([c['mode'] for c in fields['control_candidates']],['modulo_128'])

    def test_i_payload_looking_like_aprs_does_not_get_position_semantics(self):
        fields=parse_link(HEADER+b'\x00\xf0!4903.50N/07201.75W>')
        self.assertNotIn('aprs',fields)
        self.assertNotIn('aprs',fields['control_candidates'][0])
        self.assertTrue(fields['control_candidates'][0]['text'].startswith('!49'))

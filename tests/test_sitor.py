"""Independent ITU emitted-signal fixtures and explicit two-copy error cases."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from iqscope_sitor import LETTERS,FIGURES,SHARED,VALID,_text,_navtex,search_sitor,write_sitor_artifacts

TEXT='ZCZC QA00\r\nTEST 123\r\nNNNN\r\n'
# ITU-R M.476-5 Table 1: literal emitted B/Y signals, first element first.
EMITTED=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',('BBBYYYB','YBYYBBB','BYBBBYY','BBYYBYB','YBBYBYB',
    'BBYBBYY','BYBYBBY','BYYBYBB','BYBBYYB','BBBYBYY','YBBBBYY','BYBYYBB','BYYBBBY',
    'BYYBBYB','BYYYBBB','BYBBYBY','YBBBYBY','BYBYBYB','BBYBYYB','YYBYBBB','YBBBYYB',
    'YYBBBBY','BBBYYBY','YBYBBBY','BBYBYBY','BBYYYBB')))
OTHER={'\r':'YYYBBBB','\n':'YYBBYBB',' ':'YYBBBYB','LTRS':'YBYBBYB','FIGS':'YBBYBBY'}
NUMBERS=dict(zip('1234567890','QWERTYUIOP'))


def value(pattern):return sum((bit=='B')<<index for index,bit in enumerate(pattern))


def encode_text(text):
    mode='letters';codes=[value(OTHER['LTRS'])]
    for char in text:
        if char in OTHER:codes.append(value(OTHER[char]));continue
        target='figures' if char in NUMBERS else 'letters'
        if target!=mode:codes.append(value(OTHER['FIGS' if target=='figures' else 'LTRS']));mode=target
        codes.append(value(EMITTED[NUMBERS[char] if target=='figures' else char]))
    return codes


def fixture(fs=1953,offset=0,ppm=0,inverted=False,changes=None,text=TEXT,preamble=12,repeat_delay=2):
    data=encode_text(text);direct=[0x66]*preamble+data+[0x66]*3;wire=[]
    for index,code in enumerate(direct):
        old=direct[index-repeat_delay] if index>=repeat_delay else 0x66
        wire.extend([code,0x0f if old==0x66 else old])
    for position,mask in (changes or {}).items():wire[position]^=mask
    bits=np.array([int(bit) for code in wire for bit in f'{code:07b}'[::-1]])
    baud=100*(1+ppm*1e-6);n=int(len(bits)*fs/baud)
    indices=np.clip(np.floor((np.arange(n)-.37)*baud/fs).astype(int),0,len(bits)-1)
    frequency=offset+85*(2*bits[indices]-1)
    x=np.exp(2j*np.pi*np.cumsum(frequency)/fs)
    if inverted:x=x.conj()
    rng=np.random.default_rng(476);x+=.002*(rng.normal(size=n)+1j*rng.normal(size=n))
    return x,fs,wire


class SITORTests(unittest.TestCase):
    def test_primary_table_and_five_symbol_repetition_interval(self):
        self.assertEqual({value(p):c for c,p in EMITTED.items()},LETTERS)
        self.assertEqual(int(VALID.sum()),35)
        self.assertEqual(FIGURES[value(EMITTED['Q'])],'1')
        self.assertEqual(SHARED[value(OTHER['\r'])],'\r')
        _,_,wire=fixture()
        self.assertEqual(wire[:12],[0x66,0x0f]*6)
        for i in range(24,len(wire)-5,2):
            if wire[i]!=0x66:self.assertEqual(wire[i],wire[i+5])

    def test_iq_recovers_complete_navtex_header_serial_zero_and_text(self):
        x,fs,wire=fixture();trial=search_sitor(x,fs)
        self.assertGreaterEqual(len(trial['candidates']),1)
        for extra in trial['candidates'][1:]:
            if extra['text']==trial['candidates'][0]['text']:self.assertEqual(extra['same_text_as_candidate_index'],0)
        candidate=trial['candidates'][0]
        self.assertEqual(candidate['text'],TEXT)
        message=trial['messages'][0]
        self.assertEqual((message['station_designator'],message['subject_designator'],message['serial_text']),('Q','A','00'))
        self.assertEqual(message['serial'],0)
        self.assertTrue(message['framing_complete']);self.assertTrue(message['text_interpretation_complete'])
        self.assertEqual(candidate['parameters']['repeat_delay_symbols'],5)
        self.assertNotIn('frames',trial)
        self.assertTrue(all(s['time_seconds']>=0 for s in candidate['received_symbols']))

    def test_sample_rates_translation_inversion_and_clock_error(self):
        for fs,offset,ppm,inverted in [(1935,70,80,True),(8000,-1100,-100,False),(192000,23000,50,False)]:
            x,_,_=fixture(fs=fs,offset=offset,ppm=ppm,inverted=inverted)
            with self.subTest(fs=fs):
                trial=search_sitor(x,fs,center_hz=518000)
                self.assertEqual(trial['messages'][0]['text'],TEXT)
                self.assertAlmostEqual(trial['candidates'][0]['channel']['offset_hz'],-offset if inverted else offset,delta=30)

    def test_invalid_copy_recovery_preserves_raw_word_and_valid_conflict_is_erasure(self):
        # First Z occupies direct slot 26 and repeated slot 31 after phasing/LTRS.
        for changes,decision in [({26:1},'repeated_copy_only'),({31:1},'direct_copy_only')]:
            x,fs,_=fixture(changes=changes);trial=search_sitor(x,fs)
            self.assertEqual(trial['messages'][0]['text'],TEXT)
            event=next(e for e in trial['candidates'][0]['characters'] if e['decision']==decision)
            self.assertEqual(event['selected_code'],value(EMITTED['Z']))
            self.assertIn(value(EMITTED['Z'])^1,(event['direct_code'],event['repeat_code']))
        x,fs,_=fixture(changes={26:value(EMITTED['Z'])^value(EMITTED['C'])})
        trial=search_sitor(x,fs);events=trial['candidates'][0]['characters']
        event=next(e for e in events if e['decision']=='valid_copy_conflict')
        self.assertIsNone(event['selected_code']);self.assertEqual(event['decoded_status'],'erasure')
        self.assertFalse(trial['messages'])

    def test_unknown_shift_and_unframed_header_do_not_invent_message_contents(self):
        codes=[0x5a,value(EMITTED['A']),None,value(EMITTED['E']),0x36,value(EMITTED['Q']),0x5a,value(EMITTED['Z'])]
        events=[dict(selected_code=c) for c in codes]
        self.assertEqual(_text(events),'A\ufffd\ufffd1Z')
        self.assertEqual(events[3]['decoded_status'],'unknown_shift')
        self.assertFalse(_navtex('PREFIX'+TEXT,[])[0])
        partial=_navtex(TEXT.split('NNNN')[0],[])[0][0]
        self.assertFalse(partial['framing_complete']);self.assertEqual(partial['termination'],'window_end')

    def test_noise_tones_wrong_baud_wrong_repeat_and_insufficient_diversity_rejected(self):
        fs=1953;t=np.arange(fs*5)/fs;rng=np.random.default_rng(4)
        for x in [np.zeros(len(t),complex),np.exp(2j*np.pi*85*t),
                  rng.normal(size=len(t))+1j*rng.normal(size=len(t)),
                  np.exp(2j*np.pi*np.cumsum(85*np.sign(np.sin(2*np.pi*70*t)))/fs)]:
            self.assertFalse(search_sitor(x,fs)['candidates'])
        x,fs,_=fixture(text='EEEEEEEEEEEEEEEEEEEEEEEE')
        self.assertFalse(search_sitor(x,fs)['candidates'])
        x,fs,_=fixture(ppm=50000)
        self.assertFalse(search_sitor(x,fs)['candidates'])
        x,fs,_=fixture(repeat_delay=3)
        self.assertFalse(search_sitor(x,fs)['candidates'])

    def test_budgets_and_symbol_text_json_artifacts(self):
        x,fs,_=fixture();self.assertFalse(search_sitor(x,fs,max_channels=0)['candidates'])
        self.assertTrue(search_sitor(x,fs,max_seconds=4)['duration_limited'])
        self.assertEqual(search_sitor(x.real,fs)['status'],'not_applicable')
        trial=search_sitor(x,fs)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);write_sitor_artifacts(trial,out)
            self.assertEqual(json.loads((out/trial['artifact']).read_text()),trial)
            c=trial['candidates'][0]
            self.assertEqual((out/c['symbols_artifact']).read_bytes(),bytes(s['code'] for s in c['received_symbols']))
            self.assertEqual((out/c['text_artifact']).read_bytes(),TEXT.encode())
            self.assertEqual((out/trial['messages'][0]['artifact']).read_bytes(),TEXT.encode())


if __name__=='__main__':unittest.main()

"""Declared APRS telemetry calibration, timing, isolation and actual receivers."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from iqscope_aprs_calibration import parse_aprs_definition, enrich_aprs_telemetry_frames as enrich
from iqscope_ax25 import decode_ax25, decode_psk_ax25, parse_ui
from test_ax25 import frame, hdlc, candidate
from test_aprs_telemetry import SAMPLE

PARM=b':N0CALL-1 :PARM.Battery,Btemp,ATemp,Pres,Alt,Camra,Chut,Sun,10m,ATV'
UNIT=b':N0CALL-1 :UNIT.v/100,deg.F,deg.F,Mbar,Kft,Click,OPEN,on,on,hi'
EQNS=b':N0CALL-1 :EQNS.0,5.2,0,0,.53,-32,3,4.39,49,-32,3,18,1,2,3'
BITS=b':N0CALL-1 :BITS.10110000,Balloon <b>'
DEFINITIONS=[PARM,UNIT,EQNS,BITS]
PAYLOADS=[SAMPLE,*DEFINITIONS,SAMPLE]


def report(payload,start=1,end=None,source='N0CALL',ssid=1,frequency=1000):
    packet=frame(payload=payload)
    fields=parse_ui(packet[:-2]);fields['source']=dict(fields['source'],callsign=source,ssid=ssid)
    return dict(hex=packet.hex(),fields=fields,fcs_valid=True,time_seconds=start,
                time_end_seconds=start+.5 if end is None else end,candidate_index=0,
                channel={'frequency_hz':frequency})


def associated(extra=(),sample_time=10):
    return enrich([*(report(p,i) for i,p in enumerate(DEFINITIONS)),*extra,report(SAMPLE,sample_time)])[-1]['fields']['aprs']['telemetry']


def stream_bits(payloads=PAYLOADS):
    return ''.join(hdlc(frame(payload=p)) for p in payloads)


def receiver_fixture(kind='audio',payloads=PAYLOADS):
    bits=stream_bits(payloads);state=0;states=[]
    for bit in bits:
        state ^= int(bit=='0');states.append(state)
    fs=8000 if kind=='audio' else 24000
    indices=np.floor((np.arange(int(len(bits)*fs/1200))-2.3)*1200/fs).astype(int)
    keyed=np.asarray(states)[np.clip(indices,0,len(states)-1)]
    frequency=np.where(keyed,2200,1200) if kind=='audio' else 210+(2*keyed-1)*2400
    phase=2*np.pi*np.cumsum(frequency)/fs
    rng=np.random.default_rng(741)
    values=.7*np.cos(phase)+.01*rng.normal(size=len(phase)) if kind=='audio' else np.exp(1j*phase)+.01*(rng.normal(size=len(phase))+1j*rng.normal(size=len(phase)))
    return values,fs


class AprsCalibrationTests(unittest.TestCase):
    def test_published_definition_syntax_and_exact_unit_labels(self):
        for payload,kind in zip(DEFINITIONS,('PARM','UNIT','EQNS','BITS')):
            value=parse_aprs_definition(payload)
            self.assertEqual(value['status'],'decoded_telemetry_definition')
            self.assertEqual(value['definition']['kind'],kind)
            self.assertEqual(value['definition']['target'],dict(callsign='N0CALL',ssid=1))
        self.assertEqual(parse_aprs_definition(UNIT)['definition']['values'][0],'v/100')

    def test_partial_coefficients_empty_labels_and_message_identifier(self):
        value=parse_aprs_definition(b':N0CALL-1 :EQNS.-1,.5,2,9,4{A1')['definition']
        self.assertEqual(value['coefficients'],[[-1,.5,2],None,None,None,None])
        self.assertEqual(value['message_id'],'A1')
        self.assertEqual(parse_aprs_definition(b':N0CALL-1 :PARM.,B,,')['definition']['values'],['','B','',''])

    def test_invalid_definition_syntax_targets_and_widths(self):
        for payload in (b':N0CALL-1 :PARM.ToolongXx',b':N0CALL-1 :PARM.'+b','.join([b'X']*14),
                        b':N0CALL-1 :UNIT.V|olt',b':N0CALL-1 :EQNS.0,NaN,0',b':N0CALL-1 :EQNS.0,1e999,0',
                        b':N0CALL-1 :EQNS.0,,0',b':N0CALL-1 :EQNS.'+b','.join([b'0']*16),
                        b':N0CALL-1 :PARM.X{bad-id',b':N0CALL-1 :PARM.X{123456',
                        b':N0CALL-16:PARM.X',b':n0call-1 :PARM.X',b': N0CALL-1:PARM.X',
                        b':N0CALL-1 :UNIT.\xff'):
            value=parse_aprs_definition(payload)
            self.assertEqual(value['status'],'invalid_telemetry_definition',payload)
        for payload in (b'',SAMPLE,b':N0CALL-1 :hello',b':N0CALL-1 :parm.X',None):
            self.assertIsNone(parse_aprs_definition(payload))
        self.assertIsNone(parse_aprs_definition(PARM+b'x'*256))

    def test_bit_sense_project_title_and_binary_validation(self):
        value=parse_aprs_definition(BITS)['definition']
        self.assertEqual(value['sense_bits'],[1,0,1,1,0,0,0,0])
        self.assertEqual(value['project_title'],'Balloon <b>')
        for text in (b'1011000',b'10110002',b'10110000x',b'10110000,'+b'x'*24):
            self.assertEqual(parse_aprs_definition(b':N0CALL-1 :BITS.'+text)['status'],'invalid_telemetry_definition')

    def test_published_polynomial_values_keep_raw_and_unit_without_si_guessing(self):
        t=associated()
        self.assertEqual(t['analog_raw'],[199,0,255,73,123])
        first=t['analog_channels'][0]
        self.assertEqual(first['name'],'Battery')
        self.assertEqual(first['unit'],'v/100')
        self.assertAlmostEqual(first['value'],1034.8)
        self.assertNotEqual(first['value'],10.348)
        self.assertEqual(t['analog_channels'][1]['value'],-32)
        self.assertEqual(t['digital_channels'][0]['label'],'Click')
        self.assertFalse(t['digital_channels'][0]['matches_declared_sense'])
        self.assertTrue(t['digital_channels'][2]['matches_declared_sense'])
        self.assertEqual(t['project_title'],'Balloon <b>')
        self.assertEqual(set(t['definition_context']['definitions']),{'PARM','UNIT','EQNS','BITS'})
        self.assertEqual(t['definition_context']['definitions']['EQNS']['frame_index'],2)

    def test_future_overlapping_and_equal_end_definition_is_not_applied(self):
        sample=report(SAMPLE,10)
        for start,end in ((10,11),(9,11),(9,10)):
            output=enrich([report(EQNS,start,end),sample])
            self.assertNotIn('analog_channels',output[1]['fields']['aprs']['telemetry'])
        t=enrich([report(EQNS,9,9.999),sample])[1]['fields']['aprs']['telemetry']
        self.assertAlmostEqual(t['analog_channels'][0]['value'],1034.8)

    def test_source_ssid_target_channel_frontend_and_candidate_isolation(self):
        for change in (dict(source='SECOND'),dict(ssid=2),dict(frequency=2000)):
            output=enrich([report(EQNS,1,**change),report(SAMPLE,10)])
            self.assertNotIn('analog_channels',output[1]['fields']['aprs']['telemetry'])
        for modifier in ('frontend','candidate_index'):
            a=report(EQNS,1);b=report(SAMPLE,10)
            if modifier=='frontend':a['frontend']='bpsk_g3ruh'
            else:a['channel']=b['channel']=None;a['candidate_index']=2
            self.assertNotIn('analog_channels',enrich([a,b])[1]['fields']['aprs']['telemetry'])
        t=enrich([report(EQNS.replace(b'N0CALL-1 ',b'SECOND   '),1),report(SAMPLE,10)])[1]['fields']['aprs']['telemetry']
        self.assertNotIn('analog_channels',t)

    def test_expiry_is_per_definition_type_without_refreshing_old_coefficients(self):
        rows=[report(EQNS,0),report(UNIT,595),report(SAMPLE,600.5),report(SAMPLE,600.501)]
        a,b=[f['fields']['aprs']['telemetry'] for f in enrich(rows)[2:]]
        self.assertIn('value',a['analog_channels'][0])
        self.assertNotIn('value',b['analog_channels'][0])
        self.assertEqual(b['analog_channels'][0]['unit'],'v/100')
        self.assertEqual(b['definition_context']['excluded_definitions']['EQNS'],'expired')

    def test_conflicting_equal_time_definitions_block_and_later_update_recovers(self):
        a=report(EQNS,1);b=report(EQNS.replace(b'5.2',b'6.2'),1)
        output=enrich([a,b,report(SAMPLE,10),report(EQNS,11),report(SAMPLE,12)])
        self.assertNotIn('analog_channels',output[2]['fields']['aprs']['telemetry'])
        self.assertEqual(output[2]['fields']['aprs']['telemetry']['definition_context']['excluded_definitions']['EQNS'],'conflicting_equal_time_definitions')
        self.assertIn('value',output[4]['fields']['aprs']['telemetry']['analog_channels'][0])
        same=enrich([a,deepcopy(a),report(SAMPLE,10)])
        self.assertIn('value',same[2]['fields']['aprs']['telemetry']['analog_channels'][0])

    def test_malformed_and_partial_replacements_do_not_backfill_old_slots(self):
        for payload in (b':N0CALL-1 :EQNS.0,bad,0',b':N0CALL-1 :EQNS.1,2'):
            t=associated([report(payload,8)])
            if 'analog_channels' in t:self.assertNotIn('value',t['analog_channels'][0])
        t=associated([report(b':N0CALL-1 :PARM.X',8),report(b':N0CALL-1 :UNIT.',8.5)])
        self.assertEqual(t['analog_channels'][0]['name'],'X')
        self.assertNotIn('name',t['analog_channels'][1])
        self.assertNotIn('unit',t['analog_channels'][0])
        self.assertNotIn('label',t['digital_channels'][0])

    def test_names_units_and_coefficients_are_independently_optional(self):
        for payload,field in ((PARM,'name'),(UNIT,'unit'),(EQNS,'value')):
            t=enrich([report(payload,1),report(SAMPLE,10)])[1]['fields']['aprs']['telemetry']
            self.assertIn(field,t['analog_channels'][0])
            if payload!=EQNS:self.assertNotIn('value',t['analog_channels'][0])
            if payload!=UNIT:self.assertNotIn('unit',t['analog_channels'][0])
        t=enrich([report(BITS,1),report(SAMPLE,10)])[1]['fields']['aprs']['telemetry']
        self.assertIn('matches_declared_sense',t['digital_channels'][0])
        self.assertNotIn('label',t['digital_channels'][0])

    def test_immutability_idempotence_ordering_and_no_state_between_calls(self):
        source=[report(SAMPLE,10),report(EQNS,1),report(PARM,2)]
        before=deepcopy(source);output=enrich(source)
        self.assertEqual(source,before)
        self.assertEqual(output,enrich(output))
        self.assertEqual([f['time_seconds'] for f in output],[10,1,2])
        self.assertIn('value',output[0]['fields']['aprs']['telemetry']['analog_channels'][0])
        self.assertNotIn('analog_channels',enrich([report(SAMPLE,10)])[0]['fields']['aprs']['telemetry'])

    def test_stale_derived_values_are_cleared_and_raw_values_reparsed(self):
        sample=report(SAMPLE,10)
        sample['fields']['aprs']['telemetry'].update(analog_raw=[9]*5,analog_channels=[{'value':999}],project_title='stale')
        t=enrich([sample])[0]['fields']['aprs']['telemetry']
        self.assertEqual(t['analog_raw'],[199,0,255,73,123])
        self.assertNotIn('analog_channels',t)
        self.assertNotIn('project_title',t)

    def test_bad_crc_pid_and_nonfinite_timing_cannot_supply_metadata(self):
        for key,value in (('fcs_valid',False),('time_seconds',float('nan')),('time_end_seconds',float('inf')),('time_seconds',-1)):
            definition=report(EQNS,1);definition[key]=value
            t=enrich([definition,report(SAMPLE,10)])[1]['fields']['aprs']['telemetry']
            self.assertNotIn('analog_channels',t)
        definition=report(EQNS,1);definition['fields']['pid']=0xCF
        self.assertNotIn('analog_channels',enrich([definition,report(SAMPLE,10)])[1]['fields']['aprs']['telemetry'])
        sample=report(SAMPLE,10);sample['time_end_seconds']=None
        self.assertNotIn('analog_channels',enrich([report(EQNS,1),sample])[1]['fields']['aprs']['telemetry'])

    def test_overflow_has_no_nonfinite_value_in_json(self):
        t=associated([report(b':N0CALL-1 :EQNS.1e308,0,0',8)])
        self.assertNotIn('value',t['analog_channels'][0])
        self.assertEqual(t['analog_channels'][0]['value_status'],'non_finite_result; no value selected')
        json.dumps(t,allow_nan=False)

    def test_zero_ssid_canonicalization_and_age_budget_validation(self):
        for target in (b'N0CALL   ',b'N0CALL-0 '):
            definition=report(b':'+target+b':EQNS.0,1,0',1,ssid=0)
            t=enrich([definition,report(SAMPLE,10,ssid=0)])[1]['fields']['aprs']['telemetry']
            self.assertEqual(t['analog_channels'][0]['value'],199)
        for budget in (-1,float('inf'),True,3601,'600'):
            with self.assertRaises(ValueError):enrich([],budget)

    def test_actual_iq_and_audio_receivers_associate_only_later_samples(self):
        from iqscope import analyze_samples
        from iqscope_afsk import decode_afsk1200
        audio,fs=receiver_fixture()
        frames=decode_afsk1200(audio,fs)['frames']
        self.assertEqual(len(frames),6)
        self.assertNotIn('analog_channels',frames[0]['fields']['aprs']['telemetry'])
        self.assertAlmostEqual(frames[-1]['fields']['aprs']['telemetry']['analog_channels'][0]['value'],1034.8)
        iq,fs=receiver_fixture('iq')
        with tempfile.TemporaryDirectory() as directory:
            result=analyze_samples(iq,fs,0,directory)
            frames=next(t for t in result['wideband_trials'] if t['decoder']=='ax25_ui')['frames']
            self.assertTrue(any(f['fields'].get('aprs',{}).get('telemetry',{}).get('analog_channels') for f in frames))

    def test_bpsk_descrambling_preserves_association_and_provenance(self):
        state=register=0;encoded=[]
        for bit in stream_bits():
            state ^= int(bit=='0');output=state^((register>>11)&1)^((register>>16)&1)
            encoded.append(str(output));register=((register<<1)|output)&0x1ffff
        c=candidate(''.join(encoded));c['modulation']='BPSK'
        frames=decode_psk_ax25([c])['frames']
        self.assertEqual(len(frames),6)
        t=frames[-1]['fields']['aprs']['telemetry']
        self.assertAlmostEqual(t['analog_channels'][0]['value'],1034.8)
        self.assertEqual(t['definition_context']['definitions']['EQNS']['frame_hex'],frames[3]['hex'])

    def test_received_end_includes_closing_flag_and_precedes_next_report(self):
        frames=decode_ax25([candidate(stream_bits())])['frames']
        self.assertEqual(len(frames),6)
        for a,b in zip(frames,frames[1:]):
            self.assertGreater(a['time_end_seconds'],a['time_seconds'])
            self.assertLess(a['time_end_seconds'],b['time_seconds'])
        flag='01111110'
        shared=flag+hdlc(frame(payload=EQNS))[80:-80]+flag+hdlc(frame(payload=SAMPLE))[80:-80]+flag
        joined=decode_ax25([candidate(shared)])['frames']
        self.assertEqual(len(joined),2)
        self.assertAlmostEqual(joined[1]['time_seconds']-joined[0]['time_end_seconds'],.5/1200)
        self.assertAlmostEqual(joined[1]['fields']['aprs']['telemetry']['analog_channels'][0]['value'],1034.8)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_wav_import_exports_declared_values_and_provenance_without_rf_center(self):
        from iqscope_audio import analyze_audio
        audio,fs=receiver_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wave=root/'calibration.wav';wavfile.write(wave,fs,audio.astype(np.float32))
            result=analyze_audio(wave,root/'out')
            self.assertIsNone(result['center_frequency_hz'])
            frames=next(t for t in result['wideband_trials'] if t['decoder']=='afsk1200_ax25')['frames']
            self.assertEqual(len(frames),6)
            self.assertEqual(json.loads((root/'out'/result['frame_artifact']).read_text())['frames'],frames)
            self.assertAlmostEqual(frames[-1]['fields']['aprs']['telemetry']['analog_channels'][0]['value'],1034.8)


if __name__=='__main__':
    unittest.main()

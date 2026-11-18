"""Published AIS payloads and independently generated Gaussian MSK waveforms."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy import signal

from iqscope_ais import parse_ais,checked_ais_packet,search_ais,write_ais_artifacts
from test_ax25 import with_fcs

# GPSD AIVDM examples, independently checked with pyais 3.3.1. No RF oracle.
# https://gpsd.gitlab.io/gpsd/AIVDM.html and GPSD test/sample.aivdm (Kurt Schwehr).
POSITION='177KQJ5000G?tO`K>RA1wUbN0TKH'
BASE='403OviQuMGCqWrRO9>E6fE700@GO'


def unarmor(text):
    bits=''
    for c in text:
        value=ord(c)-48
        if value>40:value-=8
        bits+=f'{value:06b}'
    return int(bits,2).to_bytes(len(bits)//8,'big')


PAYLOAD=unarmor(POSITION)
PACKET=with_fcs(PAYLOAD)


def changed(payload,start,width,value):
    bits=list(''.join(f'{b:08b}' for b in payload));bits[start:start+width]=f'{value%(1<<width):0{width}b}'
    return int(''.join(bits),2).to_bytes(len(bits)//8,'big')


def fixture(fs=48000,offset=0,cfo=0,baud=9600,inverted=False,bad=False,repeats=1):
    packet=PACKET if not bad else PACKET[:-3]+bytes([PACKET[-3]^4])+PACKET[-2:]
    stuffed=[];ones=0
    for bit in ''.join(f'{b:08b}'[::-1] for b in packet):
        stuffed.append(int(bit));ones=ones+1 if bit=='1' else 0
        if ones==5:stuffed.append(0);ones=0
    bits=[1]*8+[0,1]*12+[0,1,1,1,1,1,1,0]+stuffed+[0,1,1,1,1,1,1,0]+[1]*8
    state=0;tones=[]
    for bit in bits:
        if not bit:state^=1
        tones.append(2*state-1)
    count=int(len(tones)*fs/baud)
    indices=np.floor((np.arange(count)-.37)*baud/fs).astype(int)
    levels=np.array(tones)[np.clip(indices,0,len(tones)-1)]
    # Integrate an independently shaped NRZI frequency pulse; AIS h=0.5, BT=.4.
    half=math_ceil(4*fs/baud);t=np.arange(-half,half+1)*baud/fs
    gaussian=np.exp(-2*(np.pi*.4*t)**2/np.log(2));gaussian/=gaussian.sum()
    shaped=signal.convolve(np.pad(levels,(half,half),mode='edge'),gaussian,mode='valid')
    frequency=shaped*baud/4
    burst=np.exp(2j*np.pi*np.cumsum(frequency)/fs)
    if inverted:burst=burst.conj()
    source=np.zeros(int(fs*(.08+repeats*.12)),dtype=complex)
    for index in range(repeats):
        start=int(fs*(.03+.12*index));source[start:start+len(burst)]=burst
    source*=np.exp(2j*np.pi*(offset+cfo)*np.arange(len(source))/fs)
    rng=np.random.default_rng(507);source+=.002*(rng.normal(size=len(source))+1j*rng.normal(size=len(source)))
    return source,fs


def math_ceil(value):return int(np.ceil(value))


class AISTests(unittest.TestCase):
    def test_published_class_a_and_base_station_message_fields(self):
        fields=checked_ais_packet(PACKET)
        self.assertEqual(fields['mmsi'],477553000);self.assertEqual(fields['message_type'],1)
        self.assertAlmostEqual(fields['longitude_deg'],-122.34583333333333)
        self.assertAlmostEqual(fields['latitude_deg'],47.58283333333333)
        self.assertEqual(fields['speed_over_ground_knots'],0)
        self.assertEqual(fields['course_over_ground_deg'],51)
        self.assertEqual(fields['true_heading_deg'],181)
        base=parse_ais(unarmor(BASE))
        self.assertEqual(base['mmsi'],3669702)
        self.assertAlmostEqual(base['longitude_deg'],-76.35236166666667)
        self.assertAlmostEqual(base['latitude_deg'],36.88376666666667)
        self.assertEqual(base['raw_utc'],dict(year=2007,month=5,day=14,hour=19,minute=57,second=39))

    def test_unavailable_reserved_and_lower_bound_codes_do_not_invent_values(self):
        payload=PAYLOAD
        for start,width,value in [(61,28,181*600000),(89,27,91*600000),(50,10,1023),(116,12,3600),(128,9,511),(137,6,63)]:
            payload=changed(payload,start,width,value)
        fields=parse_ais(payload)
        for key in ['longitude_deg','latitude_deg','speed_over_ground_knots','course_over_ground_deg','true_heading_deg','utc_second']:
            self.assertIsNone(fields[key])
        self.assertEqual(fields['utc_second_status'],'inoperative')
        self.assertEqual(fields['position_status'],'not_available')
        fields=parse_ais(changed(changed(payload,50,10,1022),116,12,3601))
        self.assertEqual(fields['speed_status'],'at_least');self.assertEqual(fields['speed_over_ground_knots'],102.2)
        self.assertEqual(fields['course_status'],'reserved')

    def test_class_b_and_long_range_coordinate_scaling(self):
        b=changed(bytes(21),0,6,18);b=changed(b,8,30,123456789)
        for start,width,value in [(57,28,-600000),(85,27,2*600000),(46,10,123),(112,12,900),(124,9,511)]:b=changed(b,start,width,value)
        f=parse_ais(b);self.assertEqual((f['longitude_deg'],f['latitude_deg']),(-1,2))
        self.assertEqual(f['speed_over_ground_knots'],12.3);self.assertIsNone(f['true_heading_deg'])
        long=changed(bytes(12),0,6,27);long=changed(long,8,30,123456789)
        for start,width,value in [(44,18,-600),(62,17,1200),(79,6,63),(85,9,511)]:long=changed(long,start,width,value)
        f=parse_ais(long);self.assertEqual((f['longitude_deg'],f['latitude_deg']),(-1,2))
        self.assertIsNone(f['speed_over_ground_knots']);self.assertIsNone(f['course_over_ground_deg'])
        # Frozen pyais 3.3.1 transmitter vectors; part A includes a zero spare octet.
        part_a=unarmor('H1mg=5@U5<<u0F1@E=@000000000')
        part_b=unarmor('H1mg=5E600000006l12300000000')
        extended=unarmor('C1mg=5@0Nje2>0K=C60p@dP0BRV6NP;0`:V`00000000S0000000')
        self.assertEqual(parse_ais(part_a)['ship_name'],'IQSCOPE TEST')
        self.assertEqual(parse_ais(part_a[:-1])['ship_name'],'IQSCOPE TEST')
        self.assertIsNone(parse_ais(part_a[:-1]+b'\x01'))
        self.assertEqual(parse_ais(part_b)['callsign'],'F4ABC')
        self.assertEqual(parse_ais(extended)['ship_name'],'IQSCOPE TEST')
        self.assertAlmostEqual(parse_ais(extended)['latitude_deg'],-33.5)
        self.assertAlmostEqual(parse_ais(extended)['longitude_deg'],151.2)

    def test_invalid_header_lengths_crc_and_raw_application_scope(self):
        for payload in [b'',bytes(5),PAYLOAD[:-1],PAYLOAD+bytes(1),changed(PAYLOAD,8,30,1000000000)]:
            self.assertIsNone(parse_ais(payload))
        with self.assertRaises(ValueError):checked_ais_packet(PACKET[:-1]+bytes([PACKET[-1]^1]))
        raw=changed(PAYLOAD,0,6,8);f=parse_ais(raw)
        self.assertEqual(f['interpretation'],'header_only');self.assertEqual(f['payload_hex'],raw.hex())
        self.assertNotIn('latitude_deg',f)

    def test_gmsk_clock_polarity_cfo_and_input_sample_rates(self):
        for fs,cfo,baud,inverted in [(24000,250,9600,False),(48000,-500,9600*.99995,True),(96000,500,9600*1.00005,False)]:
            with self.subTest(fs=fs):
                x,fs=fixture(fs,cfo=cfo,baud=baud,inverted=inverted)
                trial=search_ais(x,fs,[])
                self.assertEqual([f['hex'] for f in trial['frames']],[PACKET.hex()],trial)
                self.assertAlmostEqual(trial['frames'][0]['time_seconds'],.03+40/baud,delta=2/9600)

    def test_automatic_channel_selection_and_identical_retransmissions(self):
        x,fs=fixture(250000,offset=25000,repeats=2)
        t=np.arange(len(x))/fs;x+=3*np.exp(2j*np.pi*60000*t)
        from iqscope import discover
        trial=search_ais(x,fs,discover(x,fs)[0],162000000)
        channel_b=[f for f in trial['frames'] if f['channel']['ais_channel']=='B']
        self.assertEqual([f['hex'] for f in channel_b],[PACKET.hex(),PACKET.hex()])
        self.assertGreater(channel_b[1]['time_seconds']-channel_b[0]['time_seconds'],.1)

    def test_noise_tone_corrupted_and_truncated_packets_do_not_validate(self):
        x,fs=fixture(bad=True)
        rng=np.random.default_rng(508);noise=rng.normal(size=24000)+1j*rng.normal(size=24000)
        tone=np.exp(2j*np.pi*2200*np.arange(24000)/48000)
        clean,_=fixture()
        for samples in [x,noise,tone,clean[:int(.04*fs)]]:
            self.assertEqual(search_ais(samples,fs,[])['frames'],[])
        self.assertEqual(search_ais(clean,12000,[])['status'],'not_applicable')

    def test_frame_channel_time_and_flag_budgets_are_explicit(self):
        x,fs=fixture(repeats=2)
        frame_limited=search_ais(x,fs,[],max_frames=1)
        self.assertEqual(len(frame_limited['frames']),1);self.assertTrue(frame_limited['budget_exhausted'])
        self.assertEqual(search_ais(x,fs,[],max_channels=0)['frames'],[])
        self.assertEqual(search_ais(x,fs,[],max_flag_pairs=0)['frames'],[])
        self.assertTrue(search_ais(x,fs,[],max_seconds=.1)['duration_limited'])

    def test_pipeline_exports_fcs_checked_frames_and_source_window_metadata(self):
        from iqscope import analyze
        from iqscope_scan import scan_file
        x,fs=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'ais.cf32';x.astype('<c8').tofile(path)
            report=analyze(path,root/'report',fs)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='ais_gmsk')
            self.assertEqual(len(trial['frames']),1)
            self.assertEqual(json.loads((root/'report'/trial['artifact']).read_text()),trial)
            f=trial['frames'][0]
            self.assertEqual((root/'report'/f['wire_artifact']).read_bytes(),PACKET)
            self.assertEqual((root/'report'/f['payload_artifact']).read_bytes(),PAYLOAD)
            scan=scan_file(path,root/'scan',fs)
            event=scan['event_catalogue']['events'][0]
            self.assertEqual(event['family'],'AIS');self.assertEqual(event['fields']['mmsi'],477553000)
            self.assertEqual((root/'scan'/event['binary_artifact']).read_bytes(),PACKET)

    def test_failed_artifact_validation_does_not_export_a_partial_set(self):
        with tempfile.TemporaryDirectory() as directory:
            trial=dict(frames=[dict(hex=PACKET.hex()),dict(hex=(PACKET[:-1]+bytes([PACKET[-1]^1])).hex())])
            with self.assertRaises(ValueError):write_ais_artifacts(trial,directory)
            self.assertEqual(list(Path(directory).iterdir()),[])

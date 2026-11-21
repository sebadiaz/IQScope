"""Published RDS fields and an independent differential/biphase/FM transmitter."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy import signal

from iqscope_rds import checked_rds_group,remainder,search_rds,station_views,write_rds_artifacts

# Redsea components-hex.cc, commit b16943e17f6b954c87a70a35307691fc1bf5b735:
# independently published YLE X3M 2016-09-15 information words and expected PS.
PUBLISHED=[(0x6204,0x0130,0x966b,0x594c),(0x6204,0x0131,0x93cd,0x4520),
           (0x6204,0x0132,0xe472,0x5833),(0x6204,0x0137,0x966b,0x4d20)]
RT=[(0x6204,0x2000+index,int.from_bytes(data[:2],'big'),int.from_bytes(data[2:],'big'))
    for index,data in enumerate([b'HELL',b'O RD',b'S\r  '])]


def packet(words,bad_block=None):
    offsets=['0011111100','0110011000','1101010000' if words[1]&0x800 else '0101101000','0110110100']
    stream=''
    # Bit-list long division independent of the receiver integer/vector paths.
    for index,(word,offset) in enumerate(zip(words,offsets)):
        message=f'{word:016b}';dividend=list(map(int,message+'0'*10));generator=list(map(int,'10110111001'))
        for bit in range(16):
            if dividend[bit]:
                for j,value in enumerate(generator):dividend[bit+j]^=value
        check=[a^int(b) for a,b in zip(dividend[-10:],offset)]
        if bad_block==index:check[5]^=1
        stream+=message+''.join(map(str,check))
    return int(stream,2).to_bytes(13,'big')


def frame(words,time=0,offset=0):
    data=packet(words)
    return dict(hex=data.hex(),crc_valid=True,time_seconds=time,time_end_seconds=time+104/1187.5,
                channel=dict(offset_hz=offset,rf_center_known=False),fields=checked_rds_group(data))


def fixture(fs=228000,groups=None,offset=0,carrier_error=0,clock_ppm=0,inverted=False,bad=False,pilot=True):
    groups=(PUBLISHED+RT)*2 if groups is None else groups
    bits='01001110100110100101110100101011'+''.join(''.join(f'{v:08b}' for v in packet(g,1 if bad else None)) for g in groups)+'01'*24
    state=0;chips=[]
    for bit in bits:
        state^=int(bit);chips.extend([1 if state else -1,-1 if state else 1])
    clock=1187.5*(1+clock_ppm*1e-6);t=np.arange(int(fs*len(chips)/(2*clock)))/fs
    chip_index=np.minimum((t*clock*2).astype(int),len(chips)-1)
    base=signal.convolve(np.array(chips)[chip_index],signal.firwin(129,2400,fs=fs),mode='same')
    mpx=.15*np.sin(2*np.pi*1000*t)+.04*base*np.cos(2*np.pi*(57000+carrier_error)*t+.43)
    if pilot:mpx+=.08*np.cos(2*np.pi*19000*t)
    x=np.exp(2j*np.pi*(np.cumsum(mpx*65000)/fs+offset*t))
    if inverted:x=x.conj()
    rng=np.random.default_rng(5719);x+=.002*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,fs,groups


class RDSTests(unittest.TestCase):
    def test_nrsc_examples_and_published_group_fields(self):
        # NRSC-4-A Annex B: message 1 -> check 0x1B9; B-offset transmitted 0x421.
        self.assertEqual(remainder(1<<10),0x1b9)
        self.assertEqual(remainder(0x421),0x198)
        views=station_views([frame(words,index*.1) for index,words in enumerate(PUBLISHED)])
        self.assertEqual(views[0]['ps']['text'],'YLE X3M ')
        self.assertEqual(views[0]['pi_hex'],'6204');self.assertEqual(views[0]['pty'],9)
        self.assertFalse(views[0]['tp']);self.assertTrue(views[0]['ta']);self.assertFalse(views[0]['music'])
        for block in range(4):
            with self.assertRaises(ValueError):checked_rds_group(packet(PUBLISHED[0],block))
        with self.assertRaises(ValueError):checked_rds_group(b'\x00'*12)

    def test_automatic_biphase_dbpsk_fm_and_exact_received_groups(self):
        x,fs,groups=fixture();trial=search_rds(x,fs,[])
        self.assertTrue(trial['frames'],trial)
        self.assertTrue({f['hex'] for f in trial['frames']}.issubset({packet(g).hex() for g in groups}))
        station=trial['stations'][0]
        self.assertEqual(station['ps']['text'],'YLE X3M ')
        self.assertEqual(station['radiotext']['text'],'HELLO RDS')

    def test_sample_rates_carrier_clock_translation_inversion_and_no_pilot(self):
        for fs,error,ppm,invert,pilot,offset in [(192000,13,50,False,False,0),(384000,-18,-80,True,True,55000)]:
            x,_,_=fixture(fs=fs,carrier_error=error,clock_ppm=ppm,inverted=invert,pilot=pilot,offset=offset)
            actual_offset=-offset if invert else offset
            trial=search_rds(x,fs,[dict(offset_hz=actual_offset,bandwidth_hz=160000)])
            with self.subTest(fs=fs):
                self.assertEqual(trial['stations'][0]['ps']['text'],'YLE X3M ')
                self.assertEqual(trial['stations'][0]['channel']['offset_hz'],actual_offset)
                self.assertAlmostEqual(trial['channels_examined'][0]['carrier']['residual_subcarrier_hz'],error,delta=1)

    def test_rejects_corrupt_noise_unrelated_fm_and_isolated_group(self):
        x,fs,_=fixture(bad=True)
        self.assertFalse(search_rds(x,fs,[])['frames'])
        x,fs,_=fixture(groups=[PUBLISHED[0]])
        self.assertFalse(search_rds(x,fs,[])['frames'])
        t=np.arange(192000*.5)/192000;rng=np.random.default_rng(5)
        for x in [np.zeros(len(t),complex),np.exp(1j*5*np.sin(2*np.pi*1000*t)),
                  rng.normal(size=len(t))+1j*rng.normal(size=len(t))]:
            self.assertFalse(search_rds(x,192000,[])['frames'])

    def test_text_conflicts_flag_changes_missing_segments_and_channel_isolation(self):
        observations=[frame(g,index*.1) for index,g in enumerate(PUBLISHED+RT)]
        altered=deepcopy(observations);altered[0]['fields']={'pi':1}
        self.assertEqual(station_views(altered),station_views(observations))
        partial=station_views(observations[:2])[0]['ps']
        self.assertFalse(partial['complete']);self.assertIsNone(partial['text'])
        changed=frame((0x6204,0x0130,0,0x4142),time=1)
        state=station_views(observations+[changed])[0]
        self.assertFalse(state['ps']['complete']);self.assertEqual(state['ps_resets'],1)
        changed=frame((0x6204,0x2010,0x4e45,0x570d),time=1)
        state=station_views(observations+[changed])[0]
        self.assertEqual(state['radiotext']['text'],'NEW');self.assertEqual(state['radiotext_resets'],1)
        self.assertEqual(len(station_views(observations+[frame(PUBLISHED[0],time=1,offset=50000)])),2)
        version_b=[frame((0x6204,0x2800,0x6204,0x4849)),frame((0x6204,0x2801,0x6204,0x0d20),time=.1)]
        self.assertEqual(station_views(version_b)[0]['radiotext']['text'],'HI')

    def test_budgets_and_received_octet_exports(self):
        x,fs,_=fixture()
        self.assertFalse(search_rds(x,fs,[],max_channels=0)['frames'])
        trial=search_rds(x,fs,[],max_frames=3)
        self.assertEqual(len(trial['frames']),3);self.assertTrue(trial['budget_exhausted'])
        self.assertTrue(search_rds(x,fs,[],max_seconds=.4)['duration_limited'])
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);write_rds_artifacts(trial,out)
            self.assertEqual(json.loads((out/trial['artifact']).read_text()),trial)
            for f in trial['frames']:
                self.assertEqual((out/f['wire_artifact']).read_bytes(),bytes.fromhex(f['hex']))
                self.assertEqual((out/f['payload_artifact']).read_bytes(),bytes.fromhex(''.join(f['fields']['information_words_hex'])))
        self.assertEqual(search_rds(x.real,fs,[])['status'],'not_applicable')

    def test_catalogue_rechecks_all_blocks_preserves_bytes_and_overlap_origin(self):
        from iqscope_scan_events import ScanEventCatalogue
        from test_scan_events import report
        first=frame(PUBLISHED[0],time=.2)
        forged=deepcopy(first);forged['fields']={'pi':0}
        bad=deepcopy(first);bad['hex']=packet(PUBLISHED[0],2).hex()
        unclaimed=dict(first,crc_valid=False)
        catalogue=ScanEventCatalogue(228000,0)
        catalogue.observe(report([forged,bad,unclaimed],decoder='rds_fm',end=228000),1,'window-001')
        catalogue.observe(report([dict(first,time_seconds=.1,time_end_seconds=.1+104/1187.5)],decoder='rds_fm',
                                 start=22800,end=250800),2,'window-002')
        snapshot=catalogue.snapshot();self.assertEqual(snapshot['event_count'],1)
        self.assertEqual(snapshot['rejected_observations'],2)
        event=snapshot['events'][0];self.assertEqual(event['fields']['pi'],0x6204)
        self.assertEqual(event['observation_count'],2);self.assertEqual(event['hex'],first['hex'])
        self.assertEqual(event['byte_scope'],'four_26bit_blocks_with_offset_crc')


if __name__=='__main__':unittest.main()

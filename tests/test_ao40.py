import unittest
import numpy as np
import reedsolo
from iqscope_ao40 import SYNC, decode_frame, randomizer, viterbi_decode, _Probe, search_ao40_samples


def encode_reference(payload,rs_errors=0):
    # Independent serial transmitter: RS(160,128), PN, convolutional, matrix.
    rs=reedsolo.RSCodec(32,nsize=255,fcr=112,prim=0x187,generator=173)
    lanes=[rs.encode(payload[path::2]) for path in (0,1)]
    data=bytearray(v for pair in zip(*lanes) for v in pair)
    for k in range(rs_errors):data[2*k]^=k+1
    # Independent PN recurrence as an eight-bit queue, rather than a register.
    state=[1]*8;pn=[]
    for _ in range(2560):
        pn.append(state[0]);state=state[1:]+[state[0]^state[3]^state[5]^state[7]]
    message=np.unpackbits(np.frombuffer(data,dtype='u1'))^pn
    state=0;coded=[]
    for bit in list(message)+[0]*6:
        state=((state<<1)|int(bit))&127
        a=sum((state>>j)&1 for j in (0,1,2,3,6))%2
        b=1^((sum((state>>j)&1 for j in (0,2,3,5,6)))%2)
        coded.extend([a,b])
    linear=np.r_[SYNC,coded,[0,0,0]]
    return linear.reshape(80,65).T.ravel()


class Ao40Tests(unittest.TestCase):
    def test_ccsds_pn_known_prefix(self):
        self.assertEqual(np.packbits(randomizer(64)).tobytes().hex(),'ff480ec09a0d70bc')

    def test_fec_roundtrip_and_soft_bit_errors(self):
        payload=bytes((i*29+7)%256 for i in range(256))
        bits=encode_reference(payload)
        soft=2*bits.astype(float)-1
        self.assertEqual(decode_frame(soft)[0],payload)
        damaged=encode_reference(payload,rs_errors=8)
        recovered,counts=decode_frame(2*damaged.astype(float)-1)
        self.assertEqual(recovered,payload)
        self.assertEqual(counts,[8,0])
        # Isolated channel errors corrected by the convolutional layer.
        soft[np.arange(91,4000,419)]*=-1
        self.assertEqual(decode_frame(soft)[0],payload)

    def test_differential_sync_polarity_and_limits(self):
        payload=bytes(range(256));coded=encode_reference(payload)
        phase=np.r_[0,np.cumsum(coded)%2]
        values=(1-2*phase.astype(float)).astype(complex)
        for sign in (1,-1):
            probe=_Probe();probe(sign*values,1200,.25,.4)
            self.assertEqual(bytes.fromhex(probe.frames[0]['payload_hex']),payload)
            self.assertIsNone(probe.frames[0]['crc_valid'])
            self.assertAlmostEqual(probe.frames[0]['time_seconds'],.25+1/1200)
            self.assertTrue(probe.done)
        short=_Probe();short(values[:5000],1200,0,.1)
        self.assertFalse(short.frames)
        rng=np.random.default_rng(819)
        random=_Probe();random(rng.normal(size=8000)+1j*rng.normal(size=8000),1200,0,1)
        self.assertFalse(random.frames)
        fake=rng.integers(0,2,5200);fake[::80]=SYNC
        phase=np.r_[0,np.cumsum(fake)%2]
        forced=_Probe();forced((1-2*phase.astype(float)).astype(complex),1200,0,1)
        self.assertFalse(forced.frames)
        self.assertEqual(forced.best_sync_errors,0)
        self.assertGreater(forced.attempts,0)
        with self.assertRaises(ValueError):viterbi_decode(np.zeros(20))
        self.assertEqual(search_ao40_samples(np.ones(1000),1e6)['status'],'not_applicable')

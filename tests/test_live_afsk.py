"""Synthetic long AX.25 frame through quantized rtl_tcp receive buffering and FM."""
import struct
import unittest
from unittest.mock import patch

import numpy as np
from scipy import signal

from iqscope_afsk_fm import search_afsk_fm
from iqscope_web.live import LiveReceiver
from test_afsk import fixture as audio_fixture
from test_live import FakeSocket

PAYLOAD=b'>LIVE '+b'0123456789ABCDEF'*14


def long_frame_iq():
    # Source audio is independently timed at 1194.8 baud, then FM is generated
    # directly at the receiver rate. Audio interpolation adds no RF bandwidth.
    audio,_=audio_fixture(fs=48000,baud=1194.8,payload=PAYLOAD)
    audio=signal.resample_poly(audio[:len(audio)//4],16,3)
    fs=256000
    time=np.arange(len(audio))/fs
    burst=.75*np.exp(2j*np.pi*(32000*time+3000*np.cumsum(audio)/fs))
    iq=np.r_[np.zeros(3*fs),burst,np.zeros(fs//2)]
    rng=np.random.default_rng(821)
    iq+=.01*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    return iq,fs


def long_frame_receiver():
    iq,fs=long_frame_iq()
    values=np.column_stack((iq.real,iq.imag))
    wire=np.clip(np.rint(127.5+127.5*values),0,255).astype(np.uint8).tobytes()
    endpoint=FakeSocket(b'RTL0'+struct.pack('>II',5,29)+wire)
    receiver=LiveReceiver();receiver.fs=fs;receiver.frequency=145000000
    with patch('iqscope_web.live.socket.create_connection',return_value=endpoint):
        receiver._receive(1234)
    return receiver


def boundary_iq():
    """Eight quantized seconds, with the frame straddling the four-second cut."""
    iq,fs=long_frame_iq()
    rng=np.random.default_rng(822)
    count=8*fs-len(iq)
    iq=np.r_[iq,.01*(rng.normal(size=count)+1j*rng.normal(size=count))]
    values=np.clip(np.rint(127.5+127.5*np.column_stack((iq.real,iq.imag))),0,255)
    values=(values.astype(np.float32)-127.5)/127.5
    return (values[:,0]+1j*values[:,1]).astype(np.complex64),fs


def append_interval(receiver, samples):
    for start in range(0,len(samples),32768):
        receiver._append_samples(samples[start:start+32768].copy())


class LiveAfskTests(unittest.TestCase):
    def test_overlap_recovers_a_frame_split_between_disjoint_windows(self):
        from iqscope import discover
        iq,fs=boundary_iq()
        receiver=LiveReceiver();receiver.fs=fs;receiver.frequency=145000000
        counts=[];previous=0
        for end in (4*fs,6*fs,8*fs):
            append_interval(receiver,iq[previous:end]);previous=end
            context=receiver.snapshot_context();x=context['samples']
            trial=search_afsk_fm(x,fs,discover(x,fs)[0],receiver.frequency)
            counts.append(len(trial['frames']))
            if end==6*fs:
                frame=trial['frames'][0]
                self.assertEqual(bytes.fromhex(frame['fields']['payload_hex']),PAYLOAD)
                self.assertTrue(frame['fcs_valid'])
                self.assertAlmostEqual(context['source_sample_start']/fs+frame['time_seconds'],3+80/1194.8,delta=2/1194.8)
        self.assertEqual(counts,[0,1,0])

    def test_long_frame_survives_live_window_where_one_second_was_incomplete(self):
        receiver=long_frame_receiver();fs=receiver.fs
        context=receiver.snapshot_context()
        self.assertEqual(len(context['samples']),4*fs)
        self.assertGreater(context['source_sample_start'],0)
        from iqscope import discover
        bands=discover(context['samples'],fs)[0]
        recovered=search_afsk_fm(context['samples'],fs,bands,receiver.frequency)
        self.assertEqual(len(recovered['frames']),1,recovered)
        frame=recovered['frames'][0]
        self.assertEqual(frame['fields']['payload_hex'],PAYLOAD.hex())
        self.assertTrue(frame['fcs_valid'])
        self.assertGreater(frame['time_end_seconds']-frame['time_seconds'],1)
        source_time=context['source_sample_start']/fs+frame['time_seconds']
        self.assertAlmostEqual(source_time,3+80/1194.8,delta=2/1194.8)
        former=search_afsk_fm(context['samples'][-fs:],fs,bands,receiver.frequency)
        self.assertEqual(former['frames'],[])

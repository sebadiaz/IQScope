"""Bounded IQ readers for stereo WAV and SDRangel .sdriq.

Layout references: SDRangel FileRecord::Header, FileInputWorker and
WavFileRecord::Header. This module implements those layouts independently;
no SDRangel code is copied or linked.
"""
from pathlib import Path
import math
import struct
import zlib

import numpy as np

MAX_SAMPLES = 8_000_000


def sample_count(fs, seconds):
    if not math.isfinite(fs) or fs <= 0 or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Sample rate and duration must be positive and finite')
    return min(MAX_SAMPLES, int(fs * seconds))


def check_samples(x):
    if len(x) < 1024 or not np.all(np.isfinite(x)):
        raise ValueError('Need at least 1024 finite complex samples')
    return x


def wave_layout(path, allow_prefix=False):
    """Parse RIFF/RF64 chunks without loading their payloads.

    allow_prefix is reserved for a deliberately bounded downloaded excerpt;
    normal imports reject data truncated relative to the RIFF declarations.
    """
    path = Path(path)
    length = path.stat().st_size
    with path.open('rb') as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] not in (b'RIFF', b'RF64') or header[8:] != b'WAVE':
            raise ValueError('Expected little-endian RIFF/RF64 WAVE IQ data')
        rf64 = header[:4] == b'RF64'
        declared = struct.unpack_from('<I', header, 4)[0]
        if not rf64 and (declared < 4 or (declared+8 > length and not allow_prefix)):
            raise ValueError('Invalid or truncated RIFF container')
        container_end = length if rf64 else min(length, declared+8)
        fmt = None
        center = 0
        ds64_data_size = None
        for _ in range(1000):
            if handle.tell()+8 > container_end:
                break
            chunk = handle.read(8)
            kind, size = struct.unpack('<4sI', chunk)
            position = handle.tell()
            if kind == b'data':
                if fmt is None:
                    raise ValueError('WAV data precedes its format chunk')
                if rf64:
                    if declared != 0xFFFFFFFF or size != 0xFFFFFFFF or ds64_data_size is None:
                        raise ValueError('RF64 requires consistent ds64 and data chunks')
                    size = ds64_data_size
                if position+size > container_end and not allow_prefix:
                    raise ValueError('WAV data is truncated')
                encoding, channels, fs, byte_rate, align, bits = fmt
                if channels != 2:
                    raise ValueError('WAV IQ requires two channels: I then Q; mono audio is not IQ')
                if encoding not in (1, 3) or bits not in ((8,16,24,32) if encoding == 1 else (32,64)):
                    raise ValueError('Only PCM 8/16/24/32 or float 32/64 stereo IQ WAV is supported')
                if fs <= 0 or align != 2*(bits//8) or byte_rate != fs*align or size % align:
                    raise ValueError('Inconsistent WAV sample layout')
                available = min(size, max(0, length-position))
                return {'sample_rate': fs, 'center_frequency_hz': center, 'bits': bits,
                        'encoding': encoding, 'data_offset': position,
                        'data_bytes': available-available % align, 'block_align': align}
            if position+size > container_end:
                raise ValueError('WAV metadata chunk is truncated')
            if kind == b'fmt ':
                if fmt is not None or not 16 <= size <= 65536:
                    raise ValueError('Invalid or duplicate WAV format chunk')
                fmt = struct.unpack('<HHIIHH', handle.read(16))
            elif kind == b'auxi':
                if size < 36:
                    raise ValueError('WAV auxi chunk is too short')
                auxi = handle.read(36)
                center = struct.unpack_from('<I', auxi, 32)[0]
            elif kind == b'ds64':
                if size < 28:
                    raise ValueError('Invalid RF64 ds64 chunk')
                riff_size, ds64_data_size, _, _ = struct.unpack('<QQQI', handle.read(28))
                if riff_size+8 > length and not allow_prefix:
                    raise ValueError('Truncated RF64 file')
                container_end = min(length, riff_size+8)
            handle.seek(position+size+(size & 1))
    raise ValueError('WAV contains no supported IQ data chunk')


def read_wave_iq(path, seconds=10, allow_prefix=False):
    layout = wave_layout(path, allow_prefix=allow_prefix)
    fs, bits = layout['sample_rate'], layout['bits']
    count = min(sample_count(fs, seconds), layout['data_bytes']//layout['block_align'])
    with Path(path).open('rb') as handle:
        handle.seek(layout['data_offset'])
        payload = handle.read(count*layout['block_align'])
    if layout['encoding'] == 3:
        values = np.frombuffer(payload, dtype=f'<f{bits//8}').astype(np.float32)
    elif bits == 24:
        raw = np.frombuffer(payload, dtype=np.uint8).reshape(-1,3).astype(np.int32)
        values = raw[:,0] | (raw[:,1] << 8) | (raw[:,2] << 16)
        values = ((values ^ 0x800000)-0x800000).astype(np.float32)/8388608
    elif bits == 8:
        values = (np.frombuffer(payload, dtype=np.uint8).astype(np.float32)-128)/128
    else:
        values = np.frombuffer(payload, dtype=f'<i{bits//8}').astype(np.float32)/(2**(bits-1))
    x = values[::2]+1j*values[1::2]
    return check_samples(x), float(fs), float(layout['center_frequency_hz'])


def read_sdriq(path, seconds=10):
    path = Path(path)
    with path.open('rb') as handle:
        header = handle.read(32)
        if len(header) != 32:
            raise ValueError('SDRangel header requires 32 bytes')
        checksum = zlib.crc32(header[:28]) & 0xFFFFFFFF
        layout = None
        for endian in ('<','>'):
            fields = struct.unpack(endian+'IQQIII', header)
            if fields[-1] == checksum and fields[0] > 0 and fields[3] in (16,24):
                layout = (endian, fields)
                break
        if layout is None:
            raise ValueError('Invalid SDRangel header CRC-32 or unsupported sample size')
        endian, (fs, center, timestamp, bits, filler, crc) = layout
        # SDRangel stores 24-bit samples in signed 32-bit containers, not packed bytes.
        width = 2 if bits == 16 else 4
        if (path.stat().st_size-32) % (2*width):
            raise ValueError('SDRangel file ends with an incomplete IQ sample')
        count = sample_count(fs, seconds)
        raw = np.fromfile(handle, dtype=endian+f'i{width}', count=2*count)
        if bits == 24 and np.any((raw < -8388608) | (raw > 8388607)):
            raise ValueError('SDRangel samples exceed the declared signed 24-bit range')
        values = raw.astype(np.float32)/(2**(bits-1))
        x = values[::2]+1j*values[1::2]
        return check_samples(x), float(fs), float(center)

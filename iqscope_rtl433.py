"""Optional file-only rtl_433 adapter. External integrity claims stay external."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from iqscope_channels import extract_channel

MAX_CHANNELS = 4
MAX_MESSAGES = 128
OUTPUT_LIMIT = 1_048_576


def _run(argv, cwd, timeout):
    """Drain both pipes with finite memory, killing on overflow or deadline."""
    output = [b'', b'']
    overflow = threading.Event()
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def read(index, stream):
        try:
            output[index] = stream.read(OUTPUT_LIMIT + 1)
            if len(output[index]) > OUTPUT_LIMIT:
                overflow.set()
                process.kill()
        finally:
            stream.close()
    readers = [threading.Thread(target=read, args=(i, stream), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=max(.01, timeout))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return_code = 'timeout'
    else:
        return_code = 'output_limit' if overflow.is_set() else process.returncode
    finally:
        for reader in readers:
            reader.join()
    if overflow.is_set() and return_code != 'timeout':
        return_code = 'output_limit'
    return return_code, output[0][:OUTPUT_LIMIT]


def search_rtl433(x, fs, detections, center=0):
    result = {'decoder': 'rtl433', 'family': 'OOK / FSK sensors (external rtl_433)',
              'status': 'unavailable', 'messages': [], 'channels_examined': [],
              'validation': 'external decoder claims; no independent IQScope CRC or sender authentication',
              'limitations': ['Default rtl_433 device set only; installed version determines coverage.',
                              'Stationary spectral centers; hopping, overlapping and weak bursts may be missed.',
                              'At most four channels, five seconds per channel and a twelve-second process budget.']}
    executable = shutil.which('rtl_433')
    if executable is None:
        result['reason'] = 'Install rtl_433 on PATH to enable automatic sensor decoding.'
        return result
    executable = str(Path(executable).resolve())
    if not math.isfinite(fs) or fs < 20_000 or fs > 20_000_000:
        result.update(status='not_applicable', reason='Requires 20 kS/s to 20 MS/s')
        return result
    # A baseband trial preserves short centered bursts missed by the averaged PSD.
    offsets = [0.0]
    spacing = min(fs / max(1, math.ceil(fs / 250_000)), 250_000) * .25
    for item in sorted(detections if fs > 250_000 else [], key=lambda d: d['spectral_snr_db'], reverse=True):
        offset = item['offset_hz']
        if abs(offset) < fs/2 and all(abs(offset-old) > spacing for old in offsets):
            offsets.append(offset)
    result['deferred_channel_count'] = max(0, len(offsets)-MAX_CHANNELS)
    result['status'] = 'completed'
    deadline = time.monotonic() + 12
    with tempfile.TemporaryDirectory(prefix='iqscope-rtl433-') as directory:
        for offset in offsets[:MAX_CHANNELS]:
            if time.monotonic() >= deadline or len(result['messages']) >= MAX_MESSAGES:
                result['status'] = 'budget_exhausted'
                break
            y, channel = extract_channel(x, fs, offset)
            channel['index'] = len(result['channels_examined'])
            channel['frequency_hz'] = float(center + offset) if center else None
            channel['frequency_reference'] = 'provided_capture_center' if center else 'relative_only'
            result['channels_examined'].append(channel)
            # Explicit cf32 format and -c 0 prevent filename guesses/config/network outputs.
            path = Path(directory) / 'input.cf32'
            y.tofile(path)
            argv = [executable, '-c', '0', '-r', str(path), '-s', str(round(channel['sample_rate'])),
                    '-F', 'json', '-M', 'protocol', '-M', 'time:rel', '-C', 'si']
            channel['decoder_sample_rate'] = round(channel['sample_rate'])
            channel['decoder_sample_rate_error_hz'] = round(channel['sample_rate'])-channel['sample_rate']
            try:
                code, output = _run(argv, directory, deadline-time.monotonic())
            except OSError as exc:
                channel['status'] = 'error'
                channel['error_type'] = type(exc).__name__
                result['status'] = 'partial_error'
                continue
            channel['status'] = 'completed' if code == 0 else str(code)
            if code != 0:
                result['status'] = 'partial_error'
            invalid = 0
            for line in output.splitlines():
                try:
                    message = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                    json.dumps(message, allow_nan=False)
                    if not isinstance(message, dict) or not isinstance(message.get('model'), str):
                        raise ValueError('Not a device message')
                except (ValueError, UnicodeError, RecursionError):
                    invalid += 1
                    continue
                if len(result['messages']) >= MAX_MESSAGES:
                    result['status'] = 'budget_exhausted'
                    break
                result['messages'].append({'channel_index': channel['index'],
                                           'integrity_reported_by_decoder': message.get('mic'),
                                           'independently_validated': False,
                                           'fields': message})
            channel['invalid_json_lines'] = invalid
    return result

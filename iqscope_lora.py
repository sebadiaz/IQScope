"""Bounded LoRa PHY trials: CSS, explicit headers and CR4/5 payload CRC."""
from fractions import Fraction
import numpy as np
from scipy import signal
from iqscope_lora_header import decode_explicit_header
from iqscope_lora_payload import decode_payload


def _opposite_chirp_pair(y, chirp, polarity, run_end, bandwidth):
    """Look for two concentrated opposite chirps; not a packet-boundary solution."""
    length = len(chirp)
    template = chirp.conj() if polarity == 1 else chirp
    step = max(1, length//32)
    first = max(0, run_end-length)
    last = min(len(y)-2*length, run_end+4*length)
    best = None
    for start in range(first,last+1,step):
        matrix = y[start:start+2*length].reshape(2,length)
        power = abs(np.fft.fft(matrix*template.conj(),axis=1))**2
        peaks = np.argmax(power,axis=1)
        fraction = sum(power[np.arange(2),(peaks+offset)%length] for offset in (-1,0,1))/np.maximum(power.sum(axis=1),1e-30)
        separation = min((int(peaks[0])-int(peaks[1]))%length,(int(peaks[1])-int(peaks[0]))%length)
        strength = float(min(fraction))
        if strength < .8 or separation > 1:
            continue
        if best is None or strength > best['minimum_three_bin_energy_fraction']:
            best = {'status':'opposite_chirp_pair_candidate', 'time_seconds':start/bandwidth,
                    'sample_start_at_chip_rate':start, 'search_step_chips':step,
                    'minimum_three_bin_energy_fraction':strength,
                    'dechirped_peak_bins':[int(value) for value in peaks],
                    'scope':'Two opposite-direction chirps only; sync word, quarter chirp, exact boundary and payload not validated'}
    return best or {'status':'no_consistent_opposite_pair'}


def _sync_word_candidate(y, chirp, polarity, preamble_bin, pair, bandwidth):
    """Resolve timing hypotheses from up/down bins, then read two relative CSS bins."""
    if pair['status'] != 'opposite_chirp_pair_candidate':
        return {'status':'not_available_without_opposite_pair'}
    length = len(chirp)
    start = pair['sample_start_at_chip_rate']
    down_bin = pair['dechirped_peak_bins'][0]
    phase = ((polarity*(down_bin-preamble_bin)+start)/2) % (length/2)
    template = chirp if polarity == 1 else chirp.conj()
    hypotheses = []
    tested = set()
    for half in (0,length/2):
        for cycle in range(start//length-1,start//length+2):
            center = round(cycle*length+phase+half)
            for delta in (-1,0,1):
                boundary = center+delta
                if boundary in tested or boundary < 3*length or abs(boundary-start)>length/2:
                    continue
                tested.add(boundary)
                matrix = y[boundary-3*length:boundary].reshape(3,length)
                power = abs(np.fft.fft(matrix*template.conj(),axis=1))**2
                peaks = np.argmax(power,axis=1)
                energy = sum(power[np.arange(3),(peaks+offset)%length] for offset in (-1,0,1))/np.maximum(power.sum(axis=1),1e-30)
                # Use the preamble concentration criterion for shifted upchirps too.
                if min(energy)<.65:
                    continue
                symbols = [(polarity*(int(value)-int(peaks[0])))%length for value in peaks[1:]]
                nibbles,errors = [],[]
                for value in symbols:
                    distances = [min((value-8*n)%length,(8*n-value)%length) for n in range(16)]
                    nibble = int(np.argmin(distances))
                    nibbles.append(nibble)
                    errors.append(distances[nibble])
                if max(errors)>1:
                    continue
                hypotheses.append({'word':16*nibbles[0]+nibbles[1], 'boundary':boundary,
                                   'symbols':symbols, 'strength':float(min(energy)), 'errors':errors})
    words = {item['word'] for item in hypotheses}
    if not hypotheses:
        return {'status':'no_consistent_sync_word'}
    if len(words)>1:
        return {'status':'ambiguous_sync_word', 'word_hypotheses_hex':[f'{word:02X}' for word in sorted(words)]}
    best = max(hypotheses,key=lambda item:item['strength'])
    return {'status':'sync_word_candidate', 'value_hex':f"{best['word']:02X}",
            'relative_symbol_bins':best['symbols'], 'symbol_bin_errors':best['errors'],
            'opposite_chirp_start_seconds':best['boundary']/bandwidth,
            'opposite_chirp_start_chip':best['boundary'],
            'minimum_three_bin_energy_fraction':best['strength'],
            'scope':'Conventional two-nibble sync-word hypothesis only; no network identity, quarter-chirp, header, CRC or payload validation'}


def _fractional_tone_bin(values, peak):
    """Median adjacent phase after removing the coarse FFT bin; tolerate wrap outliers."""
    length = len(values)
    products = values[1:]*values[:-1].conj()*np.exp(-2j*np.pi*peak/length)
    residual = float(np.median(np.angle(products)))*length/(2*np.pi)
    return (peak+residual)%length if abs(residual)<=1.5 else None


def _data_symbol_candidates(y, chirp, polarity, sync, bandwidth):
    """Require a matching final quarter chirp before bounded raw CSS symbols."""
    if sync['status'] != 'sync_word_candidate':
        return {'status':'not_available_without_sync_word'}
    length = len(chirp)
    quarter = length//4
    up = chirp if polarity == 1 else chirp.conj()
    down = up.conj()
    best = None
    # Small integer timing refinements; fractional timing/clock tracking is not solved.
    for boundary in range(sync['opposite_chirp_start_chip']-2,sync['opposite_chirp_start_chip']+3):
        end = boundary+2*length+quarter
        if boundary < 3*length or end > len(y):
            continue
        reference = y[boundary-3*length:boundary-2*length]
        reference_power = abs(np.fft.fft(reference*up.conj()))**2
        reference_bin = int(np.argmax(reference_power))
        reference_tone = _fractional_tone_bin(reference*up.conj(), reference_bin)
        if reference_tone is None:
            continue
        down_power = abs(np.fft.fft(y[boundary:boundary+length]*down.conj()))**2
        down_bin = int(np.argmax(down_power))
        n = np.arange(quarter)
        expected = down[:quarter]*np.exp(2j*np.pi*down_bin*n/length)
        observed = y[boundary+2*length:end]
        energy = float(np.sum(abs(observed)**2))
        correlation = float(abs(np.vdot(expected,observed))**2/max(quarter*energy,1e-30))
        if correlation < .8:
            continue
        if best is None or correlation > best['correlation']:
            best = {'boundary':boundary,'start':end,'reference_bin':reference_bin,'reference_tone':reference_tone,'correlation':correlation}
    if best is None:
        return {'status':'no_consistent_final_quarter_chirp'}
    count = min(64,(len(y)-best['start'])//length)
    symbols, strengths, fft_symbols = [],[],[]
    stop_reason = 'symbol_budget' if count==64 else 'source_exhausted'
    for index in range(count):
        start = best['start']+index*length
        power = abs(np.fft.fft(y[start:start+length]*up.conj()))**2
        peak = int(np.argmax(power))
        strength = float(sum(power[(peak+offset)%length] for offset in (-1,0,1))/max(float(sum(power)),1e-30))
        if strength < .65:
            stop_reason = 'insufficient_spectral_concentration'
            break
        tone = _fractional_tone_bin(y[start:start+length]*up.conj(),peak)
        if tone is None:
            stop_reason = 'unstable_phase_estimate'
            break
        fft_symbols.append((polarity*(peak-best['reference_bin']))%length)
        symbols.append(int(round(polarity*(tone-best['reference_tone'])))%length)
        strengths.append(strength)
    return {'status':'raw_css_symbol_candidates' if symbols else 'quarter_chirp_candidate_no_symbols',
            'quarter_chirp_correlation':best['correlation'],
            'candidate_data_start_seconds':best['start']/bandwidth,
            'symbol_bins':symbols, 'fft_peak_symbol_bins':fft_symbols, 'symbol_energy_fractions':strengths,
            'symbol_bin_uncertainty':1, 'symbol_budget':64,
            'symbol_budget_reached':len(symbols)==64, 'stop_reason':stop_reason,
            'scope':'Raw relative CSS bins only; timing remains a hypothesis. No Gray mapping, deinterleaving, error correction, whitening, header, CRC or payload bytes decoded'}


def detect_lora_preamble(x, fs):
    base = {'decoder': 'lora_preamble', 'family': 'LoRa-compatible CSS preamble', 'candidates': []}
    if not np.isfinite(fs) or not 125000 <= fs <= 2400000 or len(x) < 1024:
        return dict(base, status='not_applicable')
    original = len(x)
    limit = min(original, int(fs))
    x = np.asarray(x[:limit], dtype=np.complex128)
    if not np.all(np.isfinite(x)):
        return dict(base, status='not_applicable')
    candidates = []
    trials = 0
    search_windows = []
    for bandwidth in (125000, 250000, 500000):
        if fs < bandwidth:
            continue
        ratio = Fraction(bandwidth / fs).limit_denominator(4096)
        actual = fs * ratio.numerator / ratio.denominator
        if abs(actual - bandwidth) / bandwidth > 1e-6:
            continue
        y = signal.resample_poly(x, ratio.numerator, ratio.denominator)
        for sf in range(7, 13):
            length = 2**sf
            blocks = min(len(y)//length, 256)
            if blocks < 6:
                continue
            search_windows.append({'bandwidth_hz': bandwidth, 'spreading_factor': sf,
                'symbol_blocks': blocks, 'examined_seconds': blocks*length/bandwidth,
                'symbol_budget_reached': len(y)//length > blocks})
            n = np.arange(length)
            # One sample/chip: a cyclic shift of a chirp becomes a tone after dechirping.
            chirp = np.exp(1j*np.pi*(n*n/length-n))
            matrix = y[:blocks*length].reshape(blocks, length)
            for polarity in (1, -1):
                trials += 1
                transformed = np.fft.fft(matrix * np.conj(chirp if polarity == 1 else chirp.conj()), axis=1)
                power = np.abs(transformed)**2
                peaks = np.argmax(power, axis=1)
                concentration = sum(power[np.arange(blocks),(peaks+offset)%length] for offset in (-1,0,1))/np.maximum(power.sum(axis=1), 1e-30)
                best_start, best_count = 0, 0
                run_start = 0
                for index in range(blocks):
                    if concentration[index] < .65:
                        run_start = index+1
                        continue
                    if index > run_start and min((int(peaks[index])-int(peaks[run_start]))%length,
                                                (int(peaks[run_start])-int(peaks[index]))%length) > 1:
                        run_start = index
                    count = index-run_start+1
                    if count > best_count:
                        best_start, best_count = run_start, count
                if best_count < 6:
                    continue
                strength = float(np.median(concentration[best_start:best_start+best_count]))
                pair = _opposite_chirp_pair(y, chirp, polarity, (best_start+best_count)*length, bandwidth)
                sync = _sync_word_candidate(y, chirp, polarity, int(peaks[best_start]), pair, bandwidth)
                data = _data_symbol_candidates(y, chirp, polarity, sync, bandwidth)
                candidates.append({'parameters': {'bandwidth_hz': bandwidth, 'spreading_factor': sf,
                    'symbol_seconds': length/bandwidth, 'chirp_polarity': polarity},
                    'time_seconds': best_start*length/bandwidth,
                    'evidence': {'repeated_chirps': best_count, 'median_three_bin_energy_fraction': strength,
                                 'dechirped_peak_bin': int(peaks[best_start]), 'required_chirps': 6},
                    'synchronization': pair,
                    'sync_word': sync,
                    'data_symbols': data,
                    'explicit_header': decode_explicit_header(data.get('symbol_bins',[]),sf),
                    'payload': decode_payload(data.get('symbol_bins',[]),sf),
                    'score': strength, 'score_kind': 'heuristic_not_probability',
                    'validation_scope': 'Bounded LoRa PHY trial; only explicit header checks and supported payload CRC results are validated. No LoRaWAN identity or authentication.'})
    candidates.sort(key=lambda item: item['score'], reverse=True)
    frames=[]
    for candidate in candidates[:6]:
        payload=candidate['payload']
        if payload['status']!='payload_crc_valid':
            continue
        time=candidate['data_symbols']['candidate_data_start_seconds']
        if any(frame['payload_hex']==payload['payload_hex'] and abs(frame['time_seconds']-time)<candidate['parameters']['symbol_seconds'] for frame in frames):
            continue
        frames.append({**payload,'time_seconds':time,'parameters':candidate['parameters'],'sync_word':candidate['sync_word'].get('value_hex')})
    return dict(base, status='crc_valid_payload' if frames else ('repeated_chirp_candidate' if candidates else 'no_consistent_candidate'),
                candidates=candidates[:6], trials=trials, analyzed_seconds=len(x)/fs, search_windows=search_windows,
                **({'frames':frames} if frames else {}),
                sample_budget_reached=limit < original,
                limitations=['Centered single-channel search only; no RF center or carrier-offset estimation.',
                    'BW 125/250/500 kHz, SF7–SF12, both chirp directions; six stable concentrated FFT peaks required.',
                    'First second only; at most 256 symbols per BW/SF. Late/short/weak bursts, clock drift and off-center channels may be missed.',
                    'Other CSS waveforms can match preamble evidence. Header checksum and supported payload CRC are checked separately; all other stages remain candidates. Payload: explicit CR4/5, SF7–SF10 only.'])

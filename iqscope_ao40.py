"""Bounded standard AO-40 FEC acquisition. RS parity is not CRC or identity."""
import threading
import numpy as np
from scipy import signal

SYNC=np.array([int(v) for v in '11111110000111011110010110010010000001000100110001011101011011000'])
_RS_LOCK=threading.Lock()


def viterbi_decode(soft):
    soft=np.clip(np.asarray(soft,dtype=float),-8,8)
    if len(soft)!=5132 or not np.all(np.isfinite(soft)):
        raise ValueError('AO-40 needs 5132 finite coded symbols')
    state=np.arange(64);bit=state&1
    predecessors=np.array([state//2,state//2+32])
    registers=(predecessors<<1)|bit
    signs=np.empty((2,64,2))
    for a in range(2):
        for b in range(64):
            for j,poly in enumerate((79,109)):
                value=(int(registers[a,b])&poly).bit_count()%2
                signs[a,b,j]=2*(value^(j==1))-1
    metrics=np.full(64,-1e10);metrics[0]=0
    history=np.empty((2566,64),dtype=np.uint8)
    for k,pair in enumerate(soft.reshape(-1,2)):
        scores=metrics[predecessors]+np.sum(signs*pair,axis=2)
        choice=np.argmax(scores,axis=0)
        metrics=scores[choice,state]
        history[k]=choice
    current=0;bits=[]
    for choice in history[::-1]:
        bits.append(current&1)
        current=int(predecessors[choice[current],current])
    if current!=0:
        raise ValueError('Inconsistent Viterbi initial state')
    return np.array(bits[::-1],dtype=np.uint8)[:-6]


def randomizer(length):
    register=255;out=np.empty(length,dtype=np.uint8)
    for k in range(length):
        out[k]=register&1
        register=(register>>1)|(((register&0xa9).bit_count()&1)<<7)
    return out


def decode_frame(soft):
    import reedsolo
    coded=np.asarray(soft).reshape(65,80).T.ravel()[65:5197]
    bits=viterbi_decode(coded)
    data=np.packbits(bits^randomizer(len(bits))).tobytes()
    outputs=[];corrections=[]
    # RSCodec sets module-level field tables: serialize all our RS calls.
    with _RS_LOCK:
        rs=reedsolo.RSCodec(32,nsize=255,fcr=112,prim=0x187,generator=173)
        for path in range(2):
            decoded,corrected,errors=rs.decode(data[path::2])
            if len(decoded)!=128 or bytes(rs.encode(decoded))!=bytes(corrected):
                raise ValueError('Reed-Solomon parity verification failed')
            outputs.append(decoded);corrections.append(len(errors))
    return bytes(v for pair in zip(*outputs) for v in pair),corrections


class _Probe:
    def __init__(self):
        self.frames=[];self.attempts=0;self.best_sync_errors=None
        self.seen=set()

    @property
    def done(self):
        return bool(self.frames) or self.attempts>=4

    def __call__(self,values,baud,first,evm):
        # DBPSK soft decisions; positive means one at the FEC input.
        import reedsolo
        soft=-(values[1:]*values[:-1].conj()).real
        n=len(soft)-5199
        if n<=0 or self.done:return self.done
        scores=np.zeros(n)
        hard=np.where(soft>=0,1,-1)
        for k,bit in enumerate(SYNC):scores+=hard[k*80:k*80+n]*(2*bit-1)
        # At most four synchronization hypotheses over all pulse-shape trials.
        for index in np.argsort(-abs(scores)):
            errors=int((65-abs(scores[index]))/2)
            self.best_sync_errors=errors if self.best_sync_errors is None else min(errors,self.best_sync_errors)
            if errors>8 or self.done:break
            key=round((first+(int(index)+1)/baud)*baud)
            if key in self.seen:continue
            self.seen.add(key);self.attempts+=1
            try:payload,corrected=decode_frame(soft[index:index+5200]*np.sign(scores[index]))
            except (ValueError,ArithmeticError,reedsolo.ReedSolomonError):continue
            from iqscope_funcube import interpret_funcube
            telemetry=interpret_funcube(payload)
            self.frames.append({'telemetry':telemetry,'decoder':'ao40_fec','payload_hex':payload.hex(),'payload_bytes':len(payload),
                                'time_seconds':float(first+(int(index)+1)/baud),'baud':float(baud),
                                'sync_errors':errors,'rs_corrected_symbols':corrected,
                                'upstream_symbol_evm_rms':float(evm),'crc_valid':None,'crc_check':'not_present',
                                'validation':'Viterbi terminated K=7, CCSDS derandomization, both shortened RS parity checks; no CRC or authentication'})
        return self.done


def search_ao40_samples(x,fs,frequency_reference='relative_hz'):
    result={'decoder':'ao40_fec','family':'AO-40 FEC / DBPSK','frames':[],
            'frequency_reference':frequency_reference,'crc_valid':None,'crc_check':'not_present',
            'limitations':['Standard 5200-symbol AO-40 FEC only; not short frames or Manchester variants.',
                            'First six seconds only; direct <=96 kS/s, at most four synchronization/FEC attempts and one accepted frame.',
                            'Upstream symbol EVM is diagnostic; payload acceptance requires both Reed-Solomon checks.',
                            'Error-correcting parity is not CRC, sender authentication or telemetry semantics.']}
    if not np.isfinite(fs) or not 1000<=fs<=96000:
        return dict(result,status='not_applicable')
    count=min(len(x),int(6*fs))
    result.update(analyzed_seconds=count/fs,duration_limited=count<len(x))
    if count/fs*min(9600,fs/8)<5220:
        return dict(result,status='not_applicable')
    try:import reedsolo
    except ImportError:return dict(result,status='unavailable',reason='reedsolo dependency missing')
    analytic=np.asarray(x[:count])
    if not np.all(np.isfinite(analytic)):
        return dict(result,status='invalid_samples')
    from iqscope_psk_rrc import recover_rrc
    probe=_Probe()
    recover_rrc(analytic,fs,protocol_probe=probe)
    return dict(result,status='fec_validated_payload' if probe.frames else 'no_fec_validated_payload',
                frames=probe.frames,fec_attempts=probe.attempts,best_sync_errors=probe.best_sync_errors)


def search_ao40_audio(audio,fs):
    count=min(len(audio),int(6*fs))
    derived=signal.resample_poly(signal.hilbert(audio[:count]),2,1)
    result=search_ao40_samples(derived,fs*2,frequency_reference='audio_hz')
    result['duration_limited']=count<len(audio)
    result['source_kind']='derived_analytic_receiver_audio'
    return result


def write_ao40_artifacts(trial,out):
    import json
    from pathlib import Path
    out=Path(out)
    for index,frame in enumerate(trial['frames'],1):
        frame['payload_artifact']=f'ao40-payload-{index}.bin'
        (out/frame['payload_artifact']).write_bytes(bytes.fromhex(frame['payload_hex']))
        if frame.get('telemetry',{}).get('status')=='candidate_interpretation':
            frame['telemetry_artifact']=f'funcube-telemetry-{index}.json'
            (out/frame['telemetry_artifact']).write_text(json.dumps(frame['telemetry'],indent=2),encoding='utf-8')
    if trial['frames']:
        trial['artifact']='ao40-frames.json'
        (out/trial['artifact']).write_text(json.dumps(trial,indent=2),encoding='utf-8')

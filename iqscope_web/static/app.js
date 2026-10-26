'use strict';
const $ = id => document.getElementById(id);
let busy = false, liveMode = false, liveConnected = false, pollingLive = false;
let currentSpectrum = null, waterfallRows = [], selectedSignal = null, signals = [];
let center = 0, sampleRate = 0, lastSnapshot = 0, lastLiveSample = -1, reportJob = null;
const api = async (url, body, method = 'POST') => {
  const response = await fetch(url, {
    method, headers: {'X-IQScope':'local', ...(body instanceof Blob ? {'X-IQScope-Filename':encodeURIComponent(body.name || 'recording.cf32')} : {'Content-Type':'application/json'})},
    ...(method === 'GET' ? {} : {body: body instanceof Blob ? body : JSON.stringify(body ?? {})})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
};
function status(text, kind = '') { $('status-text').textContent = text; $('status-dot').className = `dot ${kind}`; }
function setBusy(value) {
  busy = value;
  for (const id of ['analyze','demo','tab-file','tab-live']) $(id).disabled = value;
}
function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function formatFrequency(hz) {
  return Math.abs(hz) >= 1e6 ? `${(hz/1e6).toFixed(4)} MHz` : `${(hz/1e3).toFixed(2)} kHz`;
}
function canvasContext(id) {
  const canvas = $(id), ratio = window.devicePixelRatio || 1;
  const width = Math.max(100, Math.round(canvas.clientWidth * ratio));
  const height = Math.round((id === 'spectrum' ? 190 : 180) * ratio);
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  return [canvas.getContext('2d'), width, height];
}
function drawSpectrum() {
  const [ctx,w,h] = canvasContext('spectrum');
  ctx.fillStyle = '#0a121c'; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle = '#1b2b3a'; ctx.lineWidth = 1;
  for (let i=1;i<5;i++) { ctx.beginPath(); ctx.moveTo(0,h*i/5); ctx.lineTo(w,h*i/5); ctx.stroke(); }
  for (let i=1;i<8;i++) { ctx.beginPath(); ctx.moveTo(w*i/8,0); ctx.lineTo(w*i/8,h); ctx.stroke(); }
  if (!currentSpectrum) return;
  const power = currentSpectrum.power_db;
  const sorted = [...power].sort((a,b)=>a-b);
  const floor = sorted[Math.floor(sorted.length*.1)]-8;
  const ceiling = Math.max(floor+20,sorted[sorted.length-1]+7);
  for (const sig of signals) {
    const [a,b] = sig.band_edges_hz;
    ctx.fillStyle = sig.id === selectedSignal ? '#64e5c12e' : '#83aaff0c';
    ctx.fillRect((a/sampleRate+.5)*w,0,(b-a)/sampleRate*w,h);
  }
  ctx.beginPath();
  for (let i=0;i<power.length;i++) {
    const x = i/Math.max(1,power.length-1)*w;
    const y = h-((power[i]-floor)/(ceiling-floor))*h*.92;
    i ? ctx.lineTo(x,y) : ctx.moveTo(x,y);
  }
  ctx.strokeStyle='#64e5c1';ctx.lineWidth=1.25*(window.devicePixelRatio||1);ctx.stroke();
}
function color(v) {
  const stops=[[8,16,31],[23,40,82],[58,73,170],[30,172,182],[114,230,192],[255,224,149]];
  const scaled=Math.max(0,Math.min(.9999,v))*(stops.length-1), i=Math.floor(scaled), t=scaled-i;
  return stops[i].map((n,k)=>Math.round(n+(stops[i+1][k]-n)*t));
}
function drawWaterfall() {
  const [ctx,w,h]=canvasContext('waterfall');
  if (!waterfallRows.length) {ctx.fillStyle='#0a121c';ctx.fillRect(0,0,w,h);return;}
  const sampled=[];
  for (const row of waterfallRows) for(let i=0;i<row.length;i+=8) sampled.push(row[i]);
  sampled.sort((a,b)=>a-b);
  const lo=sampled[Math.floor(sampled.length*.15)]-3;
  const hi=Math.max(lo+25,sampled[Math.floor(sampled.length*.995)]+3);
  const palette=Array.from({length:256},(_,i)=>color(i/255));
  const image=ctx.createImageData(w,h);
  for(let y=0;y<h;y++) {
    const row=waterfallRows[Math.min(waterfallRows.length-1,Math.floor(y/h*waterfallRows.length))];
    for(let x=0;x<w;x++) {
      const v=row[Math.min(row.length-1,Math.floor(x/w*row.length))];
      const rgb=palette[Math.max(0,Math.min(255,Math.floor((v-lo)/(hi-lo)*255)))];
      const p=(y*w+x)*4;
      image.data[p]=rgb[0];image.data[p+1]=rgb[1];image.data[p+2]=rgb[2];image.data[p+3]=255;
    }
  }
  ctx.putImageData(image,0,0); $('empty-plot').hidden=true;
}
function updateAxes() {
  $('axis-left').textContent=formatFrequency(center-sampleRate/2);
  $('axis-center').textContent=formatFrequency(center);
  $('axis-right').textContent=formatFrequency(center+sampleRate/2);
  $('center-label').textContent=center ? `Centre ${formatFrequency(center)}` : 'Fréquences relatives à la capture';
  $('rate-label').textContent=`${(sampleRate/1e6).toFixed(3)} Méch/s`;
}
function showReport(report, jobId) {
  reportJob=jobId; center=report.center_frequency_hz;sampleRate=report.sample_rate;
  signals=report.signals;selectedSignal=null;currentSpectrum=report.spectrum;
  if(!liveMode) {
    waterfallRows=report.waterfall.power_db;
    $('waterfall-label').textContent='Capture · fenêtres échantillonnées du début vers la fin';
  }
  updateAxes();drawSpectrum();drawWaterfall();
  const frames=(report.wideband_trials || []).filter(t=>t.decoder==='adsb_1090es').flatMap(t=>t.frames || []);
  const ax25Trials=(report.wideband_trials || []).filter(t=>t.decoder==='ax25_ui');
  const ax25Frames=ax25Trials.flatMap(t=>t.frames || []);
  $('metric-signals').textContent=signals.length;
  $('metric-frames').textContent=frames.length+ax25Frames.length;
  $('metric-duration').textContent=`${report.analyzed_seconds.toFixed(2)} s`;
  $('download').href=`/api/jobs/${jobId}/artifacts/report.json`; $('download').hidden=false;
  const list=$('signal-list');list.replaceChildren();
  if(!signals.length) list.append(element('div','Aucune bande stationnaire détectée. Les paquets sont recherchés séparément.','empty-results'));
  for(const sig of signals) {
    const details=element('details',undefined,'signal'), summary=element('summary');
    summary.append(element('strong',formatFrequency(sig.frequency_hz)));
    summary.append(element('span',`${(sig.bandwidth_hz/1000).toFixed(2)} kHz · ${sig.spectral_snr_db.toFixed(0)} dB de contraste`));
    details.append(summary);
    details.addEventListener('toggle',()=>{if(details.open){selectedSignal=sig.id;drawSpectrum();}});
    const content=element('div',undefined,'detail');
    if(!sig.decoder_trials.length) content.append(element('p',sig.status==='budget_deferred' ? 'Essais différés : budget de bandes atteint.' : 'Famille inconnue. Aucun contenu validé.','unknown'));
    for(const trial of sig.decoder_trials) {
      const row=element('div',undefined,'trial');
      row.append(element('p',`${trial.family} · audio candidat, non validé`));
      const audio=element('audio');audio.controls=true;audio.preload='none';
      audio.src=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.audio)}`;
      row.append(audio);content.append(row);
    }
    details.append(content);list.append(details);
  }
  const frameList=$('frame-list');frameList.replaceChildren();
  frameList.append(element('h3',`Mode S / ADS-B · ${frames.length} paquet(s) CRC valide(s)`,'frames-title'));
  if(sampleRate<2e6) frameList.append(element('p','Recherche ADS-B non applicable : il faut au moins 2 Méch/s.','hint'));
  else if(!frames.length) frameList.append(element('p','Aucun paquet DF17/18 validé dans cette fenêtre. Cela ne prouve pas l’absence d’autres protocoles.','hint'));
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder==='adsb_1090es' && trial.budget_exhausted) frameList.append(element('p',`Recherche partielle : budget atteint après ${trial.candidates_examined} candidats. Tous les paquets de la fenêtre n’ont pas été examinés.`,'hint'));
  }
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='rtty_ita2') continue;
    if(trial.search_mode==='wideband_spectral_pairs')frameList.append(element('p',`Recherche RTTY : ${trial.channels_examined.length} canaux examinés · ${trial.deferred_channel_count} centres différés. Recherche spectrale bornée, non exhaustive.`,'hint'));
    if(!trial.candidates?.length)continue;
    frameList.append(element('h3','RTTY / ITA2 · texte candidat, sans CRC','frames-title'));
    if(trial.duration_limited)frameList.append(element('p',`Analyse RTTY limitée aux ${trial.analyzed_seconds.toFixed(1)} premières secondes.`,'hint'));
    for(const candidate of trial.candidates){
      const card=element('div',undefined,'frame');
      card.append(element('p',`${candidate.parameters.baud} bauds · écart ${candidate.parameters.shift_hz.toFixed(1)} Hz · ${candidate.evidence.framed_characters} caractères tramés`));
      if(candidate.channel)card.append(element('p',`Canal ${(candidate.channel.frequency_hz/1e6).toFixed(6)} MHz`));
      card.append(element('pre',candidate.text,'rtty-text'));
      frameList.append(card);
    }
  }
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='cw_morse')continue;
    if(trial.channels_examined)frameList.append(element('p',`Recherche Morse : ${trial.channels_examined.length} tonalités examinées · ${trial.deferred_peak_count} pics différés.`,'hint'));
    if(trial.duration_limited)frameList.append(element('p',`Analyse Morse limitée aux ${trial.analyzed_seconds.toFixed(1)} premières secondes.`,'hint'));
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame');
      card.append(element('h3','CW / Morse · texte candidat, sans CRC'));
      card.append(element('p',`${candidate.parameters.words_per_minute.toFixed(1)} mots/min · ${(candidate.channel.frequency_hz/1e6).toFixed(6)} MHz · ${candidate.evidence.characters} caractères`));
      card.append(element('pre',candidate.text,'cw-text'));
      frameList.append(card);
    }
  }
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='fsk2_generic')continue;
    if(trial.channels_examined)frameList.append(element('p',`Recherche 2-FSK : ${trial.channels_examined.length} canaux examinés · ${trial.deferred_channel_count} différés · ${trial.excluded_wide_band_count} bandes trop larges. Recherche non exhaustive.`,'hint'));
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame');
      card.append(element('h3','2-FSK · bits candidats, protocole inconnu'));
      if(candidate.channel)card.append(element('p',`Canal ${(candidate.channel.frequency_hz/1e6).toFixed(6)} MHz`,'fsk-frequency'));
      card.append(element('p',`${candidate.parameters.baud.toFixed(2)} bauds · écart ${candidate.parameters.shift_hz.toFixed(1)} Hz · ${candidate.bit_count} bits`));
      card.append(element('p','Tonalité haute = 1 par convention. Polarité inverse possible ; aucun alignement de trame ni CRC validé.','hint'));
      if(trial.duration_limited || candidate.bit_budget_reached)card.append(element('p','Export partiel : limite de durée ou de bits atteinte.','hint'));
      card.append(element('pre',candidate.bits.slice(0,512),'fsk-bits'));
      for(const [label,name] of Object.entries(candidate.artifacts || {})){
        const link=element('a',label==='bits'?'Télécharger les bits':'Télécharger le binaire compacté');
        link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`;
        link.download=name;card.append(link,document.createTextNode(' '));
      }
      card.append(element('p',`Binaire : premier bit récupéré placé en tête d’octet, ${candidate.packed_padding_bits} bit(s) de remplissage nul à la fin.`,'hint'));
      frameList.append(card);
    }
  }
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='fsk4_generic')continue;
    if(trial.channels_examined)frameList.append(element('p',`Recherche 4-FSK : ${trial.channels_examined.length} canaux examinés · ${trial.deferred_channel_count} différés · ${trial.excluded_wide_band_count} bandes trop larges. Recherche non exhaustive.`,'hint'));
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame');
      card.append(element('h3','4-FSK · symboles candidats, protocole inconnu'));
      if(candidate.channel)card.append(element('p',`Canal ${(candidate.channel.frequency_hz/1e6).toFixed(6)} MHz`,'fsk4-frequency'));
      card.append(element('p',`${candidate.parameters.baud.toFixed(2)} bauds · espacement ${candidate.parameters.spacing_hz.toFixed(1)} Hz · ${candidate.symbol_count} symboles`));
      card.append(element('p','Symboles 0–3 par fréquence croissante. Export bits selon la convention 00/01/10/11 ; correspondance réelle inconnue. Aucune trame ni CRC validé.','hint'));
      if(trial.duration_limited || candidate.bit_budget_reached)card.append(element('p','Export partiel : limite de durée ou de symboles atteinte.','hint'));
      card.append(element('pre',candidate.symbols.slice(0,512),'fsk4-symbols'));
      const labels={symbols:'Télécharger les symboles 4-FSK',bits:'Télécharger les bits 4-FSK (convention)',packed:'Télécharger le binaire 4-FSK (convention)'};
      for(const [kind,name] of Object.entries(candidate.artifacts || {})){
        const link=element('a',labels[kind]);
        link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`;
        link.download=name;card.append(link,document.createTextNode(' '));
      }
      card.append(element('p',`Binaire : premier symbole récupéré en tête d’octet, ${candidate.packed_padding_bits} bit(s) de remplissage nul à la fin.`,'hint'));
      frameList.append(card);
    }
  }
  if(ax25Frames.length)frameList.append(element('h3',`AX.25 UI · ${ax25Frames.length} trame(s) CRC valide(s)`,'frames-title'));
  for(const trial of ax25Trials){
    if(trial.budget_exhausted)frameList.append(element('p',`Recherche AX.25 partielle : limite de trames ou de ${trial.flag_pair_budget} paires de fanions atteinte.`,'hint'));
  }
  for(const frame of ax25Frames){
    const card=element('div',undefined,'frame');
    const f=frame.fields;
    const address=a=>`${a.callsign}${a.ssid?'-'+a.ssid:''}`;
    card.append(element('p',`${address(f.source)} → ${address(f.destination)} · ${frame.line_coding} · CRC-16/X-25 valide`,'ax25-addresses'));
    if(f.via.length)card.append(element('p',`Via : ${f.via.map(address).join(', ')}`));
    card.append(element('p',`t=${frame.time_seconds.toFixed(6)} s · PID 0x${f.pid.toString(16).padStart(2,'0')}${frame.channel?' · '+formatFrequency(frame.channel.frequency_hz):''}`));
    if(f.text!==undefined)card.append(element('pre',f.text,'ax25-text'));
    else card.append(element('code',f.payload_hex));
    card.append(element('p','CRC et structure UI vérifiés ; identité de l’émetteur et interprétation APRS non établies.','hint'));
    frameList.append(card);
  }
  for(const frame of frames) {
    const card=element('div',undefined,'frame');card.append(element('code',frame.hex));
    const f=frame.fields;
    card.append(element('p',`t=${frame.time_seconds.toFixed(6)} s · DF${f.downlink_format} · ${f.icao_hex ? 'ICAO' : 'Adresse'} ${f.address_hex} · type ${f.type_code}`));
    if(f.barometric_altitude_ft!==undefined) card.append(element('p',`Altitude barométrique : ${f.barometric_altitude_ft} ft`));
    frameList.append(card);
  }
}
async function followJob(job) {
  for (;;) {
    await new Promise(resolve=>setTimeout(resolve,450));
    const state=await api(`/api/jobs/${job.id}`,undefined,'GET');
    if(state.status==='failed') throw new Error(state.error);
    if(state.status==='completed') {showReport(state.result,job.id);return;}
  }
}
async function runFile(isDemo) {
  if(busy) return;
  setBusy(true);status(isDemo ? 'Génération et analyse de la démo…' : 'Import de la capture…','busy');
  try {
    let body={demo:isDemo};
    if(!isDemo) {
      const file=$('iq-file').files[0]; if(!file) throw new Error('Choisissez un fichier IQ.');
      if(file.size>128*1024*1024) throw new Error('La limite d’import est de 128 Mio.');
      let metadata=null;
      const meta=$('meta-file').files[0];
      if(meta) {if(meta.size>1024*1024) throw new Error('Métadonnées trop volumineuses.');metadata=JSON.parse(await meta.text());}
      const uploaded=await api('/api/uploads',file);
      body={upload_id:uploaded.upload_id, metadata,sample_rate:Number($('file-rate').value),seconds:Number($('seconds').value)};
    }
    status('Détection des émissions et essais de décodage…','busy');
    const job=await api('/api/analyses',body);await followJob(job);
    $('source-badge').textContent=isDemo ? 'Démo synthétique' : 'Fichier IQ';
    status('Analyse terminée. Sélectionnez une émission pour écouter les candidats audio.','success');
  } catch(error) {status(error.message,'error');}
  finally {setBusy(false);}
}
async function switchTab(live) {
  if(busy) return;
  if(!live && liveMode) {try {await api('/api/live/stop');} catch(error) {status(error.message,'error');}}
  liveMode=live;
  for(const [id,on] of [['tab-live',live],['tab-file',!live]]) {$(id).classList.toggle('active',on);$(id).setAttribute('aria-selected',String(on));}
  $('file-panel').hidden=live;$('live-panel').hidden=!live;
}
$('tab-file').onclick=()=>switchTab(false);$('tab-live').onclick=()=>switchTab(true);
$('iq-file').onchange=()=>{
  const file=$('iq-file').files[0];
  $('filename').textContent=file?.name || 'SigMF · WAV IQ · .sdriq · .cf32';
  const embedded=/\.(wav|sdriq)$/i.test(file?.name || '');
  if(embedded) $('meta-file').value='';
  $('meta-file').disabled=embedded;
  $('file-rate').disabled=embedded;
};
$('analyze').onclick=()=>runFile(false);$('demo').onclick=()=>runFile(true);
$('connect').onclick=async()=>{
  try {
    status('Connexion au serveur rtl_tcp…','busy');
    await api('/api/live/start',{port:Number($('live-port').value),frequency_hz:Math.round(Number($('live-frequency').value)*1e6),sample_rate:Number($('live-rate').value)});
    waterfallRows=[];signals=[];lastLiveSample=-1;lastSnapshot=0;
  } catch(error) {status(error.message,'error');}
};
$('disconnect').onclick=async()=>{try{await api('/api/live/stop');status('Réception arrêtée.');}catch(error){status(error.message,'error');}};
async function pollLive() {
  if(!liveMode || pollingLive) return;
  pollingLive=true;
  try {
    const state=await api('/api/live/status',undefined,'GET');
    liveConnected=state.connected;
    $('connect').disabled=state.running;$('disconnect').disabled=!state.running;
    for(const id of ['live-port','live-rate','live-frequency']) $(id).disabled=state.running;
    $('live-dot').style.background=state.connected ? '#64e5c1' : '#64748b';
    $('connection-text').textContent=state.connected ? `Connecté · ${(state.received_samples/1e6).toFixed(1)} Méch reçus` : state.running ? 'Connexion…' : 'SDR déconnecté';
    if(state.error) {status(state.error,'error');return;}
    if(!state.connected) return;
    const {spectrum}=await api('/api/live/spectrum',undefined,'GET');
    if(spectrum && spectrum.received_samples!==lastLiveSample) {
      lastLiveSample=spectrum.received_samples;currentSpectrum=spectrum;
      center=spectrum.center_frequency_hz;sampleRate=spectrum.sample_rate;
      waterfallRows.unshift(spectrum.power_db);if(waterfallRows.length>180) waterfallRows.pop();
      $('waterfall-label').textContent='Direct · fenêtres reçues, plus récente en haut';
      $('source-badge').textContent='SDR · direct';updateAxes();drawSpectrum();drawWaterfall();
    }
    if($('auto-live').checked && !busy && Date.now()-lastSnapshot>4000 && state.buffered_samples>sampleRate*.25) {
      lastSnapshot=Date.now();setBusy(true);status('Réception active · analyse de la fenêtre récente…','busy');
      api('/api/live/analyze').then(followJob).then(()=>status('Réception active · dernière fenêtre analysée.','success')).catch(error=>status(error.message,'error')).finally(()=>setBusy(false));
    } else if(!busy) status('Réception active · spectre actualisé.','success');
  } catch(error) {status(error.message,'error');}
  finally {pollingLive=false;}
}
setInterval(pollLive,250);
$('capabilities').onclick=async()=>{
  try {
    const data=await api('/api/capabilities',undefined,'GET');$('cap-list').replaceChildren();
    for(const cap of data.decoders) {const row=element('div',undefined,'capability');row.append(element('strong',cap.family));row.append(element('p',`${cap.scope} · ${cap.validation}`));$('cap-list').append(row);}
    $('cap-dialog').showModal();
  }catch(error){status(error.message,'error');}
};
$('close-dialog').onclick=()=>$('cap-dialog').close();
window.addEventListener('resize',()=>{drawSpectrum();drawWaterfall();});
drawSpectrum();drawWaterfall();

$('datasets').onclick=async()=>{
  try {
    const data=await api('/api/datasets',undefined,'GET');
    $('dataset-list').replaceChildren();
    const labels={audio_reference_only:'Référence audio · import IQ indisponible',annotations_validated:'Annotations vérifiées · IQ non importés',validated_subset:'Sous-ensemble validé',documentation_only:'Documentation seulement',adapter_under_validation:'Importateur en validation',window_import_validated:'Import de fenêtre validé'};
    const kinds={receiver_audio_collection:'Collection audio de récepteur',real_recordings:'Captures réelles',real_measurements:'Mesures réelles',synthetic_windows:'Fenêtres synthétiques',synthetic_generator:'Générateur synthétique',aggregate_windows:'Agrégat de fenêtres',real_recording_collection:'Collection de captures',real_recording:'Capture réelle',real_mono_waveforms:'Signaux réels mono'};
    for(const entry of data.entries){
      const card=element('div',undefined,'capability');
      const link=element('a',entry.name);link.href=entry.url;link.target='_blank';link.rel='noopener noreferrer';
      card.append(link,element('p',`${kinds[entry.kind] || entry.kind} · ${labels[entry.status] || entry.status}`));
      if(entry.note)card.append(element('p',entry.note));
      if(entry.id==='panoradio_hf')card.append(element('code','iqscope dataset-import panoradio_hf fichier.npy --record 0 --out extrait'));
      $('dataset-list').append(card);
    }
    $('dataset-dialog').showModal();
  }catch(error){status(error.message,'error');}
};
$('close-datasets').onclick=()=>$('dataset-dialog').close();

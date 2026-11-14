'use strict';
const $ = id => document.getElementById(id);
let audioPlot = false;
let busy = false, liveMode = false, liveConnected = false, pollingLive = false;
let lastLiveAnalysis = null, lastLiveSpectrumSession = null;
let currentLiveSession=null,liveHistorySession=null,liveHistoryRevision=-1;
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
  for (const id of ['analyze','demo','tab-file','tab-live','input-kind','experimental-lora','live-experimental-lora']) $(id).disabled = value;
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
  if(audioPlot){
    $('axis-left').textContent='0 Hz';$('axis-center').textContent=formatFrequency(sampleRate/4);$('axis-right').textContent=formatFrequency(sampleRate/2);
    $('center-label').textContent='Fréquences audio · aucune fréquence RF disponible';
    $('rate-label').textContent=`${sampleRate/1000} kéch/s · mono`;return;
  }
  $('axis-left').textContent=formatFrequency(center-sampleRate/2);
  $('axis-center').textContent=formatFrequency(center);
  $('axis-right').textContent=formatFrequency(center+sampleRate/2);
  $('center-label').textContent=center ? `Centre ${formatFrequency(center)}` : 'Fréquences relatives à la capture';
  $('rate-label').textContent=`${(sampleRate/1e6).toFixed(3)} Méch/s`;
}
function drawPskConstellation(canvas, data) {
  const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,scale=Math.min(w,h)/2.8;
  ctx.fillStyle='#101b2c';ctx.fillRect(0,0,w,h);
  ctx.strokeStyle='#506078';ctx.beginPath();
  ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.moveTo(w/2,0);ctx.lineTo(w/2,h);ctx.stroke();
  ctx.fillStyle='#f1f5fa';ctx.font='12px sans-serif';ctx.fillText('I',w-16,h/2-8);ctx.fillText('Q',w/2+8,16);
  ctx.fillStyle='#61d6bb';
  for(let i=0;i<data.i.length;i++){
    ctx.beginPath();ctx.arc(w/2+data.i[i]*scale,h/2-data.q[i]*scale,2,0,2*Math.PI);ctx.fill();
  }
}
function showReport(report, jobId) {
  audioPlot=report.source_kind==='receiver_audio';
  reportJob=jobId; center=report.center_frequency_hz;sampleRate=report.sample_rate;
  signals=report.signals;selectedSignal=null;currentSpectrum=report.spectrum;
  if(!liveMode) {
    waterfallRows=report.waterfall.power_db;
    $('waterfall-label').textContent='Capture · fenêtres échantillonnées du début vers la fin';
  }
  updateAxes();drawSpectrum();drawWaterfall();
  const frames=(report.wideband_trials || []).filter(t=>t.decoder==='adsb_1090es').flatMap(t=>t.frames || []);
  const ax25Trials=(report.wideband_trials || []).filter(t=>(t.decoder==='ax25_ui' || t.decoder==='afsk1200_ax25' || t.decoder==='afsk1200_fm_ax25'));
  const ax25Frames=ax25Trials.flatMap(t=>t.frames || []);
  const loraFrames=(report.wideband_trials || []).filter(t=>t.decoder==='lora_preamble').flatMap(t=>t.frames || []);
  $('metric-signals').textContent=signals.length;
  $('metric-frames').textContent=frames.length+ax25Frames.length+loraFrames.length;
  $('metric-duration').textContent=`${report.analyzed_seconds.toFixed(2)} s`;
  $('download').href=`/api/jobs/${jobId}/artifacts/report.json`; $('download').hidden=false;
  const list=$('signal-list');list.replaceChildren();
  if(report.interpretation_status==='unverified_byte_order_and_header_layout'){
    list.append(element('p',`Hypothèse de lecture ${report.interpretation_datatype || ''}. Type, ordre des octets et en-tête non validés ; le taux provient d’une convention de nom ou des auteurs, sans mesure indépendante.`,'hint'));
  }
  if(report.recording_provenance){
    const provenance=report.recording_provenance;
    const note=element('div',undefined,'recording-provenance');
    note.append(element('p',`VKSDR · ${provenance.source_label} · ${(provenance.prefix_bytes/1048576).toFixed(2)} Mio reçus · ${report.analyzed_seconds.toFixed(3)} s analysées`));
    note.append(element('p',provenance.header_center_frequency_hz===null?'Centre RF absent de l’en-tête : fréquences relatives à la capture. Les indications du nom de fichier ne sont pas appliquées.':'Centre RF lu dans l’en-tête.','hint'));
    note.append(element('p','Import d’un préfixe seulement ; le mode annoncé et le contenu ne sont pas validés.','hint'));
    const labels={data:'Télécharger les IQ SigMF',metadata:'Télécharger les métadonnées SigMF',provenance:'Télécharger la provenance'};
    for(const [kind,name] of Object.entries(report.recording_artifacts || {})){
      const link=element('a',labels[kind]);link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`;link.download=name;
      note.append(link,document.createTextNode(' '));
    }
    list.append(note);
  }
  if(!signals.length) list.append(element('div',audioPlot?'Audio importé : lecture et essais Morse/RTTY/PSK/AX.25 ci-dessous. Les émissions RF ne sont pas recherchées dans ce mode.':'Aucune bande stationnaire détectée. Les paquets sont recherchés séparément.','empty-results'));
  for(const sig of signals) {
    const details=element('details',undefined,'signal'), summary=element('summary');
    summary.append(element('strong',formatFrequency(sig.frequency_hz)));
    summary.append(element('span',`${(sig.bandwidth_hz/1000).toFixed(2)} kHz · ${sig.spectral_snr_db.toFixed(0)} dB de contraste`));
    details.append(summary);
    details.addEventListener('toggle',()=>{if(details.open){selectedSignal=sig.id;drawSpectrum();}});
    const content=element('div',undefined,'detail');
    if(sig.validated_content?.decoder==='afsk1200_fm_ax25')content.append(element('p',`FM → AFSK1200 · ${sig.validated_content.frame_count} trame(s) AX.25 à CRC valide. Les interprétations applicatives peuvent rester indéterminées.`,'fm-ax25-signal'));
    else if(!sig.decoder_trials.length) content.append(element('p',sig.status==='budget_deferred' ? 'Essais différés : budget de bandes atteint.' : 'Famille inconnue. Aucun contenu validé.','unknown'));
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
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='qam16_generic')continue;
    for(const candidate of trial.candidates || []) {
      const card=element('div',undefined,'frame qam16-candidate');
      card.append(element('h3','16-QAM · symboles candidats, sans CRC'));
      card.append(element('p',`${candidate.parameters.baud.toFixed(2)} bauds · ${candidate.symbol_count} symboles · erreur symbole RMS ${(100*candidate.evidence.symbol_evm_rms).toFixed(1)} %`));
      card.append(element('p',`Correction porteuse : ${candidate.parameters.carrier_offset_hz.toFixed(2)} Hz · filtre RRC essayé α=${candidate.parameters.rrc_rolloff_trial}`));
      if(candidate.channel)card.append(element('p',`Offset du canal : ${candidate.channel.offset_hz.toFixed(1)} Hz`));
      card.append(element('p','Convention binaire arbitraire, rotation et conjugaison inconnues. Protocole non identifié ; aucune charge utile validée.','hint'));
      const canvas=element('canvas');canvas.width=360;canvas.height=260;canvas.style.width='100%';canvas.style.maxWidth='360px';
      canvas.setAttribute('role','img');canvas.setAttribute('aria-label','Constellation 16-QAM, amplitudes relatives conservées');
      card.append(canvas);drawPskConstellation(canvas,candidate.constellation);
      card.append(element('pre',candidate.bits.slice(0,256),'qam16-bits'));
      if(candidate.soft_bits?.status==='likelihood_model_estimated')card.append(element('p','Fiabilité estimée disponible pour chaque bit à l’export.','hint'));
      for(const [kind,name] of Object.entries(candidate.artifacts || {})){
        const label=kind==='soft'?'fiabilité des bits':kind;
        const link=element('a',`Télécharger 16-QAM · ${label}`);link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`;link.download=name;card.append(link);
      }
      frameList.append(card);
    }
    if(trial.artifact){const link=element('a','Télécharger le rapport 16-QAM');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
  }

  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='ao40_fec')continue;
    for(const frame of trial.frames || []) {
      const card=element('div',undefined,'frame ao40-frame');
      card.append(element('h3',`AO-40 FEC · ${frame.payload_bytes} octets`));
      card.append(element('p',`${frame.baud.toFixed(2)} bauds · synchronisation ${65-frame.sync_errors}/65 · corrections RS : ${frame.rs_corrected_symbols.join(', ')}`));
      card.append(element('p','Deux blocs Reed-Solomon vérifiés après Viterbi. Aucun CRC dans ce chemin ; identité et interprétation de télémétrie non établies.','hint ao40-validation'));
      card.append(element('code',frame.payload_hex.slice(0,128)+'…'));
      const telemetry=frame.telemetry;
      if(telemetry?.status==='candidate_interpretation') {
        const section=element('div',undefined,'funcube-telemetry');
        section.append(element('h3','Profil FUNcube-1 FM candidat · télémétrie partielle'));
        section.append(element('p',`Séquence ${telemetry.sequence_number} · code de trame ${telemetry.header.frame_type_code}`,'funcube-sequence'));
        section.append(element('p',`EPS déclaré valide : ${telemetry.source_validity.eps?'oui':'non'} · éclipse : ${telemetry.modes.eclipse?'oui':'non'}`,'funcube-validity'));
        if(!telemetry.source_validity.eps)section.append(element('p','Bloc EPS déclaré invalide : valeurs non confirmées, éventuellement périmées.','hint funcube-stale'));
        for(const measure of telemetry.measurements) {
          const suffix=measure.unit==='count'?'':` ${measure.unit}`;
          section.append(element('p',`${measure.label} : ${measure.value}${suffix}`,'funcube-measurement'));
        }
        section.append(element('p','Interprétation candidate du profil et des unités publiés. Identité et étalonnage indépendants non établis ; températures conservées en codes bruts.','hint'));
        if(frame.telemetry_artifact){const link=element('a','Télécharger la télémétrie FUNcube (JSON)');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(frame.telemetry_artifact)}`;link.download=frame.telemetry_artifact;section.append(link);}
        card.append(section);
      }

      if(frame.payload_artifact){const link=element('a','Télécharger la charge utile AO-40');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(frame.payload_artifact)}`;link.download=frame.payload_artifact;card.append(link);}
      frameList.append(card);
    }
    if(trial.artifact){const link=element('a','Télécharger le rapport AO-40 FEC');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
  }

  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='psk_generic')continue;
    if(trial.frequency_reference==='audio_hz')frameList.append(element('p',`Recherche PSK audio : ${trial.windows_examined.length} fenêtre(s) examinée(s), ${trial.deferred_window_count} différée(s). Signal analytique dérivé de l’audio, aucune fréquence RF.`,'hint psk-audio-search'));
    for(const candidate of trial.candidates || []) {
      const card=element('div',undefined,'frame psk-candidate');
      card.append(element('h3',`${candidate.modulation} · symboles candidats, sans CRC`));
      card.append(element('p',`${candidate.parameters.baud.toFixed(2)} bauds · ${candidate.symbol_count} symboles · correction porteuse ${candidate.parameters.carrier_offset_hz.toFixed(2)} Hz`));
      if(candidate.channel)card.append(element('p',candidate.channel.audio_frequency_hz!==undefined?`Fréquence audio : ${candidate.channel.audio_frequency_hz.toFixed(1)} Hz`:`Offset du canal : ${candidate.channel.offset_hz.toFixed(1)} Hz`));
      if(candidate.evidence.quality_start_seconds>0)card.append(element('p','Contexte de début inclus pour la synchronisation ; seuls les octets des trames à CRC valide sont vérifiés.','hint psk-context-recovery'));
      if(candidate.parameters.amplitude_recovery==='local_rms_64_symbols')card.append(element('p','Correction lente du gain · moyenne sur 64 symboles','hint psk-gain-recovery'));
      if(candidate.parameters.carrier_recovery)card.append(element('p','Suivi de phase BPSK dans cette fenêtre ; pas de continuité entre fenêtres.','hint'));
      if(candidate.parameters.pulse_shape==='rrc_trial')card.append(element('p',`Filtre adapté RRC essayé · α=${candidate.parameters.rrc_rolloff_trial} · erreur symbole RMS ${(100*candidate.evidence.symbol_evm_rms).toFixed(1)} %`,'hint psk-pulse-shape'));
      else card.append(element('p','Impulsions rectangulaires · récupération par transitions','hint psk-pulse-shape'));
      card.append(element('p','Rotation, conjugaison I/Q, correspondance bits/symboles et alignement des octets inconnus. Protocole non identifié.','hint'));
      const canvas=element('canvas');canvas.width=360;canvas.height=260;
      canvas.style.width='100%';canvas.style.maxWidth='360px';canvas.setAttribute('aria-label',`Constellation ${candidate.modulation} normalisée`);canvas.setAttribute('role','img');
      card.append(canvas);drawPskConstellation(canvas,candidate.constellation);
      card.append(element('p','Constellation après correction : amplitude normalisée, au plus 512 symboles échantillonnés.','hint'));
      card.append(element('pre',candidate.bits.slice(0,256),'psk-bits'));
      for(const [kind,name] of Object.entries(candidate.artifacts || {})) {
        const link=element('a',`Télécharger PSK · ${kind}`);link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}`;link.download=name;card.append(link);
      }
      frameList.append(card);
    }
    if(trial.artifact){const link=element('a','Télécharger le rapport PSK');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
  }

  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='rtl433')continue;
    frameList.append(element('h3',`Capteurs OOK / FSK · ${trial.messages.length} message(s)`));
    frameList.append(element('p',trial.status==='unavailable'?'rtl_433 absent : installer le programme pour activer ce décodeur facultatif.':`rtl_433 · ${trial.channels_examined.length} canaux examinés · ${trial.status}`,'hint rtl433-status'));
    for(const message of trial.messages) {
      const card=element('div',undefined,'frame rtl433-message');
      card.append(element('h3',message.fields.model));
      card.append(element('p',`Canal ${message.channel_index+1} · intégrité annoncée par rtl_433 : ${message.integrity_reported_by_decoder || 'non précisée'}. Non revérifiée par IQScope.`,'hint'));
      card.append(element('pre',JSON.stringify(message.fields,null,2)));
      frameList.append(card);
    }
    if(trial.artifact){const link=element('a','Télécharger les valeurs des capteurs (JSON)');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
  }

  if(audioPlot){
    frameList.append(element('h3','Audio de récepteur · Morse, RTTY, PSK, AX.25 et POCSAG'));
    frameList.append(element('p','Fréquences audio uniquement. Morse/RTTY : textes candidats sans CRC. AX.25 : structure et CRC vérifiés. POCSAG : BCH/parité vérifiés, sans CRC.','hint'));
    frameList.append(element('p',`Début de l’enregistrement : ${report.analyzed_seconds.toFixed(2)} s analysées (maximum demandé ${report.requested_seconds} s).`,'hint'));
    if(report.frame_artifact){const link=element('a','Télécharger les trames AX.25 validées');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.frame_artifact)}`;link.download=report.frame_artifact;frameList.append(link);}
    if(report.audio_artifact){
      const player=element('audio');player.id='audio-preview';player.controls=true;player.preload='none';
      player.src=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.audio_artifact)}`;frameList.append(player);
    }
    if(!(report.wideband_trials || []).some(t=>t.candidates?.length || t.messages?.length || t.frames?.length))frameList.append(element('p','Aucun contenu décodé dans cet extrait.','hint'));
  }
  if(!audioPlot)frameList.append(element('h3',`Mode S / ADS-B · ${frames.length} paquet(s) CRC valide(s)`,'frames-title'));
  if(!audioPlot && sampleRate<2e6) frameList.append(element('p','Recherche ADS-B non applicable : il faut au moins 2 Méch/s.','hint'));
  else if(!audioPlot && !frames.length) frameList.append(element('p','Aucun paquet DF17/18 validé dans cette fenêtre. Cela ne prouve pas l’absence d’autres protocoles.','hint'));
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
      if(candidate.channel)card.append(element('p',candidate.channel.audio_frequency_hz!==undefined?`Tonalités audio autour de ${formatFrequency(candidate.channel.audio_frequency_hz)}`:`Canal ${(candidate.channel.frequency_hz/1e6).toFixed(6)} MHz`));
      card.append(element('pre',candidate.text,'rtty-text'));
      if(candidate.text_artifact){const link=element('a','Télécharger le texte RTTY candidat');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(candidate.text_artifact)}`;link.download=candidate.text_artifact;card.append(link);}
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
      card.append(element('p',`${candidate.parameters.words_per_minute.toFixed(1)} mots/min · ${candidate.channel.audio_frequency_hz!==undefined?formatFrequency(candidate.channel.audio_frequency_hz)+' audio':(candidate.channel.frequency_hz/1e6).toFixed(6)+' MHz'} · ${candidate.evidence.characters} caractères`));
      card.append(element('pre',candidate.text,'cw-text'));
      if(candidate.text_artifact){const link=element('a','Télécharger le texte Morse candidat');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(candidate.text_artifact)}`;link.download=candidate.text_artifact;card.append(link);}
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
  for(const trial of report.wideband_trials || []) {
    if(trial.decoder!=='pocsag' || !trial.messages.length)continue;
    frameList.append(element('h3',`POCSAG · ${trial.messages.length} message(s) contrôlé(s)`,'frames-title'));
    frameList.append(element('p',`BCH(31,21) et parité paire vérifiés · au plus ${trial.budgets?.corrected_bits_per_message ?? 0} bits corrigés par message. Aucun CRC ; émetteur non authentifié.`,'hint pocsag-validation'));
    if(trial.budget_exhausted || trial.input_budget_reached || trial.duration_limited || trial.edge_budget_reached)frameList.append(element('p','Recherche POCSAG partielle : une limite de traitement est atteinte.','hint'));
    for(const message of trial.messages) {
      const card=element('div',undefined,'frame pocsag-message');
      const f=message.fields;
      card.append(element('h3',`POCSAG ${message.nominal_baud} · adresse ${f.capcode}`,'pocsag-address'));
      card.append(element('p',`Fonction ${f.function} · ${message.baud.toFixed(2)} bauds · t=${message.time_seconds.toFixed(6)} s`));
      if(message.corrected_bits)card.append(element('p',`Correction BCH : ${message.corrected_bits} bit${message.corrected_bits>1?'s':''} sur le message complet, terminaison comprise. Mots reçus conservés dans le JSON.`,'hint pocsag-corrections'));
      if(message.frontend==='receiver_audio_discriminator')card.append(element('p','Audio démodulé · aucun centre RF déduit.','hint pocsag-audio-reference'));
      if(message.channel && Number.isFinite(message.channel.frequency_hz))card.append(element('p',`Canal ${formatFrequency(message.channel.frequency_hz)}`));
      if(f.message_format==='tone_only')card.append(element('p','Appel sans message.','pocsag-tone-only'));
      else if(f.text!==undefined) {
        card.append(element('p',f.message_format==='numeric'?'Message numérique · espaces finaux conservés':'Message IA5 / ASCII de base','pocsag-format'));
        card.append(element('pre',f.text,'pocsag-text'));
        if(f.reserved_character_present)card.append(element('p','Caractère réservé reçu : code brut conservé dans le rapport.','hint'));
      } else card.append(element('p','Fonction sans interprétation standard sélectionnée ; bits conservés dans le rapport.','hint pocsag-raw'));
      frameList.append(card);
    }
    if(trial.artifact){const link=element('a','Télécharger les messages POCSAG (JSON)');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
  }
  if(ax25Frames.length)frameList.append(element('h3',`AX.25${ax25Frames.some(f=>f.fields.frame_type!=='UI')?'':' UI'} · ${ax25Frames.length} trame(s) CRC valide(s)`,'frames-title'));
  for(const trial of ax25Trials){
    if(trial.frontend==='bpsk_g3ruh' && !trial.frames.length && trial.stream_diagnostics?.some(d=>d.flags_observed))frameList.append(element('p','BPSK : fanions HDLC observés, aucune trame AX.25 UI validée. Le rapport détaille les rejets ; aucune charge utile binaire n’est déduite.','hint psk-ax25-unresolved'));
    if(trial.frontend==='bpsk_g3ruh' && trial.artifact){const link=element('a','Télécharger le rapport AX.25 BPSK');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
    if(trial.decoder==='afsk1200_fm_ax25' && trial.artifact){const link=element('a','Télécharger les trames AX.25 reçues en FM (JSON)');link.className='fm-ax25-download';link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(trial.artifact)}`;link.download=trial.artifact;frameList.append(link);}
    if(trial.budget_exhausted)frameList.append(element('p',`Recherche AX.25 partielle : limite de trames ou de ${trial.flag_pair_budget} paires de fanions atteinte.`,'hint'));
  }
  for(const frame of ax25Frames){
    const card=element('div',undefined,'frame');
    const f=frame.fields;
    const address=a=>`${a.callsign}${a.ssid?'-'+a.ssid:''}`;
    card.append(element('p',`${address(f.source)} → ${address(f.destination)} · ${frame.line_coding} · CRC-16/X-25 valide`,'ax25-addresses'));
    if(frame.frontend==='bpsk_g3ruh')card.append(element('p','BPSK · G3RUH · CRC vérifié par IQScope','psk-ax25-integrity'));
    if(frame.frontend==='fm_iq_afsk1200')card.append(element('p','FM → AFSK1200 · CRC vérifié par IQScope','fm-ax25-integrity'));
    if(frame.wire_artifact){const link=element('a','Télécharger la trame AX.25 complète (binaire)');link.className='ax25-wire-download';link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(frame.wire_artifact)}`;link.download=frame.wire_artifact;card.append(link);}
    if(frame.payload_artifact){const link=element('a',frame.frontend==='fm_iq_afsk1200'?'Télécharger la charge utile AX.25 FM':'Télécharger la charge utile AX.25 BPSK');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(frame.payload_artifact)}`;link.download=frame.payload_artifact;card.append(link);}
    if(f.via.length)card.append(element('p',`Via : ${f.via.map(address).join(', ')}`));
    const channel=frame.channel;
    const channelLabel=channel?(channel.audio_frequency_hz!==undefined?' · '+formatFrequency(channel.audio_frequency_hz)+' audio':channel.rf_center_known===false?' · décalage '+formatFrequency(channel.offset_hz)+' (centre RF non renseigné)':Number.isFinite(channel.frequency_hz)?' · '+formatFrequency(channel.frequency_hz):Number.isFinite(channel.offset_hz)?' · offset '+formatFrequency(channel.offset_hz):''):'';
    card.append(element('p',`t=${frame.time_seconds.toFixed(6)} s${Number.isInteger(f.pid)?' · PID 0x'+f.pid.toString(16).padStart(2,'0'):''}${channelLabel}`));
    if(f.frame_type!=='UI'){
      const type=f.frame_type==='S'?f.supervisory_function:f.frame_type==='U'?f.unnumbered_function:'I';
      card.append(element('p',`Trame AX.25 ${type}${f.control_mode?' · '+f.control_mode.replace('_',' '):' · mode de contrôle non établi'}`,'ax25-link-type'));
      if(Number.isInteger(f.n_r))card.append(element('p',`N(R)=${f.n_r} · bit P/F=${f.poll_final_bit?1:0}`,'ax25-link-sequence'));
      card.append(element('code',f.link_body_hex,'ax25-link-body'));
      for(const c of f.control_candidates || []){
        card.append(element('p',`Hypothèse ${c.mode.replace('_',' ')} : N(S)=${c.n_s}, N(R)=${c.n_r}, P/F=${c.poll_final_bit?1:0}, PID 0x${c.pid.toString(16).padStart(2,'0')}`,'ax25-control-candidate'));
        if(c.text!==undefined)card.append(element('pre',c.text,'ax25-link-text-candidate'));
        else if(c.payload_hex!==undefined)card.append(element('code',c.payload_hex,'ax25-link-hex-candidate'));
      }
      card.append(element('p','État de connexion non reconstitué ; les hypothèses de trame I ne sélectionnent aucun contenu applicatif.','hint ax25-link-scope'));
    }
    if(f.frame_type==='UI'){
      if(f.text!==undefined)card.append(element('pre',f.text,'ax25-text'));
      else card.append(element('code',f.payload_hex));
    }
    const aprs=f.aprs;
    if(aprs?.telemetry){
      const t=aprs.telemetry;
      const sequence=t.sequence.kind==='MIC'?'MIC':t.encoding==='base91_comment'?t.sequence.value:t.sequence.raw;
      card.append(element('h3',`Télémétrie APRS${t.encoding==='base91_comment'?' base 91':''} · séquence ${sequence}`,'aprs-telemetry'));
      card.append(element('p',t.analog_raw.map((v,i)=>`A${i+1}=${v}`).join(' · '),'aprs-telemetry-analog'));
      if(t.digital_bits)card.append(element('p',t.digital_bits.map((v,i)=>`B${i+1}=${v}`).join(' · '),'aprs-telemetry-digital'));
      else card.append(element('p','Canaux binaires non transmis.','hint aprs-telemetry-digital-missing'));
      if(t.digital_reserved_value)card.append(element('p','Bits réservés reçus : conservés dans le JSON sans interprétation en canaux supplémentaires.','hint aprs-telemetry-reserved'));
      const associated=t.definition_context?.status==='associated_declared_metadata';
      card.append(element('p',associated?'Valeurs brutes conservées ; définitions déclarées associées avec provenance. Émetteur et mesures non authentifiés ; aucune conversion d’unité implicite.':'Valeurs brutes ; unités, calibration, noms et sens actif des bits non appliqués.','hint aprs-telemetry-scope'));
      if(associated){
        if(t.project_title)card.append(element('p',`Projet déclaré : ${t.project_title}`,'aprs-telemetry-project'));
        for(const c of t.analog_channels || []){
          if(c.name || c.unit || Number.isFinite(c.value))card.append(element('p',`A${c.channel}${c.name?` « ${c.name} »`:''} · brut ${c.raw_value}${Number.isFinite(c.value)?` → ${Number(c.value.toPrecision(10))}${c.unit?` ${c.unit}`:' · unité inconnue'}`:c.unit?` · unité déclarée ${c.unit}, conversion non disponible`:' · unité inconnue'}`,'aprs-telemetry-calibrated'));
          if(c.value_status==='non_finite_result; no value selected')card.append(element('p',`A${c.channel} : résultat non fini, aucune valeur calculée sélectionnée.`,'hint aprs-telemetry-calibration-unresolved'));
        }
        for(const c of t.digital_channels || [])if(c.label && typeof c.matches_declared_sense==='boolean')card.append(element('p',`B${c.channel}${c.name?` « ${c.name} »`:''} · ${c.label} : ${c.matches_declared_sense?'indiqué':'non indiqué'} par le sens déclaré`,'aprs-telemetry-labeled-bit'));
        const provenance=Object.entries(t.definition_context.definitions).map(([kind,d])=>`${kind} : trame ${d.frame_index+1}, reçue jusqu’à ${d.received_end_seconds.toFixed(6)} s, âge ${d.age_seconds.toFixed(3)} s`).join(' · ');
        card.append(element('p',provenance,'hint aprs-telemetry-provenance'));
      }
      if(t.comment)card.append(element('pre',t.comment,'aprs-telemetry-comment'));
    }else if(aprs?.requested_profile==='classic_t_hash_8bit')card.append(element('p','Rapport T# hors profil classique ou mal formé : aucune valeur numérique déduite.','hint aprs-telemetry-unresolved'));
    if(aprs?.comment_telemetry_status && aprs.comment_telemetry_status!=='decoded_comment_telemetry')card.append(element('p','Extension de télémétrie en commentaire non interprétée : aucune valeur partielle déduite.','hint aprs-comment-telemetry-unresolved'));
    if(aprs?.definition){
      const d=aprs.definition;
      card.append(element('p',`Définition APRS ${d.kind} pour « ${d.addressee_raw} » · ${aprs.status==='decoded_telemetry_definition'?'syntaxe reconnue':'hors profil ou mal formée'}`,'aprs-telemetry-definition'));
      card.append(element('p',d.association_eligibility==='self_addressed_claim'?'Annonce adressée au même indicatif/SSID ; association limitée au même canal et aux mesures ultérieures.':'Définition conservée sans association automatique à cette source.','hint'));
    }
    if(aprs?.entity){
      const e=aprs.entity;
      card.append(element('p',`${e.kind==='object'?'Objet':'Item'} APRS « ${e.name} » · ${e.state_reported==='live'?'annoncé actif':'retrait déclaré'}`,'aprs-entity'));
      card.append(element('p',`Annonce de ${address(f.source)} ; la position concerne le point nommé, pas l’émetteur. Identité et autorité non vérifiées.`,'hint aprs-entity-source'));
    }
    if(aprs?.status==='retracted_entity')card.append(element('p','Annonce de retrait conservée ; aucune position active affichée. Aucune suppression automatique d’autres annonces.','hint aprs-entity-retracted'));
    else if(aprs?.status==='unresolved_entity_retraction')card.append(element('p','Marqueur de retrait reçu, contenu de position non interprété.','hint aprs-entity-unresolved'));
    else if(aprs?.status==='unsupported_area_entity')card.append(element('p','Objet de zone : géométrie non interprétée, aucune position ponctuelle déduite.','hint aprs-entity-unresolved'));
    if(aprs?.status==='decoded_position'){
      const compressed=aprs.format==='compressed';
      const digits=compressed?6:5;
      card.append(element('p',`Position APRS : ${aprs.latitude_deg.toFixed(digits)}°, ${aprs.longitude_deg.toFixed(digits)}°`,'aprs-position'));
      card.append(element('p',compressed?'Format compressé en base 91 ; précision réelle inconnue.':'Résolution encodée : 0,01 minute d’arc ; précision réelle inconnue.','hint aprs-format'));
      if(Number.isFinite(aprs.course_deg))card.append(element('p',`Route ${aprs.course_deg}° · vitesse ${Number.isInteger(aprs.speed_knots)?aprs.speed_knots:aprs.speed_knots.toFixed(2)} kn (${aprs.speed_m_s.toFixed(2)} m/s)`,'aprs-motion'));
      if(Number.isFinite(aprs.altitude_ft))card.append(element('p',`Altitude ${Number.isInteger(aprs.altitude_ft)?aprs.altitude_ft:aprs.altitude_ft.toFixed(1)} ft (${aprs.altitude_m.toFixed(1)} m) · référence non précisée`,'aprs-altitude'));
      if(aprs.altitude_status==='multiple_encodings; no value selected')card.append(element('p','Plusieurs encodages d’altitude reçus : aucune valeur sélectionnée.','hint aprs-altitude-unresolved'));
      if(Number.isFinite(aprs.radio_range_m))card.append(element('p',`Portée radio déclarée : ${(aprs.radio_range_m/1000).toFixed(2)} km · valeur de modèle, pas une mesure de réception`,'aprs-range'));
      if(aprs.compression_type)card.append(element('p',`Fix GPS déclaré ${aprs.compression_type.gps_fix_reported==='current'?'courant':'ancien'} · source déclarée ${aprs.compression_type.nmea_source_reported} · non vérifié indépendamment`,'hint aprs-fix'));
      if(aprs.timestamp?.raw)card.append(element('p',`Horodatage APRS ${aprs.timestamp.raw} · ${aprs.timestamp.time_basis==='UTC'?'UTC':'heure locale, fuseau inconnu'} · date complète inconnue`,'aprs-timestamp'));
    }else if(aprs?.status==='ambiguous_position')card.append(element('p','Position APRS ambiguë : aucune coordonnée ponctuelle déduite.','aprs-position-unresolved'));
    else if(aprs?.status==='null_position')card.append(element('p','Position APRS signalée inconnue : aucune coordonnée déduite.','aprs-position-unresolved'));
    card.append(element('p',f.frame_type==='UI'?'CRC et structure UI vérifiés ; identité de l’émetteur et contenu déclaré non vérifiés indépendamment.':'CRC, adresses et profil de contrôle vérifiés ; état de connexion et identité de l’émetteur non vérifiés.','hint'));
    frameList.append(card);
  }
  for(const trial of report.wideband_trials || []){
    if(trial.decoder!=='ofdm_cp')continue;
    if(trial.sample_budget_reached)frameList.append(element('p',`Recherche de préfixe cyclique : ${trial.analyzed_samples} échantillons répartis en fenêtres, soit ${trial.analyzed_seconds.toFixed(4)} s réellement examinées.`,'hint'));
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame ofdm-candidate');const p=candidate.parameters;
      card.append(element('h3','Répétition compatible avec un préfixe cyclique'));
      card.append(element('p',`${p.useful_samples} échantillons utiles · garde ${p.guard_samples} · période ${p.symbol_samples}`,'ofdm-parameters'));
      card.append(element('p',`Durée utile ${(p.useful_seconds*1e6).toFixed(2)} µs · garde ${(p.guard_seconds*1e6).toFixed(2)} µs · corrélation ${candidate.evidence.folded_prefix_correlation.toFixed(3)}`));
      card.append(element('p','Structure compatible OFDM ; protocole inconnu. Aucun bit ni contenu extrait.','hint'));
      frameList.append(card);
    }
    if(report.ofdm_artifact){const link=element('a','Télécharger les indices de préfixe cyclique');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.ofdm_artifact)}`;link.download=report.ofdm_artifact;frameList.append(link);}
  }
  for(const trial of report.wideband_trials || []){
    if(trial.decoder!=='lora_preamble')continue;
    if(trial.mode==='experimental_guarded')frameList.append(element('p','LoRa expérimental activé · validation radio encore limitée.','hint lora-experimental-mode'));
    if(trial.temporal_search?.partial)frameList.append(element('p','Recherche LoRa partielle dans le fichier ; les périodes examinées figurent dans le rapport.','hint lora-search-coverage'));
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame lora-candidate');const p=candidate.parameters;
      card.append(element('h3','Chirps répétés compatibles avec un préambule LoRa'));
      card.append(element('p',`SF${p.spreading_factor} · largeur ${p.bandwidth_hz/1000} kHz · ${candidate.evidence.repeated_chirps} chirps répétés`));
      if(candidate.synchronization?.status==='opposite_chirp_pair_candidate')card.append(element('p',`Paire de chirps opposés candidate vers ${candidate.synchronization.time_seconds.toFixed(6)} s ; limite de paquet et sync word non validés.`,'lora-sync-evidence'));
      if(candidate.sync_word?.status==='sync_word_candidate')card.append(element('p',`Sync word candidat : 0x${candidate.sync_word.value_hex} ; aucun réseau ni paquet authentifié.`,'lora-sync-word'));
      if(['raw_css_symbol_candidates','research_guarded_css_symbols'].includes(candidate.data_symbols?.status)){
        card.append(element('p',`${candidate.data_symbols.symbol_bins.length} symboles CSS bruts candidats avant décodage.`,'lora-data-symbols'));
        card.append(element('code',candidate.data_symbols.symbol_bins.slice(0,16).join(', ')));
        if(['insufficient_spectral_concentration','unstable_phase_estimate'].includes(candidate.data_symbols.stop_reason))card.append(element('p','Lecture arrêtée sur un symbole insuffisamment fiable ; la séquence peut être incomplète.','hint'));
        if(candidate.data_symbols.symbol_budget_reached)card.append(element('p','Limite de 64 symboles atteinte ; la séquence peut être incomplète.','hint'));
      }
      if(candidate.explicit_header?.status==='header_checksum_valid'){
        const h=candidate.explicit_header;
        card.append(element('p',`En-tête explicite candidat : ${h.payload_length_bytes} octets annoncés · codage ${h.coding_rate} · CRC de données ${h.payload_crc_present?'annoncé':'absent'}.`,'lora-header'));
        card.append(element('p','Somme d’en-tête de 5 bits vérifiée.','hint'));
      }
      if(candidate.sync_word?.status==='ambiguous_sync_word')card.append(element('p','Sync word ambigu : aucune valeur sélectionnée.','hint'));
      if(candidate.payload?.status!=='payload_crc_valid')card.append(element('p','Charge utile non validée ; consulter le rapport pour les limites de décodage.','hint'));
      frameList.append(card);
    }
    for(const frame of trial.frames || []){
      const card=element('div',undefined,'frame lora-payload');
      card.append(element('h3','LoRa · charge utile à CRC16 valide'));
      card.append(element('p',`${frame.payload_length_bytes} octets · codage ${frame.coding_rate || 'inconnu'} · somme d’en-tête et CRC de données vérifiés`));
      if(frame.quarter_chirp_validated===false)card.append(element('p','Limite des données inférée depuis la synchronisation ; quart de chirp non confirmé. En-tête et CRC de données vérifiés.','hint lora-inferred-boundary'));
      if(frame.soft_symbol_corrections?.length)card.append(element('p',`${frame.soft_symbol_corrections.length} symbole CSS corrigé par parité et score spectral avant le contrôle du CRC.`,'lora-soft-corrections'));
      const corrections=(frame.corrected_payload_codeword_bits || 0)+(frame.corrected_spillover_bits || 0);
      if(corrections)card.append(element('p',`${corrections} bit${corrections>1?'s':''} de codeword corrigé${corrections>1?'s':''} dans les données.`,'lora-fec-corrections'));
      if(frame.text!==undefined)card.append(element('pre',frame.text,'lora-payload-text'));
      else card.append(element('code',frame.payload_hex));
      card.append(element('p','CRC cohérent ; identité de l’émetteur et interprétation LoRaWAN non établies.','hint'));
      if(frame.artifact){const link=element('a','Télécharger la charge utile LoRa');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(frame.artifact)}`;link.download=frame.artifact;card.append(link);}
      frameList.append(card);
    }
    if(report.lora_artifact){const link=element('a','Télécharger le rapport LoRa');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.lora_artifact)}`;link.download=report.lora_artifact;frameList.append(link);}
  }
  for(const frame of frames) {
    const card=element('div',undefined,'frame');card.append(element('code',frame.hex));
    const f=frame.fields;
    card.append(element('p',`t=${frame.time_seconds.toFixed(6)} s · DF${f.downlink_format} · ${f.icao_hex ? 'ICAO' : 'Adresse'} ${f.address_hex} · type ${f.type_code}`));
    if(f.barometric_altitude_ft!==undefined) card.append(element('p',`Altitude barométrique : ${f.barometric_altitude_ft} ft`));
    if(f.callsign) card.append(element('p',`Indicatif : ${f.callsign}`,'adsb-callsign'));
    if(Number.isFinite(f.latitude_deg) && Number.isFinite(f.longitude_deg)) {
      card.append(element('p',`Position diffusée : ${f.latitude_deg.toFixed(5)}°, ${f.longitude_deg.toFixed(5)}°`,'adsb-position'));
      card.append(element('p','Position reconstruite depuis deux trames CRC valides ; émetteur non authentifié.','hint'));
    } else if(f.cpr) card.append(element('p','Position non résolue : une paire aérienne compatible est nécessaire.','hint adsb-position-pending'));
    const v=f.velocity;
    if(v) {
      if(Number.isFinite(v.ground_speed_kt)) card.append(element('p',`Vitesse au sol : ${v.ground_speed_kt.toFixed(1)} kt`,'adsb-ground-speed'));
      if(Number.isFinite(v.ground_track_deg)) card.append(element('p',`Route au sol : ${v.ground_track_deg.toFixed(2)}°`,'adsb-ground-track'));
      if(Number.isFinite(v.airspeed_kt)) card.append(element('p',`Vitesse air ${v.airspeed_kind} : ${v.airspeed_kt.toFixed(1)} kt`,'adsb-airspeed'));
      if(Number.isFinite(v.heading_deg)) {
        const label=v.heading_reference==='true_north'?'Cap vrai diffusé':v.heading_reference==='magnetic_north'?'Cap magnétique diffusé':'Cap diffusé';
        const suffix=v.heading_reference==='not_determined_from_tc19'?' · référence vraie/magnétique non déterminée':'';
        card.append(element('p',`${label} : ${v.heading_deg.toFixed(2)}°${suffix}`,'adsb-heading'));
      }
      if(Number.isFinite(v.horizontal_velocity_error_95_bound_m_s)) card.append(element('p',`Précision de vitesse déclarée : < ${v.horizontal_velocity_error_95_bound_m_s} m/s à 95 % (NACv ${v.nac_v_code})`,'adsb-velocity-accuracy'));
      else if(v.nac_v_code!==undefined) card.append(element('p',`Précision de vitesse ${v.nac_v_status==='reserved_code'?'non interprétée':'non renseignée'} (NACv ${v.nac_v_code})`,'hint adsb-velocity-accuracy'));
      if(Number.isFinite(v.vertical_rate_ft_min)) {
        const source=v.vertical_rate_source==='barometric'?'barométrique':'GNSS';
        card.append(element('p',`Vitesse verticale : ${v.vertical_rate_ft_min} ft/min (${source})`,'adsb-vertical-rate'));
      }
    }
    const operational=f.operational_status;
    if(operational) {
      if(operational.status==='decoded') {
        card.append(element('p',`Statut ADS-B v${operational.adsb_version} · ${operational.environment==='airborne'?'aérien':'surface'}`,'adsb-operational-status'));
        appendAdsbQuality(card,operational);
      } else {
        const detail=operational.status==='unsupported_version'?`version ${operational.version_code}`:`sous-type ${operational.subtype}`;
        card.append(element('p',`Statut ADS-B non interprété : ${detail}.`,'hint adsb-operational-status'));
      }
    }
    if(f.position_quality) appendAdsbQuality(card,f.position_quality);
    if(f.position_integrity_pair) appendAdsbNic(card,f.position_integrity_pair,true);
    else if(f.position_integrity && f.position_integrity.status!=='operational_context_required') appendAdsbNic(card,f.position_integrity,false);
    frameList.append(card);
  }
}
function appendAdsbNic(card,value,paired) {
  const role=paired?'paire CPR':'message';
  const css=paired?'adsb-pair-integrity':'adsb-frame-integrity';
  if(value.status==='reported_bound' && Number.isFinite(value.containment_radius_bound_m)) card.append(element('p',`Confinement déclaré de la ${paired?'paire CPR':'position du message'} : NIC ${value.nic_category} · Rc < ${value.containment_radius_bound_m} m`,css));
  else if(value.status==='not_available') card.append(element('p',`Confinement non renseigné (${role}, NIC 0).`,'hint '+css));
  else card.append(element('p',`NIC non déterminé (${role}).`,'hint '+css));
}

function appendAdsbQuality(card,q) {
  if(Number.isFinite(q.horizontal_accuracy_95_bound_m)) card.append(element('p',`Précision horizontale déclarée : < ${q.horizontal_accuracy_95_bound_m} m à 95 % (NACp ${q.nac_p_code})`,'adsb-position-accuracy'));
  else card.append(element('p',`Précision horizontale ${q.nac_p_status==='reserved_code'?'non interprétée':'non renseignée'} (NACp ${q.nac_p_code})`,'hint adsb-position-accuracy'));
  if(q.sil_code===0) card.append(element('p','SIL 0 : intégrité non renseignée.','hint adsb-integrity'));
  else {
    const basis=q.sil_probability_basis==='per_hour'?'par heure':q.sil_probability_basis==='per_sample'?'par échantillon':'base de probabilité non déterminée';
    card.append(element('p',`Intégrité déclarée : SIL ${q.sil_code} · ${basis}`,'adsb-integrity'));
  }
}

async function followJob(job) {
  for (;;) {
    await new Promise(resolve=>setTimeout(resolve,450));
    const state=await api(`/api/jobs/${job.id}`,undefined,'GET');
    if(state.status==='failed') throw new Error(state.error);
    if(state.status==='completed') {showReport(state.result,job.id);return state.result;}
  }
}
async function runFile(isDemo) {
  if(busy) return;
  let uploadedId=null;
  setBusy(true);status(isDemo ? 'Génération et analyse de la démo…' : 'Import de la capture…','busy');
  try {
    let body={demo:isDemo,experimental_lora:$('experimental-lora').checked};
    if(!isDemo) {
      const file=$('iq-file').files[0]; if(!file) throw new Error('Choisissez un fichier IQ.');
      if(file.size>128*1024*1024) throw new Error('La limite d’import est de 128 Mio.');
      let metadata=null;
      const audioInput=$('input-kind').value==='audio';
      const meta=audioInput?null:$('meta-file').files[0];
      if(meta) {if(meta.size>1024*1024) throw new Error('Métadonnées trop volumineuses.');metadata=JSON.parse(await meta.text());}
      const uploaded=await api('/api/uploads',file);uploadedId=uploaded.upload_id;
      body={upload_id:uploaded.upload_id,input_kind:audioInput?'audio':'iq',metadata,sample_rate:Number($('file-rate').value),seconds:Number($('seconds').value),experimental_lora:!audioInput && $('experimental-lora').checked};
    }
    status('Détection des émissions et essais de décodage…','busy');
    const job=await api('/api/analyses',body);await followJob(job);
    $('source-badge').textContent=isDemo?'Démo synthétique':audioPlot?'Audio · fréquences audio':'Fichier IQ';
    status(audioPlot?'Analyse terminée. Audio et résultats Morse/RTTY/PSK/AX.25 disponibles.':'Analyse terminée. Sélectionnez une émission pour écouter les candidats audio.','success');
  } catch(error) {status(error.message,'error');}
  finally {
    if(uploadedId){try{await api(`/api/uploads/${encodeURIComponent(uploadedId)}`,undefined,'DELETE');}catch{/* A still-running job keeps its source until it finishes. */}}
    setBusy(false);
  }
}
async function switchTab(live) {
  if(busy) return;
  if(!live && liveMode) {try {await api('/api/live/stop');} catch(error) {status(error.message,'error');}}
  liveMode=live;
  for(const [id,on] of [['tab-live',live],['tab-file',!live]]) {$(id).classList.toggle('active',on);$(id).setAttribute('aria-selected',String(on));}
  $('file-panel').hidden=live;$('live-panel').hidden=!live;
}
$('tab-file').onclick=()=>switchTab(false);$('tab-live').onclick=()=>switchTab(true);
function updateFileInput(){
  const file=$('iq-file').files[0];
  const audio=$('input-kind').value==='audio';
  $('experimental-lora-option').hidden=audio;
  if(audio)$('experimental-lora').checked=false;
  $('filename').textContent=file?.name || (audio?'MP3 · WAV audio':'SigMF · WAV IQ · .sdriq · .cf32');
  $('iq-file').accept=audio?'.mp3,.wav':'.sigmf-data,.cf32,.iq,.bin,.wav,.sdriq';
  const embedded=audio || /\.(wav|sdriq)$/i.test(file?.name || '');
  if(embedded)$('meta-file').value='';
  $('meta-file').disabled=embedded;$('file-rate').disabled=embedded;
  $('meta-file').closest('label').hidden=audio;$('file-rate').closest('label').hidden=audio;
  $('audio-input-hint').hidden=!audio;$('iq-input-hint').hidden=audio;
  $('seconds').max=audio?'20':'120';$('seconds').min=audio?'1':'0.01';
  if(audio)$('seconds').value=String(Math.max(1,Math.min(20,Number($('seconds').value))));
}
$('iq-file').onchange=updateFileInput;$('input-kind').onchange=updateFileInput;
$('analyze').onclick=()=>runFile(false);$('demo').onclick=()=>runFile(true);
$('connect').onclick=async()=>{
  try {
    status('Connexion au serveur rtl_tcp…','busy');
    await api('/api/live/start',{port:Number($('live-port').value),frequency_hz:Math.round(Number($('live-frequency').value)*1e6),sample_rate:Number($('live-rate').value)});
    waterfallRows=[];signals=[];lastLiveSample=-1;lastSnapshot=0;lastLiveAnalysis=null;lastLiveSpectrumSession=null;
    $('live-coverage').textContent='Aucune fenêtre SDR analysée.';
    currentLiveSession=null;liveHistorySession=null;liveHistoryRevision=-1;
    $('live-packet-list').replaceChildren();$('live-history-summary').textContent='Aucun événement estimé conservé.';
  } catch(error) {status(error.message,'error');}
};
$('disconnect').onclick=async()=>{try{await api('/api/live/stop');status('Réception arrêtée.');}catch(error){status(error.message,'error');}};
async function refreshLiveHistory(expectedSession){
  if(expectedSession!==currentLiveSession)return;
  const history=await api('/api/live/frames',undefined,'GET');
  if(history.session_id!==expectedSession || currentLiveSession!==expectedSession)return;
  if(liveHistorySession===history.session_id && liveHistoryRevision>=history.revision)return;
  liveHistorySession=history.session_id;liveHistoryRevision=history.revision;
  const events=history.events || [],shown=events.slice(0,12);
  $('live-history-summary').textContent=`${events.length} événements estimés conservés · ${shown.length} affichés · ${history.evicted_events} anciens écartés.`;
  const list=$('live-packet-list');list.replaceChildren();
  for(const event of shown){
    const card=element('div',undefined,'frame live-packet');card.dataset.eventId=event.id;
    card.append(element('p',`t ≈ ${event.time_seconds_estimate.toFixed(6)} s dans la session reçue · SF${event.parameters.spreading_factor} · ${event.parameters.bandwidth_hz/1000} kHz`));
    card.append(element('pre',event.text===undefined?event.payload_hex:event.text,'live-packet-text'));
    card.append(element('p',`${event.observation_count} observation${event.observation_count>1?'s':''} · ${event.modes.map(m=>m==='experimental_guarded'?'expérimental':'standard').join(', ')}`,'live-packet-observations'));
    if(!event.quarter_chirp_confirmed_in_any_observation)card.append(element('p','Quart de chirp non confirmé.','hint'));
    const link=element('a','Télécharger ce paquet LoRa');
    const binary=event.payload_hex.match(/../g).map(hex=>String.fromCharCode(parseInt(hex,16))).join('');
    link.href=`data:application/octet-stream;base64,${btoa(binary)}`;link.download=`lora-live-${event.id}.bin`;
    card.append(link);list.append(card);
  }
}

async function pollLive() {
  if(!liveMode || pollingLive) return;
  pollingLive=true;
  try {
    const state=await api('/api/live/status',undefined,'GET');
    liveConnected=state.connected;currentLiveSession=state.session_id;
    if(liveHistorySession!==state.session_id || liveHistoryRevision!==state.history_revision)await refreshLiveHistory(state.session_id);
    $('connect').disabled=state.running;$('disconnect').disabled=!state.running;
    for(const id of ['live-port','live-rate','live-frequency']) $(id).disabled=state.running;
    $('live-dot').style.background=state.connected ? '#64e5c1' : '#64748b';
    $('connection-text').textContent=state.connected ? `Connecté · ${(state.received_samples/1e6).toFixed(1)} Méch reçus` : state.running ? 'Connexion…' : 'SDR déconnecté';
    if(state.error) {status(state.error,'error');return;}
    if(!state.connected) return;
    const {spectrum}=await api('/api/live/spectrum',undefined,'GET');
    if(spectrum && (spectrum.received_samples!==lastLiveSample || spectrum.session_id!==lastLiveSpectrumSession)) {
      if(lastLiveSpectrumSession && spectrum.session_id!==lastLiveSpectrumSession)waterfallRows=[];
      lastLiveSample=spectrum.received_samples;lastLiveSpectrumSession=spectrum.session_id;currentSpectrum=spectrum;
      audioPlot=false;center=spectrum.center_frequency_hz;sampleRate=spectrum.sample_rate;
      waterfallRows.unshift(spectrum.power_db);if(waterfallRows.length>180) waterfallRows.pop();
      $('waterfall-label').textContent='Direct · fenêtres reçues, plus récente en haut';
      $('source-badge').textContent='SDR · direct';updateAxes();drawSpectrum();drawWaterfall();
    }
    const experimental=$('live-experimental-lora').checked;
    const fresh=!lastLiveAnalysis || lastLiveAnalysis.session!==state.session_id || lastLiveAnalysis.experimental!==experimental || state.received_samples>lastLiveAnalysis.end;
    if($('auto-live').checked && fresh && !busy && Date.now()-lastSnapshot>4000 && state.buffered_samples>state.sample_rate*.25) {
      lastSnapshot=Date.now();setBusy(true);status('Réception active · analyse de la fenêtre récente…','busy');
      api('/api/live/analyze',{experimental_lora:experimental}).then(followJob).then(async result=>{
        const previous=lastLiveAnalysis;
        const start=result.source_sample_start,end=result.source_sample_end,session=result.source_session_id,fs=result.sample_rate;
        let detail='Première fenêtre de cette session.';
        if(previous?.session===session){
          const gap=Math.max(0,start-previous.end)/fs;
          const overlap=Math.max(0,Math.min(previous.end,end)-start)/fs;
          detail=gap>0 ? `${Math.max(0,start-previous.end)} échantillons reçus non analysés (${gap.toFixed(3)} s) entre ces fenêtres.` : `Recouvrement avec la précédente : ${overlap.toFixed(3)} s.`;
        }
        lastLiveAnalysis={session,end,experimental};
        $('live-coverage').textContent=`Fenêtre analysée : ${((end-start)/fs).toFixed(3)} s. ${detail}`;
        await refreshLiveHistory(session);
        status('Réception active · dernière fenêtre analysée.','success');
      }).catch(error=>status(error.message,'error')).finally(()=>setBusy(false));
    } else if(!busy) status(fresh ? 'Réception active · spectre actualisé.' : 'Réception active · en attente de nouveaux échantillons.','success');
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
    const vksdr=await api('/api/recordings/vksdr',undefined,'GET');
    $('dataset-list').replaceChildren();
    const labels={candidate_conversion_available:'Conversion candidate · format non certifié',audio_import_available:'Import audio disponible · texte candidat',audio_reference_only:'Référence audio · import IQ indisponible',annotations_validated:'Annotations vérifiées · IQ non importés',validated_subset:'Sous-ensemble validé',documentation_only:'Documentation seulement',adapter_under_validation:'Importateur en validation',window_import_validated:'Import de fenêtre validé'};
    const kinds={derived_features:'Caractéristiques dérivées · pas des IQ',receiver_audio_collection:'Collection audio de récepteur',real_recordings:'Captures réelles',real_measurements:'Mesures réelles',synthetic_windows:'Fenêtres synthétiques',synthetic_generator:'Générateur synthétique',aggregate_windows:'Agrégat de fenêtres',real_recording_collection:'Collection de captures',real_recording:'Capture réelle',real_mono_waveforms:'Signaux réels mono'};
    for(const entry of data.entries){
      const card=element('div',undefined,'capability');
      const link=element('a',entry.name);link.href=entry.url;link.target='_blank';link.rel='noopener noreferrer';
      card.append(link,element('p',`${kinds[entry.kind] || entry.kind} · ${labels[entry.status] || entry.status}`));
      if(entry.note)card.append(element('p',entry.note));
      if(entry.id==='panoradio_hf')card.append(element('code','iqscope dataset-import panoradio_hf fichier.npy --record 0 --out extrait'));
      if(entry.id==='imec_lte_wifi_dvbt'){card.append(element('code','iqscope dataset-import imec_lte_wifi_dvbt fichier.bin --out extrait'));card.append(element('p','Deux interprétations d’endianness, sans choix automatique ni validation du format réel.','hint'));}
      if(entry.id==='vksdr'){
        for(const recording of vksdr.entries){
          const row=element('div',undefined,'recording');
          row.append(element('strong',recording.source_label));
          row.append(element('p',`${recording.reference_sample_rate_hz/1000} kéch/s vérifiés · WAV IQ PCM16 · centre RF non fourni par les en-têtes vérifiés`,'hint'));
          const button=element('button','Analyser un extrait · 2 Mio maximum','secondary');
          button.setAttribute('aria-label',`Analyser l’extrait ${recording.source_label}`);
          button.onclick=()=>runVksdr(recording.id,recording.source_label);row.append(button);card.append(row);
        }
      }
      $('dataset-list').append(card);
    }
    $('dataset-dialog').showModal();
  }catch(error){status(error.message,'error');}
};
$('close-datasets').onclick=()=>$('dataset-dialog').close();


async function runVksdr(identifier,label){
  if(busy)return;
  $('dataset-dialog').close();await switchTab(false);
  $('input-kind').value='iq';updateFileInput();setBusy(true);
  status('Téléchargement du préfixe VKSDR (2 Mio maximum), puis analyse…','busy');
  try{
    const job=await api(`/api/recordings/vksdr/${encodeURIComponent(identifier)}/analyze`,{});
    await followJob(job);
    $('source-badge').textContent=`VKSDR · ${label} · extrait`;
    status('Analyse terminée. Extrait IQ et provenance disponibles. Le protocole annoncé reste à valider.','success');
  }catch(error){status(error.message,'error');}
  finally{setBusy(false);}
}

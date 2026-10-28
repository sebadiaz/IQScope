'use strict';
const $ = id => document.getElementById(id);
let audioPlot = false;
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
  for (const id of ['analyze','demo','tab-file','tab-live','input-kind']) $(id).disabled = value;
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
  const ax25Trials=(report.wideband_trials || []).filter(t=>(t.decoder==='ax25_ui' || t.decoder==='afsk1200_ax25'));
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
  if(!signals.length) list.append(element('div',audioPlot?'Audio importé : lecture et essais Morse/RTTY/AX.25 ci-dessous. Les émissions RF ne sont pas recherchées dans ce mode.':'Aucune bande stationnaire détectée. Les paquets sont recherchés séparément.','empty-results'));
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
  if(audioPlot){
    frameList.append(element('h3','Audio de récepteur · Morse, RTTY et AX.25'));
    frameList.append(element('p','Fréquences audio uniquement. Morse/RTTY : textes candidats sans CRC. AX.25 : structure et CRC vérifiés.','hint'));
    frameList.append(element('p',`Début de l’enregistrement : ${report.analyzed_seconds.toFixed(2)} s analysées (maximum demandé ${report.requested_seconds} s).`,'hint'));
    if(report.frame_artifact){const link=element('a','Télécharger les trames AX.25 validées');link.href=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.frame_artifact)}`;link.download=report.frame_artifact;frameList.append(link);}
    if(report.audio_artifact){
      const player=element('audio');player.id='audio-preview';player.controls=true;player.preload='none';
      player.src=`/api/jobs/${jobId}/artifacts/${encodeURIComponent(report.audio_artifact)}`;frameList.append(player);
    }
    if(!(report.wideband_trials || []).some(t=>t.candidates?.length))frameList.append(element('p','Aucun texte Morse ou RTTY cohérent dans cet extrait.','hint'));
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
    card.append(element('p',`t=${frame.time_seconds.toFixed(6)} s · PID 0x${f.pid.toString(16).padStart(2,'0')}${frame.channel?' · '+formatFrequency(frame.channel.audio_frequency_hz ?? frame.channel.frequency_hz)+(frame.channel.audio_frequency_hz!==undefined?' audio':''):''}`));
    if(f.text!==undefined)card.append(element('pre',f.text,'ax25-text'));
    else card.append(element('code',f.payload_hex));
    card.append(element('p','CRC et structure UI vérifiés ; identité de l’émetteur et interprétation APRS non établies.','hint'));
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
    for(const candidate of trial.candidates || []){
      const card=element('div',undefined,'frame lora-candidate');const p=candidate.parameters;
      card.append(element('h3','Chirps répétés compatibles avec un préambule LoRa'));
      card.append(element('p',`SF${p.spreading_factor} · largeur ${p.bandwidth_hz/1000} kHz · ${candidate.evidence.repeated_chirps} chirps répétés`));
      if(candidate.synchronization?.status==='opposite_chirp_pair_candidate')card.append(element('p',`Paire de chirps opposés candidate vers ${candidate.synchronization.time_seconds.toFixed(6)} s ; limite de paquet et sync word non validés.`,'lora-sync-evidence'));
      if(candidate.sync_word?.status==='sync_word_candidate')card.append(element('p',`Sync word candidat : 0x${candidate.sync_word.value_hex} ; aucun réseau ni paquet authentifié.`,'lora-sync-word'));
      if(candidate.data_symbols?.status==='raw_css_symbol_candidates'){
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
      card.append(element('p',`${frame.payload_length_bytes} octets · somme d’en-tête et CRC de données vérifiés`));
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
  let uploadedId=null;
  setBusy(true);status(isDemo ? 'Génération et analyse de la démo…' : 'Import de la capture…','busy');
  try {
    let body={demo:isDemo};
    if(!isDemo) {
      const file=$('iq-file').files[0]; if(!file) throw new Error('Choisissez un fichier IQ.');
      if(file.size>128*1024*1024) throw new Error('La limite d’import est de 128 Mio.');
      let metadata=null;
      const audioInput=$('input-kind').value==='audio';
      const meta=audioInput?null:$('meta-file').files[0];
      if(meta) {if(meta.size>1024*1024) throw new Error('Métadonnées trop volumineuses.');metadata=JSON.parse(await meta.text());}
      const uploaded=await api('/api/uploads',file);uploadedId=uploaded.upload_id;
      body={upload_id:uploaded.upload_id,input_kind:audioInput?'audio':'iq',metadata,sample_rate:Number($('file-rate').value),seconds:Number($('seconds').value)};
    }
    status('Détection des émissions et essais de décodage…','busy');
    const job=await api('/api/analyses',body);await followJob(job);
    $('source-badge').textContent=isDemo?'Démo synthétique':audioPlot?'Audio · fréquences audio':'Fichier IQ';
    status(audioPlot?'Analyse terminée. Audio et résultats Morse/RTTY/AX.25 disponibles.':'Analyse terminée. Sélectionnez une émission pour écouter les candidats audio.','success');
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
      audioPlot=false;center=spectrum.center_frequency_hz;sampleRate=spectrum.sample_rate;
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

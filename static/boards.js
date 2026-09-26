/* Storyboards tab: review what Claude scripted, redo frames, leave notes, approve the video. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const H = { 'X-Studio': '1', 'Content-Type': 'application/json' };
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const usd = cr => '$' + (cr * 0.005).toFixed(2);
  const B = { list: [], board: null, open: localStorage.getItem('studio.board'), timer: null };
  const FRAME_COST = { '1K': 8, '2K': 12, '4K': 18 };

  function toast(msg, bad) {
    const t = $('#toast'); t.textContent = msg; t.className = 'toast on' + (bad ? ' bad' : '');
    clearTimeout(t._h); t._h = setTimeout(() => t.className = 'toast', bad ? 6000 : 2600);
  }
  async function api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: H, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) throw new Error(j.error || 'HTTP ' + r.status);
    return j;
  }
  const media = f => `/boards/${B.board.id}/${encodeURIComponent(f)}`;

  /* ---------------------------------------------------------- view switch */
  document.querySelectorAll('[data-view]').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.view)));
  function show(v) {
    document.querySelectorAll('[data-view]').forEach(b => b.toggleAttribute('aria-current', b.dataset.view === v));
    document.querySelectorAll('[data-view]').forEach(b => b.dataset.view === v ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
    $('.app').hidden = v !== 'gen';
    $('#boardsView').hidden = v !== 'boards';
    localStorage.setItem('studio.view', v);
    if (v === 'boards') loadList();
  }

  /* ---------------------------------------------------------- list */
  async function loadList() {
    try { B.list = await api('/api/boards'); } catch (e) { return toast(e.message, true); }
    const el = $('#boardList');
    el.innerHTML = B.list.length ? B.list.map(b => `
      <button type="button" class="bl-item" data-bopen="${b.id}" aria-current="${b.id === B.open}">
        <span class="bl-th">${b.cover ? `<img src="/boards/${b.id}/${encodeURIComponent(b.cover)}" alt="">` : ''}</span>
        <span><span class="bl-title">${esc(b.title)}</span>
        <span class="bl-meta">${statusWord(b.status)} · ${b.scenes} scenes</span></span></button>`).join('')
      : '<p class="rail-help">Nothing here yet.</p>';
    if (B.open && B.list.some(b => b.id === B.open)) openBoard(B.open);
    else if (B.list[0]) openBoard(B.list[0].id);
  }
  const statusWord = s => ({ draft: 'Waiting for your review', rendering: 'Making clips', assembling: 'Cutting the video',
    done: 'Video ready', error: 'Needs attention', 'clips-failed': 'Some clips failed' }[s] || s);

  async function openBoard(id) {
    B.open = id; localStorage.setItem('studio.board', id);
    document.querySelectorAll('.bl-item').forEach(b => b.setAttribute('aria-current', b.dataset.bopen === id));
    await refresh(true);
  }
  async function refresh(full) {
    if (!B.open) return;
    try { B.board = await api('/api/boards/' + B.open); } catch (e) { return toast(e.message, true); }
    if (full) render(); else patch();
    clearTimeout(B.timer);
    if (busy()) B.timer = setTimeout(() => refresh(false), 5000);
  }
  const busy = () => { const b = B.board; return b && (['rendering', 'assembling'].includes(b.status) ||
    b.scenes.some(s => s.frameStatus === 'running' || s.clipStatus === 'running') || b.song?.status === 'running'); };

  /* ---------------------------------------------------------- render */
  function sceneMedia(s) {
    const st = s.clipStatus === 'running' ? 'Making clip' : s.frameStatus === 'running' ? 'Drawing frame' : '';
    const err = s.clipStatus === 'failed' ? s.clipError : s.frameStatus === 'failed' ? s.frameError : '';
    let inner = '';
    if (s.clip && s.clipStatus !== 'running') inner = `<video src="${media(s.clip)}" poster="${s.frame ? media(s.frame) : ''}" muted loop playsinline preload="metadata"></video><span class="sc-badge">clip</span>`;
    else if (s.frame) inner = `<img src="${media(s.frame)}" alt="Scene ${s.n} frame">`;
    else inner = `<div class="sc-none">No frame yet</div>`;
    if (st) inner += `<div class="sc-busy"><span class="dot"></span>${st}</div>`;
    if (err) inner += `<div class="sc-err">${esc(err)}</div>`;
    return inner;
  }
  function versions(s, key) {
    const v = s[key + 'Versions'] || [];
    if (v.length < 2) return '';
    return `<div class="sc-vers" role="group" aria-label="${key} versions">${key === 'frame' ? 'Frame' : 'Clip'} take ${v.map((f, i) =>
      `<button type="button" data-bpick="${s.id}" data-bkey="${key}" data-bfile="${esc(f)}" aria-pressed="${s[key] === f}">${i + 1}</button>`).join('')}</div>`;
  }
  function clipLine(s) {
    const b = B.board;
    if (s.still) return 'Still image, no clip';
    const m = s.clipModel || b.video?.model || 'kling3';
    if (m === 'veo3') return 'Veo 3 Fast · 8s clip with sound · 60 credits';
    const secs = Math.min(15, Math.max(3, Math.ceil(s.end - s.start)));
    const r = s.sound ? [20, 27] : [14, 18];
    return `Kling 3.0 · ${secs}s clip${s.sound ? ' with sound' : ''} · ${secs * r[0]} credits std / ${secs * r[1]} pro`;
  }
  function card(s) {
    const d = (s.end - s.start).toFixed(1);
    const fc = FRAME_COST[B.board.frameResolution || '1K'];
    return `<article class="sc" id="sc-${s.id}" data-sid="${s.id}">
      <div class="sc-media">${sceneMedia(s)}</div>
      <div class="sc-body">
        <div class="sc-head"><h3>Scene ${s.n}</h3><span>${s.start.toFixed(1)}–${s.end.toFixed(1)}s · ${d}s</span></div>
        <textarea class="ed ed-line" data-bf="line" rows="1" aria-label="Line">${esc(s.line || '')}</textarea>
        <label class="sc-lbl" for="pic-${s.id}">Picture</label>
        <textarea class="ed" id="pic-${s.id}" data-bf="picture" rows="3">${esc(s.picture || '')}</textarea>
        ${s.still ? '' : `<label class="sc-lbl" for="mot-${s.id}">Motion</label>
        <textarea class="ed" id="mot-${s.id}" data-bf="motion" rows="2">${esc(s.motion || '')}</textarea>`}
        <p class="sc-clip">${clipLine(s)}</p>
        ${(s.tags || []).length ? `<div class="sc-tags">${s.tags.map(t => `<span>${esc(t)}</span>`).join('')}</div>` : ''}
        ${versions(s, 'frame')}${versions(s, 'clip')}
        <label class="sc-lbl" for="note-${s.id}">Note for Claude</label>
        <textarea class="ed ed-note" id="note-${s.id}" data-bf="note" rows="1" placeholder="e.g. make her look more annoyed">${esc(s.note || '')}</textarea>
        <div class="sc-acts">
          <button type="button" class="ghost small" data-bframe="${s.id}" ${s.frameStatus === 'running' ? 'disabled' : ''}>${s.frame ? 'Redo frame' : 'Draw frame'} · ${fc} credits</button>
          ${s.clip || s.clipStatus === 'failed' ? `<button type="button" class="ghost small" data-bclip="${s.id}" ${s.clipStatus === 'running' ? 'disabled' : ''}>Redo clip</button>` : ''}
        </div>
      </div></article>`;
  }
  function songBlock(b) {
    const sg = b.song;
    if (!sg && !b.audio) return '';
    if (!sg) return `<div class="song"><audio controls src="${media(b.audio.file)}"></audio></div>`;
    const takes = sg.takes || [];
    return `<div class="song">
      ${takes.length ? takes.map((t, i) => `<div class="take ${sg.pick === t.file ? 'on' : ''}">
          <audio controls preload="metadata" src="${media(t.file)}"></audio>
          <button type="button" class="ghost small" data-bsong="${esc(t.file)}" aria-pressed="${sg.pick === t.file}">${sg.pick === t.file ? 'Using take ' + (i + 1) : 'Use take ' + (i + 1)}</button></div>`).join('')
        : `<p class="song-none">${sg.status === 'running' ? 'Writing the song…' : 'No song yet.'}</p>`}
      <details class="lyrics"><summary>Lyrics and style</summary><p class="song-style">${esc(sg.style || '')}</p><pre>${esc(sg.lyrics || '')}</pre></details>
      ${sg.status !== 'running' ? `<button type="button" class="ghost small" data-bsongmake="1">${takes.length ? 'Make 2 more takes' : 'Make the song'} · 12 credits</button>` : ''}
    </div>`;
  }
  function costTable(b) {
    const fc = FRAME_COST[b.frameResolution || '1K'];
    const frames = b.scenes.filter(s => !s.still || true).length;
    const mode = b.video?.mode || 'std';
    const row = (item, how, cost, hi) => `<tr class="${hi ? 'hi' : ''}"><td>${item}</td><td>${how}</td><td>${cost}</td></tr>`;
    return `<table class="cost"><thead><tr><th>Item</th><th>How</th><th>Cost</th></tr></thead><tbody>
      ${row('Scene frames', `${frames} images, Nano Banana 2 at ${b.frameResolution || '1K'} (${fc} credits each)`, `${fmt(b.frameCredits || 0)} credits spent · ${usd(b.frameCredits || 0)}`)}
      ${b.song ? row('Song', 'Suno V5, 2 takes per run', `12 credits · ${usd(12)}`) : ''}
      ${row('Video, Standard 720p', 'Kling 3.0 std, each clip trimmed to its scene, upscaled to 1080×1920 when cut', `${fmt(b._costs.std)} credits · ${usd(b._costs.std)}`, mode === 'std')}
      ${row('Video, Pro 1080p', 'Kling 3.0 pro, same clip lengths', `${fmt(b._costs.pro)} credits · ${usd(b._costs.pro)}`, mode === 'pro')}
      ${row('Captions and edit', b._ffmpeg ? 'Cut, captions and song mixed on this laptop' : 'ffmpeg missing on this laptop', '$0')}
      </tbody></table>`;
  }
  function finalBlock(b) {
    if (b.status === 'done' && b.final) return `<section class="final"><h2>Final cut</h2>
      <div class="final-row"><video src="${media(b.final)}?v=${b.updated}" controls playsinline></video>
      <div><p>Saved to Downloads\\somnei-studio\\${esc(b.finalDownload || '')}</p>
      <a class="ghost" href="${media(b.final)}" download="${esc(b.finalDownload || 'final.mp4')}">Download</a>
      <button type="button" class="ghost" data-bassemble="1">Recut (free)</button></div></div></section>`;
    if (b.status === 'error') return `<section class="final err"><h2>Something went wrong</h2><p>${esc(b.error || '')}</p>
      <button type="button" class="ghost" data-bassemble="1">Try cutting again (free)</button></section>`;
    return '';
  }
  function actionBar(b) {
    const mode = b.video?.mode || 'std';
    const cost = b._costs[mode];
    const noFrame = b.scenes.filter(s => !s.frame).length;
    const running = b.status === 'rendering' || b.status === 'assembling';
    const remaining = b.scenes.filter(s => !s.still && s.clipStatus !== 'done').reduce((a, s) => a + clipCostLocal(s, mode), 0);
    let label, dis = false, note;
    if (running) { label = statusWord(b.status); dis = true;
      const done = b.scenes.filter(s => s.clipStatus === 'done').length, live = b.scenes.filter(s => !s.still).length;
      note = b.status === 'rendering' ? `${done} of ${live} clips done. Takes 2 to 6 minutes per clip, they run in parallel.` : 'Stitching clips, song and captions.'; }
    else if (noFrame) { label = 'Make the video'; dis = true; note = `${noFrame} scene${noFrame > 1 ? 's' : ''} still need a frame.`; }
    else if (b.status === 'done' || b.scenes.every(s => s.still || s.clipStatus === 'done')) {
      label = 'Recut the video (free)'; note = 'All clips are made. Redo single clips on their cards, then recut.'; }
    else { label = `Make the video · ${fmt(remaining)} credits`; note = `About ${usd(remaining)}. This approves the storyboard and starts every clip.`; }
    return `<div class="bbar">
      <div class="seg" role="group" aria-label="Video quality">
        <button type="button" data-bmode="std" aria-pressed="${mode === 'std'}">Standard 720p</button>
        <button type="button" data-bmode="pro" aria-pressed="${mode === 'pro'}">Pro 1080p</button></div>
      <p class="bbar-note">${note}</p>
      <button type="button" class="go" id="bRender" ${dis ? 'disabled' : ''}>${label}</button></div>`;
  }
  function clipCostLocal(s, mode) {
    if (s.still) return 0;
    const m = s.clipModel || B.board.video?.model || 'kling3';
    if (m === 'veo3') return 60;
    const secs = Math.min(15, Math.max(3, Math.ceil(s.end - s.start)));
    return secs * (s.sound ? { std: 20, pro: 27 } : { std: 14, pro: 18 })[mode];
  }
  function render() {
    const b = B.board, main = $('#boardMain');
    const total = (b.scenes.at(-1).end - b.scenes[0].start).toFixed(1);
    main.innerHTML = `
      <header class="bhead">
        <h1>${esc(b.title)}</h1>
        <p class="bsub">${esc(b.subtitle || '')}</p>
        <p class="bmeta">${b.scenes.length} scenes · ${total}s · ${esc(b.aspect)}${b.hook ? ` · Hook: ${esc(b.hook)}` : ''}</p>
        ${b.product ? `<p class="bmeta">Product: ${esc(b.product)}</p>` : ''}
      </header>
      <div id="bFinal">${finalBlock(b)}</div>
      ${songBlock(b)}
      ${b.refs?.length ? `<div class="refs"><h2>References used in every frame</h2><div class="ref-row">${b.refs.map(r =>
        `<figure><img src="${media(r.file)}" alt=""><figcaption>${esc(r.label)}</figcaption></figure>`).join('')}</div></div>` : ''}
      <h2 class="scenes-h">Scenes</h2>
      <div class="scenes" id="bScenes">${b.scenes.map(card).join('')}</div>
      <label class="sc-lbl" for="bNote">Notes for Claude on the whole storyboard</label>
      <textarea class="ed ed-note board-note" id="bNote" data-bboard="note" rows="2" placeholder="e.g. hook is too slow, swap scenes 3 and 4">${esc(b.note || '')}</textarea>
      <h2 class="scenes-h">Cost</h2>
      <div id="bCost">${costTable(b)}</div>
      <div id="bBar">${actionBar(b)}</div>`;
    main.querySelectorAll('textarea.ed').forEach(autosize);
    hoverPlay();
  }
  function patch() {  // refresh live parts without clobbering text being typed
    const b = B.board;
    for (const s of b.scenes) {
      const c = $('#sc-' + s.id); if (!c) return render();
      const m = c.querySelector('.sc-media'); const html = sceneMedia(s);
      if (m.dataset.sig !== html) { m.innerHTML = html; m.dataset.sig = html; }
      const acts = c.querySelector('.sc-acts'); const tmp = document.createElement('div'); tmp.innerHTML = card(s);
      acts.replaceWith(tmp.querySelector('.sc-acts'));
      const ov = c.querySelectorAll('.sc-vers'); ov.forEach(x => x.remove());
      const nv = tmp.querySelectorAll('.sc-vers'); const anchor = c.querySelector('.ed-note').previousElementSibling;
      nv.forEach(x => anchor.before(x));
    }
    $('#bFinal').innerHTML = finalBlock(b);
    $('#bCost').innerHTML = costTable(b);
    $('#bBar').innerHTML = actionBar(b);
    const song = $('.song'); if (song && !song.contains(document.activeElement)) { const t = document.createElement('div'); t.innerHTML = songBlock(b); song.replaceWith(t.firstElementChild); }
    hoverPlay();
  }
  function autosize(t) { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }
  function hoverPlay() {
    document.querySelectorAll('.sc-media video').forEach(v => {
      if (v._hp) return; v._hp = 1;
      v.parentElement.addEventListener('mouseenter', () => v.play().catch(() => {}));
      v.parentElement.addEventListener('mouseleave', () => { v.pause(); v.currentTime = 0; });
    });
  }

  /* ---------------------------------------------------------- actions */
  async function act(action, body, okMsg) {
    try { B.board = await api(`/api/boards/${B.board.id}/${action}`, body); if (okMsg) toast(okMsg); }
    catch (e) { toast(e.message, true); }
    await refresh(false);
  }
  document.addEventListener('input', e => { if (e.target.matches('#boardMain textarea.ed')) autosize(e.target); });
  document.addEventListener('change', async e => {
    const t = e.target;
    if (!t.matches('#boardMain textarea.ed')) return;
    const sid = t.closest('[data-sid]')?.dataset.sid;
    const field = t.dataset.bf || t.dataset.bboard;
    try { await api(`/api/boards/${B.board.id}/update`, { scene: sid, fields: { [field]: t.value } }); toast('Saved'); }
    catch (err) { toast(err.message, true); }
  });
  document.addEventListener('click', async e => {
    const t = e.target.closest('button'); if (!t || !t.closest('#boardsView')) return;
    const d = t.dataset;
    if (d.bopen) return openBoard(d.bopen);
    if (d.bframe) { const s = B.board.scenes.find(x => x.id === d.bframe);
      const pic = $('#pic-' + s.id).value;
      if (pic !== s.picture) await api(`/api/boards/${B.board.id}/update`, { scene: s.id, fields: { picture: pic } });
      return act('frame', { scene: d.bframe }, `Drawing scene ${s.n}. About a minute.`); }
    if (d.bclip) { const s = B.board.scenes.find(x => x.id === d.bclip); const mode = B.board.video?.mode || 'std';
      const mot = $('#mot-' + s.id)?.value;
      if (mot != null && mot !== s.motion) await api(`/api/boards/${B.board.id}/update`, { scene: s.id, fields: { motion: mot } });
      return act('clip', { scene: d.bclip, mode }, `Remaking scene ${s.n}'s clip · ${clipCostLocal(s, mode)} credits.`); }
    if (d.bpick) return act('pick', { scene: d.bpick, key: d.bkey, file: d.bfile });
    if (d.bmode) return act('update', { fields: { mode: d.bmode } });
    if (d.bsong) return act('update', { fields: { songPick: d.bsong } }, 'Song take chosen');
    if (d.bsongmake) return act('song', {}, 'Writing the song. Takes 1 to 3 minutes.');
    if (d.bassemble) return act('assemble', {}, 'Cutting the video.');
    if (t.id === 'bRender') {
      const b = B.board;
      if (b.scenes.every(s => s.still || s.clipStatus === 'done')) return act('assemble', {}, 'Cutting the video.');
      return act('render', { mode: b.video?.mode || 'std' }, 'Approved. Making every clip now.');
    }
  });

  if (localStorage.getItem('studio.view') === 'boards') show('boards');
})();

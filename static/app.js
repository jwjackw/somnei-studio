/* somnei studio front end. No build step, no framework. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const H = { 'X-Studio': '1' };
  const S = {
    catalog: null, kind: 'video', model: null,
    values: JSON.parse(localStorage.getItem('studio.values') || '{}'),   // per model key
    assets: [], jobs: [], credits: null,
    armed: null,          // media param name waiting for a pick from the library
    current: null,        // job id on stage
    fileIdx: 0,
  };
  const save = () => localStorage.setItem('studio.values', JSON.stringify(S.values));
  const vals = () => (S.values[S.model.key] ||= {});

  function toast(msg, bad = false) {
    const t = $('#toast'); t.textContent = msg; t.className = 'toast on' + (bad ? ' bad' : '');
    clearTimeout(t._h); t._h = setTimeout(() => t.className = 'toast', bad ? 6000 : 2600);
  }
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 });

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }

  /* ------------------------------------------------------------ cost */
  function assetById(id) { return S.assets.find(a => a.id === id); }
  function cost(model, v) {
    const c = model.cost;
    if (!c) return null;
    const pv = p => {
      if (p.startsWith('@has:')) { const x = v[p.slice(5)]; return String(Array.isArray(x) ? x.length > 0 : !!x); }
      const def = model.params.find(q => q.name === p);
      const raw = v[p] ?? def?.default;
      return String(raw);
    };
    let rate = c.rate;
    if (c.by) rate = c.rates[c.by.map(pv).join('|')];
    if (rate == null) return null;
    let secs = 1;
    if (c.type === 'per_1k_chars') {
      const n = String(v[c.field] || '').length;
      return { credits: Math.max(0.1, Math.round(n / 1000 * rate * 10) / 10), approx: false, rate, secs: 1, perSecond: false };
    }
    if (c.type === 'per_second') {
      if (c.sec.startsWith('@duration:')) {
        const ids = [].concat(v[c.sec.slice(10)] || []);
        const a = ids.length && assetById(ids[0]);
        if (!a || !a.duration) return { need: 'length of the ' + (model.params.find(p => p.name === c.sec.slice(10))?.label || 'clip').toLowerCase() };
        secs = Math.ceil(a.duration);
      } else {
        secs = Number(v[c.sec] ?? model.params.find(p => p.name === c.sec)?.default ?? 0);
      }
    }
    return { credits: Math.round(rate * secs * 10) / 10, approx: !!c.approx, rate, secs, perSecond: c.type === 'per_second' };
  }
  function costLabel(m) {
    const c = m.cost; if (!c) return 'price not listed';
    const rates = c.rates ? Object.values(c.rates) : [c.rate];
    const lo = Math.min(...rates);
    if (c.type === 'per_1k_chars') return `${fmt(lo)} per 1k chars`;
    return c.type === 'per_second' ? `from ${fmt(lo)}/s` : (rates.length > 1 ? `from ${fmt(lo)}` : fmt(lo));
  }

  /* ------------------------------------------------------------ settings column */
  function renderKinds() {
    $('#kinds').innerHTML = S.catalog.kinds.map(k =>
      `<button type="button" role="tab" data-k="${k.key}" aria-selected="${k.key === S.kind}">${esc(k.label)}</button>`).join('');
  }
  function renderModelList() {
    const ms = S.catalog.models.filter(m => m.kind === S.kind);
    $('#modelList').innerHTML = ms.map(m =>
      `<button type="button" data-m="${m.key}" aria-pressed="${m.key === S.model?.key}">
        <span class="m-name">${esc(m.name)}</span><span class="m-cost">${esc(costLabel(m))}</span></button>`).join('');
  }
  function selectModel(key) {
    S.model = S.catalog.models.find(m => m.key === key);
    S.kind = S.model.kind; S.armed = null;
    localStorage.setItem('studio.model', key);
    const v = vals();
    for (const p of S.model.params) if (v[p.name] === undefined && p.default !== undefined) v[p.name] = p.default;
    save();
    renderKinds(); renderModelList(); renderModelHead(); renderParams(); renderPrompt(); renderSlots(); renderLibrary(); updateGo();
  }
  function renderModelHead() {
    $('#modelHead').innerHTML = `<h3>${esc(S.model.name)}</h3><p>${esc(S.model.blurb)}</p>`;
  }

  function fieldHTML(p, v) {
    const val = v[p.name] ?? p.default ?? '';
    const desc = p.desc ? `<p class="desc">${esc(p.desc)}</p>` : '';
    const id = 'f_' + p.name;
    if (p.type === 'boolean') {
      return `<div class="field"><label class="switch"><input type="checkbox" id="${id}" data-p="${p.name}" ${val === true || val === 'true' ? 'checked' : ''}> ${esc(p.label)}</label>${desc}</div>`;
    }
    if (p.control === 'seg' && p.enum) {
      const labels = p.enumLabels || p.enum;
      return `<div class="field"><span class="lbl">${esc(p.label)}</span><div class="seg" role="group" aria-label="${esc(p.label)}">${
        p.enum.map((e, i) => `<button type="button" data-p="${p.name}" data-v="${esc(e)}" aria-pressed="${String(val) === String(e)}">${esc(labels[i])}</button>`).join('')
      }</div>${desc}</div>`;
    }
    if (p.enum) {
      return `<div class="field"><label for="${id}">${esc(p.label)}</label><select id="${id}" data-p="${p.name}">${
        p.enum.map((e, i) => `<option value="${esc(e)}" ${String(val) === String(e) ? 'selected' : ''}>${esc((p.enumLabels || p.enum)[i])}</option>`).join('')}</select>${desc}</div>`;
    }
    if (p.control === 'slider') {
      return `<div class="field"><span class="lbl"><label for="${id}">${esc(p.label)}</label><output id="${id}_o">${esc(val)}${p.unit || ''}</output></span>
        <input type="range" id="${id}" data-p="${p.name}" min="${p.min}" max="${p.max}" step="${p.step || 1}" value="${esc(val)}">${desc}</div>`;
    }
    const t = (p.type === 'integer' || p.type === 'number') ? 'number' : 'text';
    const mm = (p.min != null ? ` min="${p.min}"` : '') + (p.max != null && t === 'number' ? ` max="${p.max}"` : '');
    return `<div class="field"><label for="${id}">${esc(p.label)}</label><input type="${t}" id="${id}" data-p="${p.name}" value="${esc(val)}"${mm} placeholder="${t === 'number' ? 'random' : ''}">${desc}</div>`;
  }
  function renderParams() {
    const v = vals();
    const ps = S.model.params.filter(p => !p.media && p.control !== 'prompt' && p.control !== 'negative');
    const main = ps.filter(p => !p.advanced), adv = ps.filter(p => p.advanced);
    $('#params').innerHTML = main.map(p => fieldHTML(p, v)).join('') +
      (adv.length ? `<details class="adv"><summary>More settings (${adv.length})</summary><div class="params-inner">${adv.map(p => fieldHTML(p, v)).join('')}</div></details>` : '');
  }
  function renderPrompt() {
    const v = vals();
    const pr = S.model.params.find(p => p.control === 'prompt');
    const neg = S.model.params.find(p => p.control === 'negative');
    let h = '';
    if (pr) {
      const txt = v[pr.name] || '';
      h += `<div class="prompt-box"><label class="plabel" for="prompt">${esc(pr.label)}${pr.required ? '' : ' (optional)'}</label>
        <textarea id="prompt" data-p="${pr.name}" placeholder="${esc(pr.desc || 'Describe the video')}">${esc(txt)}</textarea>
        <span class="count" id="pcount">${txt.length}${pr.max ? ' / ' + pr.max : ''}</span></div>`;
    }
    if (neg) h += `<div class="prompt-box neg"><label class="plabel" for="neg">${esc(neg.label)} (optional)</label>
        <textarea id="neg" data-p="${neg.name}" placeholder="Things you don't want to see, e.g. blurry, extra fingers, text">${esc(v[neg.name] || '')}</textarea></div>`;
    $('#promptSlot').innerHTML = h;
  }

  /* ------------------------------------------------------------ media slots */
  const mediaParams = () => S.model.params.filter(p => p.media);
  function chip(a) {
    if (!a) return '<div class="chip" title="missing file"></div>';
    const inner = a.kind === 'video' ? `<video src="${a.local}#t=0.5" muted preload="metadata"></video>`
      : a.kind === 'audio' ? `<div style="color:#fff;font-size:10px;display:grid;place-items:center;height:100%">audio<br>${a.duration ? Math.round(a.duration) + 's' : ''}</div>`
      : `<img src="${a.local}" alt="">`;
    return inner;
  }
  function renderSlots() {
    const v = vals();
    $('#mediaSlots').innerHTML = mediaParams().map(p => {
      const ids = [].concat(v[p.name] || []);
      const items = ids.map((id, i) => `<div class="chip">${chip(assetById(id))}<button type="button" data-rm="${p.name}" data-i="${i}" aria-label="Remove">×</button></div>`).join('');
      const full = p.multiple ? ids.length >= (p.maxItems || 99) : ids.length >= 1;
      const cap = p.multiple ? ` ${ids.length}/${p.maxItems || '∞'}` : '';
      return `<div class="slot ${p.required ? 'req' : ''} ${S.armed === p.name ? 'armed' : ''}" data-slot="${p.name}" data-media="${p.media}" tabindex="0" role="button"
          aria-label="${esc(p.label)}: pick ${p.media}" title="${esc(p.desc || '')}">
        <span class="slot-name">${esc(p.label)}<span style="color:var(--muted);font-weight:500">${cap}</span></span>
        <div class="slot-items">${items || `<span class="ph">${S.armed === p.name ? `Now click a ${p.media} below` : `Click, then pick a ${p.media}`}</span>`}</div>
      </div>`;
    }).join('');
    if (!mediaParams().length) $('#mediaSlots').innerHTML = '';
  }
  function assign(pname, assetId) {
    const p = S.model.params.find(x => x.name === pname); const a = assetById(assetId);
    if (!p || !a) return;
    if (a.kind !== p.media) return toast(`${p.label} needs a ${p.media}, that's a ${a.kind}.`, true);
    const v = vals();
    if (p.multiple) {
      const arr = [].concat(v[pname] || []);
      if (arr.length >= (p.maxItems || 99)) return toast(`${p.label} holds up to ${p.maxItems}.`, true);
      arr.push(assetId); v[pname] = arr;
      if (arr.length >= (p.maxItems || 99)) S.armed = null;
    } else { v[pname] = assetId; S.armed = null; }
    save(); renderSlots(); renderLibrary(); updateGo();
  }

  /* ------------------------------------------------------------ library */
  function renderLibrary() {
    const lib = $('#library');
    const want = S.armed ? S.model.params.find(p => p.name === S.armed)?.media : null;
    if (!S.assets.length) { lib.className = 'lib-grid empty'; lib.textContent = 'No media yet. Drop product shots, UGC clips or voice tracks anywhere on this page.'; return; }
    lib.className = 'lib-grid';
    lib.innerHTML = S.assets.map(a => `<div class="asset ${want && a.kind === want ? 'pickable' : ''} ${a.pending ? 'uploading' : ''}" draggable="${!a.pending}" data-a="${a.id}" title="${esc(a.name)}">
        ${chip(a)}<span class="tag">${a.kind}${a.duration ? ' ' + Math.round(a.duration) + 's' : ''}</span>
        ${a.pending ? '' : `<button type="button" class="del" data-del="${a.id}" aria-label="Remove from library">×</button>`}</div>`).join('');
    $('#libHint').textContent = want ? `Click a ${want} to put it in ${S.model.params.find(p => p.name === S.armed).label}` : 'Drop images, videos or audio here, or';
  }
  function mediaDuration(file) {
    if (!/^(video|audio)\//.test(file.type)) return Promise.resolve(null);
    return new Promise(res => {
      const el = document.createElement(file.type.startsWith('video') ? 'video' : 'audio');
      el.preload = 'metadata'; el.onloadedmetadata = () => { res(el.duration || null); URL.revokeObjectURL(el.src); };
      el.onerror = () => res(null); el.src = URL.createObjectURL(file);
    });
  }
  async function uploadFiles(files, target) {
    for (const f of files) {
      if (!/^(image|video|audio)\//.test(f.type)) { toast(`${f.name} isn't an image, video or audio file.`, true); continue; }
      const tmp = { id: 'tmp' + Math.random(), name: f.name, kind: f.type.split('/')[0], local: URL.createObjectURL(f), pending: true };
      S.assets.unshift(tmp); renderLibrary();
      try {
        const dur = await mediaDuration(f);
        const a = await api('/api/upload', { method: 'POST', body: f,
          headers: { ...H, 'Content-Type': f.type, 'X-Filename': encodeURIComponent(f.name), 'X-Duration': dur || '' } });
        S.assets[S.assets.indexOf(tmp)] = a;
        if (target) assign(target, a.id);
      } catch (e) {
        S.assets.splice(S.assets.indexOf(tmp), 1);
        toast(`Upload failed for ${f.name}: ${e.message}`, true);
      }
      renderLibrary(); renderSlots(); updateGo();
    }
  }

  /* ------------------------------------------------------------ generate */
  function missing() {
    const v = vals();
    return S.model.params.filter(p => p.required && ([].concat(v[p.name] ?? []).filter(x => x !== '').length === 0)).map(p => p.label);
  }
  function updateGo() {
    const btn = $('#generate'), note = $('#goNote');
    const c = cost(S.model, vals());
    const miss = missing();
    note.className = 'go-note';
    if (!c) { btn.textContent = 'Generate'; note.textContent = 'kie.ai does not list a price for this model. You will see the real cost in History after it runs.'; }
    else if (c.need) { btn.textContent = 'Generate'; note.textContent = `Cost depends on the ${c.need}. Add it to see the estimate.`; }
    else {
      btn.textContent = `Generate · ${c.approx ? 'about ' : ''}${fmt(c.credits)} credits`;
      const usd = c.credits * 0.005;
      note.textContent = (c.perSecond ? `${fmt(c.rate)} credits/s × ${c.secs}s. ` : '') + `About $${usd.toFixed(2)}.` +
        (S.credits != null ? ` You have ${fmt(S.credits)} credits.` : '');
      if (S.credits != null && c.credits > S.credits) { note.className = 'go-note warn'; note.textContent += ' Not enough credits.'; }
    }
    if (miss.length) { note.className = 'go-note warn'; note.textContent = 'Still needed: ' + miss.join(', ') + '. ' + note.textContent; }
    btn.disabled = miss.length > 0 || (c && !c.need && S.credits != null && c.credits > S.credits);
  }
  async function generate() {
    const btn = $('#generate'); if (btn.disabled) return;
    const v = vals(); const params = {};
    for (const p of S.model.params) {
      let x = v[p.name];
      if (x === undefined || x === '' || x === null) continue;
      if (p.media) {
        const urls = [].concat(x).map(id => assetById(id)?.url).filter(Boolean);
        if (!urls.length) continue;
        x = p.multiple ? urls : urls[0];
      }
      params[p.name] = x;
    }
    const c = cost(S.model, v);
    const thumbs = mediaParams().flatMap(p => [].concat(v[p.name] || [])).map(id => assetById(id)?.local).filter(Boolean).slice(0, 1);
    btn.disabled = true; btn.textContent = 'Sending to kie.ai';
    try {
      const job = await api('/api/generate', { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: S.model.key, params, estCredits: c && !c.need ? c.credits : null, thumbs }) });
      S.jobs.unshift(job); S.current = job.id; renderHistory(); renderStage();
      toast(`${S.model.name} started. It keeps running if you close this tab.`);
      refreshCredits();
    } catch (e) { toast(e.message, true); }
    updateGo();
  }

  /* ------------------------------------------------------------ stage + history */
  const since = t => { const s = Math.round(Date.now() / 1000 - t); return s < 60 ? s + 's' : s < 3600 ? Math.round(s / 60) + 'm' : Math.round(s / 3600) + 'h'; };
  function ratioClass(job) {
    const r = job.params?.aspect_ratio || job.params?.aspectRatio || job.params?.ratio || '9:16';
    return { '16:9': 'r16x9', '1:1': 'r1x1', '4:5': 'r4x5', '3:2': 'r16x9', '4:3': 'r16x9', '21:9': 'r16x9' }[r] || '';
  }
  function mediaTag(f) {
    const src = '/media/' + encodeURIComponent(f.name);
    return /\.(mp4|mov|webm)$/i.test(f.name) ? `<video src="${src}" controls autoplay loop playsinline></video>` :
      /\.(mp3|wav)$/i.test(f.name) ? `<audio src="${src}" controls></audio>` : `<img src="${src}" alt="Generated result">`;
  }
  function renderStage() {
    const job = S.jobs.find(j => j.id === S.current);
    const frame = $('#frame'), actions = $('#stageActions');
    const safe = `<div class="safe" aria-hidden="true"><div class="top"><span>profile + caption bar</span></div><div class="side"></div><div class="bottom"><span>caption, CTA and buttons cover this</span></div></div>`;
    frame.className = 'frame ' + (job ? ratioClass(job) : '') + ($('#safeZones').checked ? ' show-safe' : '');
    if (!job) { $('#stageTitle').textContent = 'Nothing selected yet'; actions.innerHTML = ''; return; }
    $('#stageTitle').textContent = `${job.modelName} · ${new Date(job.created * 1000).toLocaleString()}`;
    if (job.status === 'running') {
      frame.innerHTML = `<div class="wait"><div class="pulse"></div><strong>Generating</strong><span>${since(job.created)} so far. Videos usually take 1 to 6 minutes.${job.progress ? ` ${job.progress}%` : ''}</span></div>` + safe;
      actions.innerHTML = ''; return;
    }
    if (job.status === 'failed') {
      frame.innerHTML = `<div class="err"><strong>kie.ai could not make this.</strong><br><br>${esc(job.error)}</div>`;
      actions.innerHTML = `<button class="ghost" data-act="reuse">Load these settings</button>`; return;
    }
    const files = (job.files || []).filter(f => f.name);
    S.fileIdx = Math.min(S.fileIdx, Math.max(0, files.length - 1));
    const f = files[S.fileIdx];
    frame.innerHTML = (f ? mediaTag(f) : `<div class="err">Finished, but the file did not download. ${esc((job.files || [])[0]?.remote || '')}</div>`) + safe;
    actions.innerHTML = (files.length > 1 ? `<div class="multi">${files.map((x, i) => `<button class="ghost small" data-pick="${i}" aria-pressed="${i === S.fileIdx}">${i + 1}</button>`).join('')}</div>` : '') +
      (f ? `<a class="ghost" href="/media/${encodeURIComponent(f.name)}" download>Download</a>
      <button class="ghost" data-act="asinput">Use as input</button>` : '') +
      `<button class="ghost" data-act="reuse">Load these settings</button>
      <button class="ghost" data-act="del">Remove from history</button>`;
  }
  function renderHistory() {
    const el = $('#history');
    if (!S.jobs.length) { el.innerHTML = '<p class="none">Nothing generated yet. Finished videos also save to Downloads\\somnei-studio.</p>'; return; }
    el.innerHTML = S.jobs.map(j => {
      const f = (j.files || []).find(x => x.name);
      const th = f ? (/\.(mp4|mov|webm)$/i.test(f.name) ? `<video src="/media/${encodeURIComponent(f.name)}#t=0.5" muted preload="metadata"></video>` : `<img src="/media/${encodeURIComponent(f.name)}" alt="">`)
        : j.thumbs?.[0] ? `<img src="${j.thumbs[0]}" alt="" style="opacity:.5">` : j.status === 'running' ? 'working' : '';
      const st = j.status === 'running' ? `<span class="st-running">Generating · ${since(j.created)}</span>`
        : j.status === 'failed' ? '<span class="st-failed">Failed</span>' : '<span class="st-done">Done</span>';
      const cr = j.credits != null ? `${fmt(j.credits)} credits` : j.estCredits != null ? `≈${fmt(j.estCredits)} credits` : '';
      return `<button type="button" class="job" data-j="${j.id}" aria-current="${j.id === S.current}">
        <span class="th">${th}</span>
        <span><span class="j-model">${esc(j.modelName)}</span><span class="j-prompt">${esc(j.prompt || '(no prompt)')}</span>
        <span class="j-meta">${st}${cr ? ' · ' + cr : ''}</span></span></button>`;
    }).join('');
  }
  async function refreshJobs() {
    try {
      const before = new Map(S.jobs.map(j => [j.id, j.status]));
      S.jobs = await api('/api/jobs');
      for (const j of S.jobs) if (before.get(j.id) === 'running' && j.status !== 'running') {
        toast(j.status === 'done' ? `${j.modelName} is ready.` : `${j.modelName} failed: ${j.error}`, j.status !== 'done');
        refreshCredits();
      }
      renderHistory();
      const cur = S.jobs.find(j => j.id === S.current);
      if (cur && before.get(cur.id) !== cur.status) renderStage();
      else if (cur?.status === 'running') { const w = $('#frame .wait span'); if (w) w.textContent = `${since(cur.created)} so far. Videos usually take 1 to 6 minutes.`; }
    } catch (e) { /* server restarting; try again next tick */ }
  }
  async function refreshCredits() {
    try {
      const r = await api('/api/credits'); S.credits = r.credits;
      const el = $('#credits'); el.textContent = `${fmt(r.credits)} credits`; el.classList.toggle('low', r.credits < 300);
    } catch (e) { $('#credits').textContent = 'credits unavailable'; }
    updateGo();
  }

  /* ------------------------------------------------------------ events */
  document.addEventListener('click', async e => {
    const t = e.target.closest('button, [data-slot], .asset, a');
    if (!t) return;
    if (t.dataset.k) { S.kind = t.dataset.k; const first = S.catalog.models.find(m => m.kind === S.kind); selectModel(first.key); return; }
    if (t.dataset.m) return selectModel(t.dataset.m);
    if (t.dataset.p && t.dataset.v !== undefined) {
      vals()[t.dataset.p] = t.dataset.v; save();
      t.parentElement.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b === t)); updateGo(); return;
    }
    if (t.dataset.rm) { e.stopPropagation(); const v = vals(); const p = S.model.params.find(x => x.name === t.dataset.rm);
      if (p.multiple) { v[p.name] = [].concat(v[p.name]); v[p.name].splice(+t.dataset.i, 1); } else delete v[p.name];
      save(); renderSlots(); updateGo(); return; }
    if (t.dataset.slot) { S.armed = S.armed === t.dataset.slot ? null : t.dataset.slot; renderSlots(); renderLibrary();
      if (S.armed && !S.assets.some(a => a.kind === t.dataset.media)) $('#fileInput').click(); return; }
    if (t.dataset.del) { e.stopPropagation(); await api('/api/assets/delete', { method: 'POST', headers: H, body: JSON.stringify({ id: t.dataset.del }) });
      S.assets = S.assets.filter(a => a.id !== t.dataset.del); renderLibrary(); renderSlots(); return; }
    if (t.dataset.a) { if (S.armed) assign(S.armed, t.dataset.a);
      else { const a = assetById(t.dataset.a); const slot = mediaParams().find(p => p.media === a?.kind && [].concat(vals()[p.name] || []).length < (p.multiple ? p.maxItems || 99 : 1));
        if (slot) assign(slot.name, a.id); else toast(`No free ${a?.kind} slot on ${S.model.name}. Pick a model that takes a ${a?.kind}.`, true); }
      return; }
    if (t.dataset.j) { S.current = t.dataset.j; S.fileIdx = 0; renderHistory(); renderStage(); return; }
    if (t.dataset.pick) { S.fileIdx = +t.dataset.pick; renderStage(); return; }
    const job = S.jobs.find(j => j.id === S.current);
    if (t.dataset.act === 'reuse' && job) {
      const m = S.catalog.models.find(x => x.key === job.model); if (!m) return;
      const nv = {};
      for (const p of m.params) {
        const x = job.params[p.name]; if (x === undefined) continue;
        nv[p.name] = p.media ? [].concat(x).map(u => S.assets.find(a => a.url === u)?.id).filter(Boolean) : x;
        if (p.media && !p.multiple) nv[p.name] = nv[p.name][0];
      }
      S.values[m.key] = nv; save(); selectModel(m.key); toast('Settings loaded. Tweak and generate again.'); return;
    }
    if (t.dataset.act === 'asinput' && job) {
      const f = (job.files || []).filter(x => x.name)[S.fileIdx];
      try { const a = await api('/api/assets/from-output', { method: 'POST', headers: H, body: JSON.stringify({ file: f.name, remote: f.remote }) });
        S.assets.unshift(a); renderLibrary(); toast('Added to your media. Click a slot, then click it.'); } catch (err) { toast(err.message, true); }
      return;
    }
    if (t.dataset.act === 'del' && job) {
      await api('/api/jobs/delete', { method: 'POST', headers: H, body: JSON.stringify({ id: job.id }) });
      S.jobs = S.jobs.filter(j => j.id !== job.id); S.current = S.jobs[0]?.id; renderHistory(); renderStage(); toast('Removed from history. The file stays in Downloads.'); return;
    }
    if (t.id === 'generate') return generate();
    if (t.id === 'openFolder') { api('/api/open-folder', { method: 'POST', headers: H }).catch(err => toast(err.message, true)); }
  });
  document.addEventListener('input', e => {
    const t = e.target; if (!t.dataset.p) return;
    const p = S.model.params.find(x => x.name === t.dataset.p);
    let v = t.type === 'checkbox' ? t.checked : t.value;
    if (t.type === 'range') { $('#' + t.id + '_o').textContent = v + (p.unit || ''); if (p.type === 'integer') v = +v; }
    vals()[t.dataset.p] = v; save();
    if (t.id === 'prompt') $('#pcount').textContent = t.value.length + (p.max ? ' / ' + p.max : '');
    updateGo();
  });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && document.getElementById('boardsView').hidden) generate();
    if (e.key === 'Enter' && e.target.dataset?.slot) e.target.click();
  });
  $('#safeZones').addEventListener('change', () => $('#frame').classList.toggle('show-safe', $('#safeZones').checked));
  $('#fileInput').addEventListener('change', e => { uploadFiles([...e.target.files], S.armed); e.target.value = ''; });

  // drag: files from desktop anywhere, or library items onto slots
  let depth = 0;
  document.addEventListener('dragenter', e => { if (e.dataTransfer.types.includes('Files')) { depth++; $('#dropveil').classList.add('on'); } });
  document.addEventListener('dragleave', e => { if (e.dataTransfer.types.includes('Files') && --depth <= 0) { depth = 0; $('#dropveil').classList.remove('on'); } });
  document.addEventListener('dragover', e => { e.preventDefault(); const s = e.target.closest('[data-slot]');
    document.querySelectorAll('.slot.over').forEach(x => x !== s && x.classList.remove('over')); s?.classList.add('over'); });
  document.addEventListener('dragstart', e => { const a = e.target.closest('.asset'); if (a) e.dataTransfer.setData('text/asset', a.dataset.a); });
  document.addEventListener('drop', e => {
    e.preventDefault(); depth = 0; $('#dropveil').classList.remove('on');
    const slot = e.target.closest('[data-slot]'); document.querySelectorAll('.slot.over').forEach(x => x.classList.remove('over'));
    const aid = e.dataTransfer.getData('text/asset');
    if (aid && slot) return assign(slot.dataset.slot, aid);
    if (e.dataTransfer.files.length) uploadFiles([...e.dataTransfer.files], slot?.dataset.slot);
  });

  /* ------------------------------------------------------------ boot */
  (async () => {
    try {
      [S.catalog, S.assets, S.jobs] = await Promise.all([api('/api/models'), api('/api/assets'), api('/api/jobs')]);
    } catch (e) { toast('Could not reach the studio server: ' + e.message, true); return; }
    const saved = localStorage.getItem('studio.model');
    selectModel(S.catalog.models.some(m => m.key === saved) ? saved : S.catalog.models[0].key);
    S.current = S.jobs[0]?.id; renderHistory(); renderStage();
    refreshCredits();
    setInterval(refreshJobs, 5000);
    setInterval(refreshCredits, 120000);
  })();
})();

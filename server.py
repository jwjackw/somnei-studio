"""Somnei Studio: a local video/image ad generator on top of kie.ai.

Run:  python server.py        then open http://localhost:4950
The kie.ai key never reaches the browser. It is read from
~/somnei-shopify/.kie-token (fallback: KIE_AI_API_KEY env var).

Every generation spends kie.ai credits. The browser shows the estimated
cost on the Generate button; nothing is spent until you click it.
"""
import json, os, sys, time, uuid, base64, threading, mimetypes, re, urllib.request, urllib.error, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, 'static')
DATA = os.path.join(ROOT, 'data')
UPLOADS = os.path.join(ROOT, 'uploads')
OUT = os.path.join(os.path.expanduser('~'), 'Downloads', 'somnei-studio')
JOBS_FILE = os.path.join(DATA, 'jobs.json')
ASSETS_FILE = os.path.join(DATA, 'assets.json')
MODELS_FILE = os.path.join(ROOT, 'models.json')
PORT = int(os.environ.get('STUDIO_PORT', '4950'))
VERSION = '0.3.0'
for d in (DATA, UPLOADS, OUT):
    os.makedirs(d, exist_ok=True)

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0  # hide ffmpeg console windows on Windows
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'
API = 'https://api.kie.ai'
UPLOAD_API = 'https://kieai.redpandaai.co'


def open_folder(path):
    import subprocess
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])


def kie_key():
    p = os.path.join(os.path.expanduser('~'), 'somnei-shopify', '.kie-token')
    if os.path.exists(p):
        return open(p).read().strip()
    return os.environ.get('KIE_AI_API_KEY', '')


def http(method, url, body=None, headers=None, timeout=120, raw=False):
    h = {'User-Agent': UA, 'Authorization': 'Bearer ' + kie_key()}
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            return b if raw else json.loads(b.decode() or '{}')
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors='replace')[:600]
        raise RuntimeError(f'kie.ai HTTP {e.code}: {txt}')


# ---------------------------------------------------------------- storage
LOCK = threading.Lock()


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def models():
    return load(MODELS_FILE, {'models': []})


def model_by_id(mid):
    for m in models()['models']:
        if m['key'] == mid:
            return m
    return None


# ---------------------------------------------------------------- uploads
def upload_to_kie(local_path, filename, mime):
    """Stream the file to kie.ai's temporary file host, return a public URL."""
    boundary = '----studio' + uuid.uuid4().hex
    with open(local_path, 'rb') as f:
        content = f.read()
    parts = []
    for k, v in (('uploadPath', 'somnei-studio'), ('fileName', filename)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n'.encode() + content + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    body = b''.join(parts)
    r = http('POST', UPLOAD_API + '/api/file-stream-upload', body,
             {'Content-Type': 'multipart/form-data; boundary=' + boundary}, timeout=600)
    d = r.get('data') or {}
    url = d.get('downloadUrl') or d.get('fileUrl') or d.get('url')
    if not url:
        raise RuntimeError('upload failed: ' + json.dumps(r)[:300])
    return url


# ---------------------------------------------------------------- task families
def build_request(model, params):
    """Return (path, body) for a create call, per the model's create style."""
    c = model['create']
    clean = {}
    for p in model['params']:
        n = p['name']
        if n not in params:
            continue
        v = params[n]
        if v in ('', None, []):
            continue
        t = p.get('type')
        if t == 'number':
            v = float(v)
            if v.is_integer():
                v = int(v)
        elif t == 'integer':
            v = int(float(v))
        elif t == 'boolean':
            v = bool(v) if not isinstance(v, str) else v.lower() == 'true'
        elif t == 'string' and not isinstance(v, (str, list)):
            v = str(v)
        if p.get('multiple') and not isinstance(v, list):
            v = [v]
        if not p.get('multiple') and isinstance(v, list):
            v = v[0]
        clean[n] = v
    for k, v in (c.get('fixed') or {}).items():
        clean.setdefault(k, v)
    mid = c.get('model')
    rule = c.get('modelIfEmpty')
    if rule and rule['param'] not in clean:
        mid = rule['model']
    rule = c.get('modelIfSet')
    if rule and rule['param'] in clean:
        mid = rule['model']
    rule = c.get('modelByParam')
    if rule:
        mid = rule['map'].get(str(params.get(rule['param'])), mid)
    rule = c.get('dropIfSet')
    if rule and rule['param'] in clean:
        for k in rule['drop']:
            clean.pop(k, None)
    for p in model['params']:
        if p.get('local'):
            clean.pop(p['name'], None)
    if c.get('bodyStyle') == 'jobs_input':
        body = {'model': mid, 'input': clean}
    else:
        body = dict(clean)
        if mid and 'model' not in body:
            body['model'] = mid
    return c['path'], body


def estimate(model, params, assets=None):
    """Credit estimate for one run. Mirrors cost() in static/app.js.
    Returns {'credits': float, 'approx': bool} or {'credits': None, 'reason': str}."""
    c = model.get('cost')
    if not c:
        return {'credits': None, 'reason': 'kie.ai does not list a price for this model'}
    defaults = {p['name']: p.get('default') for p in model['params']}

    def pv(name):
        if name.startswith('@has:'):
            v = params.get(name[5:])
            return str(bool(v)).lower() if not isinstance(v, list) else str(len(v) > 0).lower()
        v = params.get(name, defaults.get(name))
        if isinstance(v, bool):
            return str(v).lower()
        return str(v)

    rate = c.get('rate')
    if c.get('by'):
        rate = c['rates'].get('|'.join(pv(b) for b in c['by']))
    if rate is None:
        return {'credits': None, 'reason': 'no price for this combination of settings'}
    if c['type'] == 'per_1k_chars':
        n = len(str(params.get(c['field']) or ''))
        return {'credits': max(0.1, round(n / 1000 * rate, 1)), 'approx': False}
    secs = 1
    if c['type'] == 'per_second':
        src = c['sec']
        if src.startswith('@duration:'):
            dur = media_duration(params.get(src[10:]), assets)
            if not dur:
                return {'credits': None, 'reason': 'needs the length of ' + src[10:]}
            secs = -(-dur // 1)
        else:
            secs = float(params.get(src, defaults.get(src)) or 0)
    return {'credits': round(rate * secs, 1), 'approx': bool(c.get('approx'))}


def resolve_assets(model, params):
    """Let callers (CLI, MCP) pass library asset ids where a media URL is expected."""
    assets = {a['id']: a['url'] for a in load(ASSETS_FILE, [])}
    # a finished job id also works, so results chain without a download and re-upload
    for j in load(JOBS_FILE, []):
        f0 = next((f for f in j.get('files', []) if f.get('remote')), None)
        if j.get('status') == 'done' and f0:
            assets.setdefault(j['id'], f0['remote'])
    out = dict(params)
    for p in model['params']:
        v = out.get(p['name'])
        if p.get('media') and v:
            f = lambda x: assets[x] if isinstance(x, str) and x in assets else x
            out[p['name']] = [f(x) for x in v] if isinstance(v, list) else f(v)
    return out


def media_duration(value, assets=None):
    """Seconds of an asset referenced by id or kie URL (list or single)."""
    if isinstance(value, list):
        value = value[0] if value else None
    if not value:
        return None
    for a in assets if assets is not None else load(ASSETS_FILE, []):
        if value in (a.get('id'), a.get('url')):
            return a.get('duration')
    return None


def probe_duration(path):
    import subprocess
    fp = ffmpeg_bin('ffprobe')
    if not fp:
        return None
    try:
        p = subprocess.run([fp, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        return round(float(p.stdout.strip()), 2)
    except Exception:
        return None


def extract_task_id(r):
    d = r.get('data')
    if isinstance(d, dict):
        return d.get('taskId') or d.get('task_id') or d.get('id')
    if isinstance(d, str):
        return d
    return None


URL_RX = re.compile(r'https?://[^\s"\'\\]+\.(?:mp4|mov|webm|png|jpe?g|webp|gif|mp3|wav)(?:\?[^\s"\'\\]*)?', re.I)


def find_urls(obj):
    s = obj if isinstance(obj, str) else json.dumps(obj)
    seen, out = set(), []
    for u in URL_RX.findall(s.replace('\\/', '/')):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def poll_once(job):
    """Update job in place from kie.ai. Returns True if job reached a final state."""
    model = model_by_id(job['model'])
    fam = (model or {}).get('poll', 'jobs')
    tid = urllib.parse.quote(job['taskId'])
    if fam == 'jobs':
        r = http('GET', f'{API}/api/v1/jobs/recordInfo?taskId={tid}')
        d = r.get('data') or {}
        st = (d.get('state') or '').lower()
        job['state'] = st
        cc = d.get('creditsConsumed', d.get('credits_consumed'))
        if cc is not None:
            job['credits'] = cc
        if st == 'success':
            rj = d.get('resultJson')
            try:
                rj = json.loads(rj) if isinstance(rj, str) else (rj or {})
            except Exception:
                pass
            urls = (rj.get('resultUrls') if isinstance(rj, dict) else None) or find_urls(rj)
            return finish(job, urls)
        if st in ('fail', 'failed', 'error'):
            return fail(job, d.get('failMsg') or d.get('failCode') or 'generation failed')
        job['progress'] = d.get('progress')
        return False
    # dedicated families: veo, runway, etc.  path template from models.json
    pt = model['pollPath'].replace('{taskId}', tid)
    r = http('GET', API + pt)
    d = r.get('data') or {}
    flag = d.get('successFlag')
    status = str(d.get('status') or d.get('state') or '').lower()
    cc = d.get('creditsConsumed', d.get('credits_consumed'))
    if cc is not None:
        job['credits'] = cc
    if flag == 1 or status in ('success', 'succeeded', 'completed', 'complete'):
        src = d.get('response') or d.get('videoInfo') or d.get('resultJson') or d
        if isinstance(src, str):
            try:
                src = json.loads(src)
            except Exception:
                pass
        if isinstance(src, dict) and src.get('sunoData'):
            # Suno returns 2 takes, each with cover art; keep only the audio
            urls = [x['audioUrl'] for x in src['sunoData'] if x.get('audioUrl')]
            job['sunoIds'] = [x.get('id') for x in src['sunoData']]
        else:
            urls = (src.get('resultUrls') if isinstance(src, dict) else None) or find_urls(src)
        return finish(job, urls)
    if flag in (2, 3) or status in ('fail', 'failed', 'error', 'create_task_failed', 'generate_failed',
                                    'generate_audio_failed', 'sensitive_word_error', 'callback_exception'):
        return fail(job, d.get('errorMessage') or d.get('failMsg') or d.get('msg') or 'generation failed')
    return False


def slug(s, n=40):
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s or '').strip('-').lower()
    return s[:n] or 'gen'


def finish(job, urls):
    files = []
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(job['created']))
    for i, u in enumerate(urls):
        ext = os.path.splitext(urllib.parse.urlparse(u).path)[1] or '.mp4'
        name = f"{stamp}_{slug(job['modelName'], 20)}_{slug(job.get('prompt', ''), 30)}_{i + 1}{ext}"
        dest = os.path.join(OUT, name)
        try:
            req = urllib.request.Request(u, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=600) as r, open(dest, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            files.append({'name': name, 'remote': u})
        except Exception as e:
            files.append({'name': None, 'remote': u, 'error': str(e)})
    job['files'] = files
    job['status'] = 'done' if urls else 'failed'
    if not urls:
        job['error'] = 'finished, but kie.ai returned no media URL'
    job['finished'] = time.time()
    board_on_job(job)
    return True


def fail(job, msg):
    job['status'] = 'failed'
    job['error'] = str(msg)
    job['finished'] = time.time()
    board_on_job(job)
    return True


def create_job(model, params, extra=None, est=None, thumbs=None):
    """Send one task to kie.ai and record it in history. Raises on refusal."""
    path, body = build_request(model, params)
    if model['create'].get('callBack'):
        body['callBackUrl'] = model['create']['callBack']
    r = http('POST', API + path, body)
    if r.get('code') not in (200, None):
        raise RuntimeError(f"kie.ai refused the job: {r.get('msg') or r}")
    tid = extract_task_id(r)
    if not tid:
        raise RuntimeError('kie.ai returned no task id: ' + json.dumps(r)[:300])
    prompt = params.get('prompt') or params.get('text') or ''
    job = {'id': uuid.uuid4().hex[:10], 'taskId': tid, 'model': model['key'], 'modelName': model['name'],
           'kind': model['kind'], 'params': params, 'prompt': prompt, 'estCredits': est,
           'status': 'running', 'created': time.time(), 'thumbs': thumbs or []}
    job.update(extra or {})
    with LOCK:
        jobs = load(JOBS_FILE, [])
        jobs.insert(0, job)
        save(JOBS_FILE, jobs)
    return job


# ---------------------------------------------------------------- storyboards
# A board lives in boards/<id>/board.json with its frames, clips, song and final cut
# beside it. Claude writes the script + scenes; Jack reviews in the Storyboards tab,
# redoes frames, leaves notes, and presses "Make the video" to approve the spend.
BOARDS = os.path.join(ROOT, 'boards')
os.makedirs(BOARDS, exist_ok=True)
BLOCK = threading.Lock()


def ffmpeg_bin(name='ffmpeg'):
    import shutil, glob
    p = shutil.which(name)
    if p:
        return p
    hits = glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Packages',
                                  'Gyan.FFmpeg*', '*', 'bin', name + '.exe'))
    return hits[0] if hits else None


def board_dir(bid):
    bid = re.sub(r'[^\w-]', '', bid)
    return os.path.join(BOARDS, bid)


def load_board(bid):
    return load(os.path.join(board_dir(bid), 'board.json'), None)


def save_board(b):
    b['updated'] = time.time()
    save(os.path.join(board_dir(b['id']), 'board.json'), b)


def scene_of(b, sid):
    for s in b['scenes']:
        if s['id'] == sid:
            return s
    raise RuntimeError('no scene ' + sid)


# Lip sync scenes: the frame is animated by a talking-avatar model driven by that scene's
# slice of the song, so a character's mouth follows the vocals. Credits per second of audio.
LIPSYNC = {
    'omnihuman': {'std': 27, 'pro': 27, 'name': 'OmniHuman lip sync'},
    'kling-avatar': {'std': 8, 'pro': 16, 'name': 'Kling Avatar lip sync'},
    'infinitalk': {'std': 12, 'pro': 12, 'name': 'InfiniTalk lip sync'},
}


def clip_seconds(s, model_key):
    dur = s['end'] - s['start']
    if model_key == 'veo3':
        return 8
    if model_key in LIPSYNC:
        return int(max(1, -(-dur // 1)))  # billed on the audio slice, no minimum clip
    return int(min(15, max(3, -(-dur // 1))))  # ceil, Kling takes 3..15


def clip_cost(b, s, mode=None):
    mode = mode or b.get('video', {}).get('mode', 'std')
    if s.get('still'):
        return 0
    m = s.get('clipModel') or b.get('video', {}).get('model', 'kling3')
    if m == 'veo3':
        return 60
    if m in LIPSYNC:
        return LIPSYNC[m][mode] * clip_seconds(s, m)
    rate = {'std': 14, 'pro': 18}[mode] if not s.get('sound') else {'std': 20, 'pro': 27}[mode]
    return rate * clip_seconds(s, m)


def song_file(b):
    return (b.get('song') or {}).get('pick') or (b.get('audio') or {}).get('file')


def song_offset(b):
    return float((b.get('song') or {}).get('offset', (b.get('audio') or {}).get('start', 0)) or 0)


def song_segment(b, s):
    """Cut this scene's slice of the chosen song, for lip sync."""
    import subprocess
    src = song_file(b)
    if not src:
        raise RuntimeError(f"scene {s['n']} is set to lip sync but the storyboard has no song yet")
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError('ffmpeg not found')
    start = song_offset(b) + s['start']
    dur = s['end'] - s['start']
    name = f"{s['id']}_voice_{int(start * 100)}_{int(dur * 100)}.mp3"
    d = board_dir(b['id'])
    if not os.path.isfile(os.path.join(d, name)):
        p = subprocess.run([ff, '-y', '-v', 'error', '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', src,
                            '-ac', '1', '-ar', '44100', '-b:a', '160k', name],
                           cwd=d, capture_output=True, text=True, creationflags=NO_WINDOW)
        if p.returncode != 0:
            raise RuntimeError(p.stderr[-300:])
    return name


# ---- song timing: put every scene cut on the moment its line is sung
def norm_tok(w):
    w = re.sub(r'\[[^\]]*\]', ' ', str(w)).lower().replace('’', "'")
    return re.sub(r"[^a-z0-9%']", '', w)


def fetch_song_timing(b, take):
    """Word timings for one Suno take (0.5 credits). Stored on the take."""
    r = http('POST', API + '/api/v1/generate/get-timestamped-lyrics',
             {'taskId': take['taskId'], 'audioId': take['sunoId']})
    words = (r.get('data') or {}).get('alignedWords') or []
    take['words'] = [[w.get('word', ''), round(float(w.get('startS', 0)), 3), round(float(w.get('endS', 0)), 3)]
                     for w in words]
    return take['words']


def align_scenes(b, words, duration=None, lead=0.12, hold=2.5):
    """Set scene start/end from word timings [[word, start, end], ...].

    Each scene's first lyric word starts its scene (a touch early so the picture lands
    before the word). Scenes whose line is not sung (end cards, sung:false) sit after
    the previous line for `hold` seconds. The song is offset so the first sung word
    starts about a quarter second into the video: the hook plays from frame one.
    Returns a list of scene numbers that could not be matched."""
    W = [(norm_tok(w), s, e) for w, s, e in words]
    W = [x for x in W if x[0]]
    hits, missed, i = [], [], 0
    for s in b['scenes']:
        toks = [t for t in (norm_tok(x) for x in s.get('line', '').split()) if t]
        if s.get('sung') is False or not toks or s.get('still'):
            hits.append(None)
            continue
        found = None
        for k in (min(2, len(toks)), 1):
            for j in range(i, len(W) - k + 1):
                if all(W[j + m][0] == toks[m] for m in range(k)):
                    found = j
                    break
            if found is not None:
                break
        if found is None:
            hits.append(None)
            missed.append(s['n'])
            continue
        last = min(found + len(toks), len(W)) - 1
        hits.append((W[found][1], W[last][2]))
        i = last + 1
    sung = [h for h in hits if h]
    if not sung:
        return [s['n'] for s in b['scenes']]
    offset = max(0.0, sung[0][0] - 0.25)
    b.setdefault('song', {})['offset'] = round(offset, 3)
    n = len(b['scenes'])
    starts = [None] * n
    for k, h in enumerate(hits):
        if h:
            starts[k] = 0.0 if not any(hits[:k]) else max(0.0, h[0] - offset - lead)
    starts[0] = 0.0
    prev_end = 0.0
    for k in range(n):
        if starts[k] is None:  # unsung scene: after the previous sung line
            starts[k] = prev_end + 0.15
        if hits[k]:
            prev_end = hits[k][1] - offset
    for k, s in enumerate(b['scenes']):
        s['start'] = round(starts[k], 2)
        if k + 1 < n and starts[k + 1] > starts[k]:
            s['end'] = round(starts[k + 1], 2)
        elif hits[k]:
            tail = hits[k][1] - offset + 1.2
            if duration:
                tail = min(tail, duration - offset)
            s['end'] = round(max(s['start'] + 1.0, tail), 2)
        else:
            s['end'] = round(s['start'] + s.get('hold', hold), 2)
    return missed


def retime_board(b):
    """Align scenes to the picked take, if it has timings and nothing is rendered yet."""
    sg = b.get('song') or {}
    take = next((t for t in sg.get('takes', []) if t['file'] == sg.get('pick')), None)
    if not take or not take.get('words'):
        return False
    if any(s.get('clipStatus') in ('done', 'running', 'waiting') for s in b['scenes']):
        return False
    dur = probe_duration(os.path.join(board_dir(b['id']), take['file']))
    missed = align_scenes(b, take['words'], dur)
    b['timedTo'] = take['file']
    b['timingMissed'] = missed
    return True


def board_summary(b):
    return {'id': b['id'], 'title': b.get('title'), 'status': b.get('status'), 'created': b.get('created'),
            'updated': b.get('updated'), 'scenes': len(b.get('scenes', [])),
            'cover': next((s['frame'] for s in b['scenes'] if s.get('frame')), None)}


def ref_urls(b):
    """Reference images (character sheet, product shots) re-uploaded if stale."""
    out = []
    changed = False
    for r in b.get('refs', []):
        if not r.get('url') or time.time() - r.get('uploaded', 0) > 20 * 3600:
            p = os.path.join(board_dir(b['id']), r['file'])
            r['url'] = upload_to_kie(p, f"{b['id']}_{r['file']}", mimetypes.guess_type(p)[0] or 'image/png')
            r['uploaded'] = time.time()
            changed = True
        out.append(r['url'])
    return out, changed


def board_file_url(b, fname, key):
    """Upload a board file (frame, clip) to kie once and cache the link on the board."""
    cache = b.setdefault('urls', {})
    c = cache.get(fname)
    if c and time.time() - c['t'] < 20 * 3600:
        return c['url']
    p = os.path.join(board_dir(b['id']), fname)
    url = upload_to_kie(p, f"{b['id']}_{fname}", mimetypes.guess_type(p)[0] or 'application/octet-stream')
    cache[fname] = {'url': url, 't': time.time()}
    return url


# Consistency locks. Image models drift unless every reference is labelled and told
# what it controls; video models improvise extra action and on-screen text unless the
# prompt closes those doors. Written in lowercase: Nano Banana renders capitalised
# instruction words as literal text.
REF_LOCKS = {
    'character': 'reproduce this exact person: same face shape, eyes, nose, lips, jaw, skin tone, hairline, '
                 'hair colour and style; do not beautify, age, or restyle them',
    'product': 'reproduce this exact product: same shape, proportions, colours, materials and markings; '
               'do not invent logos, labels or text on it',
    'style': 'match only the rendering style, palette and colour grading; do not copy its people, text or logos',
    'setting': 'keep this location recognisable: same layout, furniture and light direction',
}
CLIP_LOCK = ('one continuous shot. only the described action happens, everything else stays exactly as in the '
             'start frame. faces, outfits and the product keep their exact look. no on screen text, captions, '
             'subtitles, logos or watermarks.')


def frame_prompt(b, s, refs_used):
    lines = []
    if refs_used:
        lines.append('image references: ' + '; '.join(
            f"image {i + 1} = {r.get('label') or r.get('role') or 'reference'}" for i, r in enumerate(refs_used)))
        for i, r in enumerate(refs_used):
            lock = r.get('lock') or REF_LOCKS.get(r.get('role', ''))
            if lock:
                lines.append(f'image {i + 1}: {lock}.')
    if b.get('style'):
        lines.append(b['style'])
    lines.append(s['picture'])
    return '\n\n'.join(lines)


def clip_prompt(b, s):
    lock = s.get('lock', b.get('clipLock', CLIP_LOCK))
    return s['motion'].rstrip() + ('\n\n' + lock if lock else '')


def start_frame(b, s):
    fm = b.get('frameModel', 'nano-banana-2')
    model = model_by_id(fm)
    urls, _ = ref_urls(b)
    idx = [i for i in s.get('refIdx', range(len(urls))) if i < len(urls)]
    params = {'prompt': frame_prompt(b, s, [b['refs'][i] for i in idx]), 'aspect_ratio': b.get('aspect', '9:16'),
              'resolution': b.get('frameResolution', '1K'), 'output_format': 'png'}
    use = [urls[i] for i in idx]
    if use:
        params['image_input'] = use
    rates = model['cost']['rates']
    job = create_job(model, params, {'board': b['id'], 'scene': s['id'], 'role': 'frame'},
                     est=rates.get(params['resolution']))
    s['frameJob'] = job['id']
    s['frameStatus'] = 'running'
    s.pop('frameError', None)
    b['frameCredits'] = b.get('frameCredits', 0) + (job['estCredits'] or 0)
    return job


def start_clip(b, s, mode):
    mk = s.get('clipModel') or b.get('video', {}).get('model', 'kling3')
    model = model_by_id(mk)
    frame_url = board_file_url(b, s['frame'], 'frame')
    if mk in LIPSYNC:
        audio_url = board_file_url(b, song_segment(b, s), 'voice')
        prompt = s.get('motion') or 'the character sings along, expressive face'
        if mk == 'omnihuman':
            params = {'image_url': frame_url, 'audio_url': audio_url, 'prompt': prompt,
                      'output_resolution': '720' if mode == 'std' else '1080'}
        elif mk == 'kling-avatar':
            params = {'image_url': frame_url, 'audio_url': audio_url, 'prompt': prompt,
                      'tier': 'standard' if mode == 'std' else 'pro'}
        else:
            params = {'image_url': frame_url, 'audio_url': audio_url, 'prompt': prompt, 'resolution': '720p'}
        job = create_job(model, params, {'board': b['id'], 'scene': s['id'], 'role': 'clip'},
                         est=clip_cost(b, s, mode))
        s['clipJob'] = job['id']
        s['clipStatus'] = 'running'
        s.pop('clipError', None)
        return job
    if mk == 'veo3':
        params = {'prompt': clip_prompt(b, s), 'model': 'veo3_fast', 'imageUrls': [frame_url],
                  'aspectRatio': b.get('aspect', '9:16')}
    else:
        params = {'prompt': clip_prompt(b, s), 'image_urls': [frame_url], 'duration': str(clip_seconds(s, mk)),
                  'aspect_ratio': b.get('aspect', '9:16'), 'mode': mode, 'sound': bool(s.get('sound'))}
    job = create_job(model, params, {'board': b['id'], 'scene': s['id'], 'role': 'clip'},
                     est=clip_cost(b, s, mode))
    s['clipJob'] = job['id']
    s['clipStatus'] = 'running'
    s.pop('clipError', None)
    return job


def start_song(b, take=None):
    sg = b['song']
    model = model_by_id('suno')
    params = {'prompt': sg['lyrics'], 'customMode': True, 'instrumental': False,
              'model': sg.get('model', 'V5'), 'style': sg['style'], 'title': sg.get('title', b['title'])[:80]}
    if sg.get('vocalGender'):
        params['vocalGender'] = sg['vocalGender']
    job = create_job(model, params, {'board': b['id'], 'role': 'song'}, est=12)
    sg['job'] = job['id']
    sg['status'] = 'running'
    return job


def board_on_job(job):
    """Called when any job finishes. Files a board job's result into its board."""
    if not job.get('board'):
        return
    with BLOCK:
        b = load_board(job['board'])
        if not b:
            return
        files = [f for f in job.get('files', []) if f.get('name')]
        ok = job['status'] == 'done' and files
        role = job.get('role')
        if role == 'song':
            sg = b.setdefault('song', {})
            if job['id'] in sg.get('ignoreJobs', []):
                return  # set aside by the human: keep the files in Downloads, keep them off the board
            if ok:
                takes = []
                for i, f in enumerate(files):
                    dst = f'song_take{len(sg.get("takes", [])) + i + 1}{os.path.splitext(f["name"])[1]}'
                    copy(os.path.join(OUT, f['name']), os.path.join(board_dir(b['id']), dst))
                    takes.append({'file': dst, 'sunoId': (job.get('sunoIds') or [None] * 9)[i], 'taskId': job['taskId']})
                sg['takes'] = sg.get('takes', []) + takes
                sg.setdefault('pick', takes[0]['file'])
                sg['status'] = 'done'
                if b.get('autoTime', True):
                    for t in takes:
                        try:
                            fetch_song_timing(b, t)
                        except Exception as e:
                            t['timingError'] = str(e)[:200]
                    retime_board(b)
            else:
                sg['status'] = 'failed'
                sg['error'] = job.get('error')
            save_board(b)
            return
        try:
            s = scene_of(b, job['scene'])
        except RuntimeError:
            return
        key = 'frame' if role == 'frame' else 'clip'
        if s.get(key + 'Job') != job['id']:
            return  # superseded by a newer redo
        if ok:
            ext = os.path.splitext(files[0]['name'])[1]
            n = len(s.get(key + 'Versions', [])) + 1
            dst = f"{s['id']}_{key}_v{n}{ext}"
            copy(os.path.join(OUT, files[0]['name']), os.path.join(board_dir(b['id']), dst))
            s[key] = dst
            s.setdefault(key + 'Versions', []).append(dst)
            s[key + 'Status'] = 'done'
        else:
            s[key + 'Status'] = 'failed'
            s[key + 'Error'] = job.get('error')
        if role == 'clip':
            i = b['scenes'].index(s)
            nxt = b['scenes'][i + 1] if i + 1 < len(b['scenes']) else None
            if nxt and nxt.get('fromPrev') and nxt.get('clipStatus') == 'waiting':
                if ok:
                    try:
                        nxt['frame'] = last_frame(b, s)
                        nxt.setdefault('frameVersions', []).append(nxt['frame'])
                        nxt['frameStatus'] = 'done'
                        start_clip(b, nxt, b.get('video', {}).get('mode', 'std'))
                    except Exception as e:
                        nxt['clipStatus'] = 'failed'
                        nxt['clipError'] = 'Could not hand off the last frame: ' + str(e)[:200]
                else:
                    nxt['clipStatus'] = 'failed'
                    nxt['clipError'] = f"Waits on scene {s['n']}, which failed"
        if role == 'clip' and b.get('status') == 'rendering':
            live = [x for x in b['scenes'] if not x.get('still')]
            if all(x.get('clipStatus') == 'done' for x in live):
                b['status'] = 'assembling'
                threading.Thread(target=assemble_safe, args=(b['id'],), daemon=True).start()
            elif not any(x.get('clipStatus') in ('running', 'waiting') for x in live):
                b['status'] = 'clips-failed'
        save_board(b)


def last_frame(b, s):
    """Exact-frame handoff: the next clip starts where this one actually ended."""
    import subprocess
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError('ffmpeg not found')
    d = board_dir(b['id'])
    name = f"{s['id']}_lastframe.png"
    p = subprocess.run([ff, '-y', '-v', 'error', '-sseof', '-0.1', '-i', s['clip'], '-frames:v', '1', '-vf', "scale='min(iw,1080)':-2", '-update', '1', name],
                       cwd=d, capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0 or not os.path.isfile(os.path.join(d, name)):
        raise RuntimeError(p.stderr[-300:])
    return name


def copy(src, dst):
    with open(src, 'rb') as a, open(dst, 'wb') as c:
        while True:
            chunk = a.read(1 << 20)
            if not chunk:
                break
            c.write(chunk)


def ass_time(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def write_captions(b, path):
    cap = b.get('captions', {}) if isinstance(b.get('captions'), dict) else {}
    font = cap.get('font', 'Arial Black')
    size = cap.get('size', 78)
    margin_v = cap.get('marginV', 760)  # px from bottom: sits just above the Reels caption zone
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1080', 'PlayResY: 1920', 'WrapStyle: 0', '',
             '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
             'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, '
             'MarginL, MarginR, MarginV, Encoding',
             f'Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,'
             f'90,90,{margin_v},1', '',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for s in b['scenes']:
        cap_text = s.get('caption', s.get('line', ''))
        if not cap_text or s.get('noCaption'):
            continue
        t = cap_text.replace('\n', '\\N').strip('"“”')
        lines.append(f"Dialogue: 0,{ass_time(s['start'])},{ass_time(s['end'])},Cap,,0,0,0,,{t}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def assemble_safe(bid):
    try:
        assemble(bid)
    except Exception as e:
        with BLOCK:
            b = load_board(bid)
            b['status'] = 'error'
            b['error'] = 'Assembling failed: ' + str(e)[-600:]
            save_board(b)


def assemble(bid):
    import subprocess
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError('ffmpeg not found')
    b = load_board(bid)
    d = board_dir(bid)
    W, Hh = (1080, 1920) if b.get('aspect', '9:16') == '9:16' else (1920, 1080)
    args = [ff, '-y', '-hide_banner', '-loglevel', 'error']
    filt = []
    n = 0
    for s in b['scenes']:
        dur = round(s['end'] - s['start'], 3)
        src = s.get('clip') if not s.get('still') else None
        if src:
            args += ['-i', src]
        else:
            args += ['-loop', '1', '-t', str(dur), '-i', s['frame']]
        ss = s.get('clipOffset', 0)
        filt.append(f'[{n}:v]trim=start={ss}:duration={dur},setpts=PTS-STARTPTS,'
                    f'scale={W}:{Hh}:force_original_aspect_ratio=increase,crop={W}:{Hh},fps=30,setsar=1,'
                    f'tpad=stop_mode=clone:stop_duration={dur},trim=duration={dur}[v{n}]')
        n += 1
    total = round(b['scenes'][-1]['end'] - b['scenes'][0]['start'], 3)
    filt.append(''.join(f'[v{i}]' for i in range(n)) + f'concat=n={n}:v=1:a=0[vc]')
    vout = '[vc]'
    if b.get('captions', True):
        write_captions(b, os.path.join(d, 'captions.ass'))
        filt.append('[vc]ass=captions.ass[vo]')
        vout = '[vo]'
    song = (b.get('song') or {}).get('pick') or (b.get('audio') or {}).get('file')
    amap = []
    if song:
        off = (b.get('song') or {}).get('offset', (b.get('audio') or {}).get('start', 0))
        args += ['-ss', str(off), '-i', song]
        filt.append(f'[{n}:a]atrim=duration={total},afade=t=out:st={max(0, total - 0.6)}:d=0.6[a]')
        amap = ['-map', '[a]', '-c:a', 'aac', '-b:a', '192k']
    out = 'final.mp4'
    args += ['-filter_complex', ';'.join(filt), '-map', vout] + amap + [
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        '-t', str(total), out]
    p = subprocess.run(args, cwd=d, capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    dl = os.path.join(OUT, f"{time.strftime('%Y%m%d-%H%M%S')}_{slug(b['title'], 40)}_final.mp4")
    copy(os.path.join(d, out), dl)
    with BLOCK:
        b = load_board(bid)
        b['final'] = out
        b['finalDownload'] = os.path.basename(dl)
        b['status'] = 'done'
        b.pop('error', None)
        save_board(b)


def poller():
    while True:
        time.sleep(8)
        with LOCK:
            jobs = load(JOBS_FILE, [])
        pending = [j for j in jobs if j['status'] == 'running']
        if not pending:
            continue
        changed = False
        for j in pending:
            try:
                if poll_once(j):
                    changed = True
                elif time.time() - j['created'] > 3 * 3600:
                    fail(j, 'timed out after 3 hours')
                    changed = True
                else:
                    changed = True  # progress may have moved
            except Exception as e:
                j['lastPollError'] = str(e)[:300]
        if changed:
            with LOCK:
                cur = {x['id']: x for x in load(JOBS_FILE, [])}
                for j in pending:
                    cur[j['id']] = j
                save(JOBS_FILE, sorted(cur.values(), key=lambda x: -x['created']))


SCENE_FIELDS = {'line', 'caption', 'picture', 'motion', 'note', 'start', 'end', 'sound', 'still', 'clipModel',
                'noCaption', 'clipOffset', 'tags', 'refIdx', 'lock', 'fromPrev', 'sung', 'hold'}
BOARD_FIELDS = {'title', 'subtitle', 'style', 'note', 'captions', 'frameResolution', 'clipLock', 'autoTime'}


def board_create(spec):
    """Claude calls this with a full script. refs are local file paths copied into the board."""
    bid = time.strftime('%Y%m%d-%H%M%S') + '-' + slug(spec.get('title', 'board'), 30)
    d = board_dir(bid)
    os.makedirs(d, exist_ok=True)
    refs = []
    for i, r in enumerate(spec.get('refs', [])):
        src = r['path']
        dst = f"ref{i + 1}_{re.sub(r'[^\w.-]+', '_', os.path.basename(src))[-50:]}"
        copy(src, os.path.join(d, dst))
        refs.append({'label': r.get('label', ''), 'file': dst, 'role': r.get('role', ''), 'lock': r.get('lock')})
    scenes = []
    for i, s in enumerate(spec['scenes']):
        s = dict(s)
        s.setdefault('id', f's{i + 1}')
        s['n'] = i + 1
        s.setdefault('frameStatus', 'none')
        s.setdefault('clipStatus', 'none')
        scenes.append(s)
    b = {'id': bid, 'title': spec.get('title', 'Untitled'), 'subtitle': spec.get('subtitle', ''),
         'concept': spec.get('concept', ''), 'product': spec.get('product', ''), 'hook': spec.get('hook', ''),
         'style': spec.get('style', ''), 'aspect': spec.get('aspect', '9:16'), 'refs': refs,
         'frameModel': spec.get('frameModel', 'nano-banana-2'), 'frameResolution': spec.get('frameResolution', '1K'),
         'video': spec.get('video', {'model': 'kling3', 'mode': 'std'}), 'captions': spec.get('captions', True),
         'song': spec.get('song'), 'audio': spec.get('audio'), 'endcard': spec.get('endcard'),
         'clipLock': spec.get('clipLock', CLIP_LOCK),
         'scenes': scenes, 'status': 'draft', 'created': time.time(), 'frameCredits': 0, 'log': []}
    save_board(b)
    return b


def board_action(bid, action, req):
    with BLOCK:
        b = load_board(bid)
        if not b:
            raise RuntimeError('no such storyboard')
        if action == 'update':
            tgt = scene_of(b, req['scene']) if req.get('scene') else b
            allowed = SCENE_FIELDS if req.get('scene') else BOARD_FIELDS
            for k, v in (req.get('fields') or {}).items():
                if k in allowed:
                    tgt[k] = v
                elif not req.get('scene') and k in ('mode', 'model'):
                    b.setdefault('video', {})[k] = v
                elif not req.get('scene') and k in ('songLyrics', 'songStyle', 'songTitle'):
                    b.setdefault('song', {})[{'songLyrics': 'lyrics', 'songStyle': 'style', 'songTitle': 'title'}[k]] = v
                elif not req.get('scene') and k in ('songPick', 'songOffset'):
                    b.setdefault('song', {})['pick' if k == 'songPick' else 'offset'] = v
                    if k == 'songPick' and b.get('autoTime', True):
                        retime_board(b)  # scene cuts follow the take you chose
        elif action == 'pick':
            s = scene_of(b, req['scene'])
            key = req['key']
            if req['file'] in s.get(key + 'Versions', []):
                s[key] = req['file']
        elif action == 'frame':
            start_frame(b, scene_of(b, req['scene']))
        elif action == 'frames':
            for s in b['scenes']:
                if s.get('fromPrev'):
                    continue  # its start frame is the previous clip's last frame
                if req.get('all') or s.get('frameStatus') in ('none', 'failed', None):
                    start_frame(b, s)
                    save_board(b)
                    time.sleep(0.4)
        elif action == 'clip':
            start_clip(b, scene_of(b, req['scene']), req.get('mode') or b.get('video', {}).get('mode', 'std'))
        elif action == 'render':
            mode = req.get('mode') or b.get('video', {}).get('mode', 'std')
            b.setdefault('video', {})['mode'] = mode
            missing = [s['n'] for s in b['scenes'] if not s.get('frame') and not s.get('fromPrev')]
            if missing:
                raise RuntimeError('These scenes have no frame yet: ' + ', '.join(map(str, missing)))
            b['status'] = 'rendering'
            b['approvedAt'] = time.time()
            started = 0
            for s in b['scenes']:
                if s.get('still') or (s.get('clipStatus') in ('done', 'running') and not req.get('fresh')):
                    continue
                if s.get('fromPrev'):
                    s['clipStatus'] = 'waiting'  # starts when the previous clip lands
                    continue
                start_clip(b, s, mode)
                started += 1
                save_board(b)
                time.sleep(0.4)
            live = [x for x in b['scenes'] if not x.get('still')]
            if not started and all(x.get('clipStatus') == 'done' for x in live):
                b['status'] = 'assembling'
                threading.Thread(target=assemble_safe, args=(bid,), daemon=True).start()
        elif action == 'assemble':
            b['status'] = 'assembling'
            threading.Thread(target=assemble_safe, args=(bid,), daemon=True).start()
        elif action == 'song':
            if not b.get('song', {}).get('lyrics'):
                raise RuntimeError('This storyboard has no lyrics yet')
            start_song(b)
        elif action == 'song-cancel':
            # Set the song aside: a running job is ignored when it lands, finished takes move
            # off the board (their files stay in Downloads), and nothing is timed to them.
            sg = b.setdefault('song', {})
            if sg.get('job'):
                sg.setdefault('ignoreJobs', []).append(sg.pop('job'))
            if sg.get('takes'):
                sg.setdefault('setAside', []).extend(sg.pop('takes'))
            sg.pop('pick', None)
            sg['status'] = 'cancelled'
            b.pop('timedTo', None)
            b.pop('timingMissed', None)
        save_board(b)
        return b


# ---------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    def serve_file(self, path):
        if not os.path.isfile(path):
            return self.send_json({'error': 'not found'}, 404)
        size = os.path.getsize(path)
        mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        if rng and rng.startswith('bytes='):
            a, _, b = rng[6:].partition('-')
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if (a and b) else size - 1
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    return
                left -= len(chunk)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        try:
            if p in ('/', '/index.html'):
                return self.serve_file(os.path.join(STATIC, 'index.html'))
            if p.startswith('/static/'):
                return self.serve_file(os.path.join(STATIC, os.path.basename(p)))
            if p.startswith('/media/'):
                return self.serve_file(os.path.join(OUT, os.path.basename(urllib.parse.unquote(p))))
            if p.startswith('/uploads/'):
                return self.serve_file(os.path.join(UPLOADS, os.path.basename(urllib.parse.unquote(p))))
            if p == '/api/models':
                return self.send_json(models())
            if p == '/api/presets':
                return self.send_json(load(os.path.join(ROOT, 'presets.json'), {}))
            if p == '/api/jobs':
                with LOCK:
                    return self.send_json(load(JOBS_FILE, []))
            m = re.match(r'^/api/jobs/([\w-]+)$', p)
            if m:
                with LOCK:
                    j = next((x for x in load(JOBS_FILE, []) if x['id'] == m.group(1)), None)
                return self.send_json(j) if j else self.send_json({'error': 'no such job'}, 404)
            if p == '/api/assets':
                with LOCK:
                    return self.send_json(load(ASSETS_FILE, []))
            if p == '/api/boards':
                out = []
                for bid in sorted(os.listdir(BOARDS), reverse=True):
                    b = load_board(bid)
                    if b:
                        out.append(board_summary(b))
                return self.send_json(sorted(out, key=lambda x: -(x.get('updated') or 0)))
            m = re.match(r'^/api/boards/([\w-]+)$', p)
            if m:
                b = load_board(m.group(1))
                if not b:
                    return self.send_json({'error': 'no such storyboard'}, 404)
                b['_costs'] = {mode: sum(clip_cost(b, s, mode) for s in b['scenes']) for mode in ('std', 'pro')}
                b['_sceneCosts'] = {s['id']: {m: clip_cost(b, s, m) for m in ('std', 'pro')} for s in b['scenes']}
                b['_lipsync'] = {k: v['name'] for k, v in LIPSYNC.items()}
                b['_ffmpeg'] = bool(ffmpeg_bin())
                return self.send_json(b)
            m = re.match(r'^/boards/([\w-]+)/([^/]+)$', p)
            if m:
                return self.serve_file(os.path.join(board_dir(m.group(1)), os.path.basename(urllib.parse.unquote(m.group(2)))))
            if p == '/api/health':
                return self.send_json({'ok': True, 'version': VERSION, 'python': sys.version.split()[0],
                                       'keyPresent': bool(kie_key()), 'ffmpeg': ffmpeg_bin(),
                                       'ffprobe': ffmpeg_bin('ffprobe'), 'outputDir': OUT,
                                       'models': len(models()['models'])})
            if p == '/api/credits':
                r = http('GET', API + '/api/v1/chat/credit', timeout=30)
                return self.send_json({'credits': r.get('data')})
            return self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            return self.send_json({'error': str(e)}, 502)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if self.headers.get('X-Studio') != '1':
            return self.send_json({'error': 'missing X-Studio header'}, 403)
        try:
            if p == '/api/upload':
                return self.upload()
            if p == '/api/generate':
                return self.generate()
            if p == '/api/estimate':
                req = json.loads(self.body() or b'{}')
                model = model_by_id(req.get('model'))
                if not model:
                    return self.send_json({'error': 'unknown model'}, 400)
                return self.send_json(estimate(model, resolve_assets(model, req.get('params') or {})))
            if p == '/api/assets/delete':
                req = json.loads(self.body() or b'{}')
                with LOCK:
                    a = [x for x in load(ASSETS_FILE, []) if x['id'] != req.get('id')]
                    save(ASSETS_FILE, a)
                return self.send_json({'ok': True})
            if p == '/api/jobs/delete':
                req = json.loads(self.body() or b'{}')
                with LOCK:
                    j = [x for x in load(JOBS_FILE, []) if x['id'] != req.get('id')]
                    save(JOBS_FILE, j)
                return self.send_json({'ok': True})
            if p == '/api/assets/from-output':
                return self.asset_from_output()
            if p == '/api/open-folder':
                open_folder(OUT)
                return self.send_json({'ok': True})
            if p == '/api/boards/create':
                return self.send_json(board_create(json.loads(self.body() or b'{}')))
            m = re.match(r'^/api/boards/([\w-]+)/(update|frame|frames|clip|render|assemble|song|song-cancel|pick)$', p)
            if m:
                req = json.loads(self.body() or b'{}')
                return self.send_json(board_action(m.group(1), m.group(2), req))
            return self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            return self.send_json({'error': str(e)}, 502)

    def upload(self):
        name = urllib.parse.unquote(self.headers.get('X-Filename') or 'file')
        name = re.sub(r'[^\w.\-]+', '_', name)[-80:]
        mime = self.headers.get('Content-Type') or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        raw = self.body()
        aid = uuid.uuid4().hex[:10]
        local = f'{aid}_{name}'
        path = os.path.join(UPLOADS, local)
        with open(path, 'wb') as f:
            f.write(raw)
        url = upload_to_kie(path, local, mime)
        kind = 'video' if mime.startswith('video') else 'audio' if mime.startswith('audio') else 'image'
        try:
            dur = float(self.headers.get('X-Duration') or 0) or None
        except ValueError:
            dur = None
        if not dur and kind in ('video', 'audio'):
            dur = probe_duration(path)
        a = {'id': aid, 'name': name, 'local': '/uploads/' + local, 'url': url, 'kind': kind,
             'mime': mime, 'size': len(raw), 'added': time.time(), 'duration': dur,
             'uploaded': time.time()}
        with LOCK:
            assets = load(ASSETS_FILE, [])
            assets.insert(0, a)
            save(ASSETS_FILE, assets)
        return self.send_json(a)

    def asset_from_output(self):
        req = json.loads(self.body() or b'{}')
        fname = os.path.basename(req.get('file', ''))
        src = os.path.join(OUT, fname)
        if not os.path.isfile(src):
            return self.send_json({'error': 'file not found'}, 404)
        mime = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
        aid = uuid.uuid4().hex[:10]
        local = f'{aid}_{fname}'
        dst = os.path.join(UPLOADS, local)
        with open(src, 'rb') as a, open(dst, 'wb') as b:
            b.write(a.read())
        url = req.get('remote') or upload_to_kie(dst, local, mime)
        kind = 'video' if mime.startswith('video') else 'audio' if mime.startswith('audio') else 'image'
        a = {'id': aid, 'name': fname, 'local': '/uploads/' + local, 'url': url, 'kind': kind,
             'mime': mime, 'size': os.path.getsize(dst), 'added': time.time(), 'uploaded': time.time(),
             'duration': probe_duration(dst) if kind in ('video', 'audio') else None}
        with LOCK:
            assets = load(ASSETS_FILE, [])
            assets.insert(0, a)
            save(ASSETS_FILE, assets)
        return self.send_json(a)

    def refresh_stale_urls(self, params):
        """kie.ai file links expire after 1-3 days. Re-upload any asset older than 20h."""
        with LOCK:
            assets = load(ASSETS_FILE, [])
        by_url = {a['url']: a for a in assets}
        changed = False

        def fix(u):
            nonlocal changed
            a = by_url.get(u) if isinstance(u, str) else None
            if not a or time.time() - a.get('uploaded', a.get('added', 0)) < 20 * 3600:
                return u
            local = os.path.join(UPLOADS, os.path.basename(a['local']))
            if not os.path.isfile(local):
                return u
            a['url'] = upload_to_kie(local, os.path.basename(local), a['mime'])
            a['uploaded'] = time.time()
            changed = True
            return a['url']

        out = {k: ([fix(x) for x in v] if isinstance(v, list) else fix(v)) for k, v in params.items()}
        if changed:
            with LOCK:
                cur = load(ASSETS_FILE, [])
                fresh = {a['id']: a for a in by_url.values()}
                save(ASSETS_FILE, [fresh.get(a['id'], a) for a in cur])
        return out

    def generate(self):
        req = json.loads(self.body() or b'{}')
        model = model_by_id(req.get('model'))
        if not model:
            return self.send_json({'error': 'unknown model'}, 400)
        params = req.get('params') or {}
        missing = [p['label'] if p.get('label') else p['name'] for p in model['params']
                   if p.get('required') and params.get(p['name']) in (None, '', [])]
        if missing:
            return self.send_json({'error': 'Fill in: ' + ', '.join(missing)}, 400)
        params = self.refresh_stale_urls(resolve_assets(model, params))
        try:
            job = create_job(model, params, est=req.get('estCredits'), thumbs=req.get('thumbs'))
        except RuntimeError as e:
            return self.send_json({'error': str(e)}, 400)
        return self.send_json(job)


def main():
    if not kie_key():
        print('No kie.ai key found. Put it in ~/somnei-shopify/.kie-token')
        sys.exit(1)
    # The keep-alive task relaunches this every 5 minutes. On Windows,
    # allow_reuse_address lets a second copy bind the same port, so turn it
    # off: a duplicate fails to bind and exits before it starts polling.
    class Srv(ThreadingHTTPServer):
        allow_reuse_address = False
    try:
        srv = Srv(('127.0.0.1', PORT), H)
    except OSError:
        sys.exit(0)
    threading.Thread(target=poller, daemon=True).start()
    print(f'Somnei Studio on http://localhost:{PORT}  (outputs -> {OUT})')
    srv.serve_forever()


if __name__ == '__main__':
    main()

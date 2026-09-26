#!/usr/bin/env python3
"""studio: command-line control for a running Somnei Studio server.

Built for agents (Claude Code, Codex) as much as people. Every command can
print JSON with --json. Anything that spends kie.ai credits prints its cost
and exits with code 2 unless you pass --yes.

    python cli.py models --kind video
    python cli.py model kling3
    python cli.py upload product.png
    python cli.py generate kling3 -p "slow dolly in on the trimmer" -m image_urls=product.png -s duration=5
    python cli.py generate kling3 ... --yes --wait
    python cli.py jobs
    python cli.py board create spec.json
    python cli.py board frames <id>
    python cli.py board render <id> --mode std --yes
"""
import argparse, json, mimetypes, os, sys, time, urllib.request, urllib.error, urllib.parse

BASE = os.environ.get('STUDIO_URL', 'http://localhost:4950')
EXIT_NEEDS_CONFIRM = 2


class StudioError(Exception):
    pass


def call(method, path, body=None, raw=None, headers=None):
    h = {'X-Studio': '1'}
    data = None
    if raw is not None:
        data = raw
    elif body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get('error')
        except Exception:
            msg = f'HTTP {e.code}'
        raise StudioError(msg)
    except urllib.error.URLError:
        raise StudioError(f'Studio server is not running at {BASE}. Start it with: python server.py')


def out(args, obj, human=None):
    if args.json or human is None:
        print(json.dumps(obj, indent=2))
    else:
        print(human)


# ------------------------------------------------------------------ helpers
def find_model(key):
    for m in call('GET', '/api/models')['models']:
        if m['key'] == key:
            return m
    raise StudioError(f'Unknown model "{key}". Run: studio models')


def parse_value(p, v):
    t = p.get('type')
    if t == 'boolean':
        return v.lower() in ('1', 'true', 'yes', 'on')
    if t == 'integer':
        return int(float(v))
    if t == 'number':
        return float(v)
    return v


def upload(path):
    if not os.path.isfile(path):
        raise StudioError(f'No such file: {path}')
    mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    with open(path, 'rb') as f:
        return call('POST', '/api/upload', raw=f.read(),
                    headers={'Content-Type': mime, 'X-Filename': urllib.parse.quote(os.path.basename(path))})


def media_value(v):
    """A file path gets uploaded; anything else (asset id, URL) passes through."""
    return upload(v)['id'] if os.path.isfile(v) else v


def build_params(model, args):
    params = {}
    by = {p['name']: p for p in model['params']}
    prompt_p = next((p for p in model['params'] if p.get('control') == 'prompt'), None)
    if args.prompt == '-':
        args.prompt = sys.stdin.read().strip()
    if args.prompt:
        if not prompt_p:
            raise StudioError(f'{model["name"]} has no prompt')
        params[prompt_p['name']] = args.prompt
    for kv in args.set or []:
        k, _, v = kv.partition('=')
        if k not in by:
            raise StudioError(f'{model["name"]} has no setting "{k}". Run: studio model {model["key"]}')
        params[k] = parse_value(by[k], v)
    for kv in args.media or []:
        k, _, v = kv.partition('=')
        p = by.get(k)
        if not p or not p.get('media'):
            raise StudioError(f'"{k}" is not a media input of {model["name"]}')
        val = media_value(v)
        if p.get('multiple'):
            params.setdefault(k, []).append(val)
        else:
            params[k] = val
    for p in model['params']:
        if p['name'] not in params and p.get('default') is not None and not p.get('media'):
            params[p['name']] = p['default']
    return params


def wait_job(jid, quiet=False):
    last = None
    while True:
        j = call('GET', f'/api/jobs/{jid}')
        if j['status'] != 'running':
            return j
        if not quiet and j.get('state') != last:
            last = j.get('state')
            print(f'  {j["modelName"]}: {last or "queued"} ({int(time.time() - j["created"])}s)', file=sys.stderr)
        time.sleep(6)


def job_line(j):
    files = ', '.join(f['name'] for f in j.get('files', []) if f.get('name'))
    cr = j.get('credits', j.get('estCredits'))
    return f'{j["id"]}  {j["status"]:<8} {j["modelName"]:<22} {cr if cr is not None else "?":>6} cr  ' + \
           (files or j.get('error', '') or (j.get('prompt') or '')[:50])


# ------------------------------------------------------------------ commands
def cmd_doctor(a):
    checks = []
    try:
        h = call('GET', '/api/health')
        checks.append(('server', True, f'running at {BASE}, v{h["version"]}, {h["models"]} models'))
        checks.append(('python', tuple(map(int, h['python'].split('.')[:2])) >= (3, 10), h['python']))
        checks.append(('kie.ai key', h['keyPresent'], 'found' if h['keyPresent'] else
                       'missing: set KIE_AI_API_KEY or ~/somnei-shopify/.kie-token'))
        if h['keyPresent']:
            try:
                c = call('GET', '/api/credits')['credits']
                checks.append(('kie.ai account', True, f'{c:,} credits'))
            except StudioError as e:
                checks.append(('kie.ai account', False, str(e)))
        checks.append(('ffmpeg', bool(h['ffmpeg']), h['ffmpeg'] or 'missing: storyboard cuts will fail '
                       '(winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)'))
        checks.append(('ffprobe', bool(h['ffprobe']), h['ffprobe'] or 'missing: clip lengths for avatar costs unknown'))
        checks.append(('output folder', os.access(h['outputDir'], os.W_OK), h['outputDir']))
    except StudioError as e:
        checks.append(('server', False, str(e)))
    ok = all(c[1] for c in checks)
    out(a, {'ok': ok, 'checks': [{'name': n, 'ok': o, 'detail': d} for n, o, d in checks]},
        '\n'.join(f'{"ok " if o else "BAD"}  {n:<15} {d}' for n, o, d in checks))
    if not ok:
        sys.exit(1)


def cmd_credits(a):
    c = call('GET', '/api/credits')['credits']
    out(a, {'credits': c}, f'{c:,} credits (about ${c * 0.005:,.2f})')


def cmd_models(a):
    ms = [m for m in call('GET', '/api/models')['models'] if not a.kind or m['kind'] == a.kind]
    rows = [f'{m["key"]:<16} {m["kind"]:<8} {m["name"]:<26} {m["blurb"][:70]}' for m in ms]
    out(a, [{k: m[k] for k in ('key', 'name', 'kind', 'blurb')} for m in ms], '\n'.join(rows))


def cmd_model(a):
    m = find_model(a.key)
    lines = [f'{m["name"]} ({m["key"]}, {m["kind"]})', m['blurb'], '']
    for p in m['params']:
        flag = '-m' if p.get('media') else ('-p' if p.get('control') == 'prompt' else '-s')
        opts = ' | '.join(map(str, p['enum'])) if p.get('enum') else (
            f'{p.get("min")}..{p.get("max")}' if p.get('min') is not None else p.get('type', ''))
        media = f'{p["media"]}{" x" + str(p.get("maxItems")) if p.get("multiple") else ""}' if p.get('media') else ''
        lines.append(f'  {flag} {p["name"]:<22} {"required " if p.get("required") else ""}{media or opts}'
                     f'{"  default " + str(p["default"]) if p.get("default") is not None else ""}')
    out(a, m, '\n'.join(lines))


def cmd_upload(a):
    res = [upload(f) for f in a.files]
    out(a, res, '\n'.join(f'{r["id"]}  {r["kind"]:<6} {r["name"]}' + (f'  {r["duration"]}s' if r.get('duration') else '')
                         for r in res))


def cmd_assets(a):
    res = call('GET', '/api/assets')
    out(a, res, '\n'.join(f'{r["id"]}  {r["kind"]:<6} {r["name"]}' for r in res) or 'No media yet.')


def cmd_cost(a):
    m = find_model(a.model)
    e = call('POST', '/api/estimate', {'model': m['key'], 'params': build_params(m, a)})
    out(a, e, f'{"about " if e.get("approx") else ""}{e["credits"]} credits (${e["credits"] * 0.005:.2f})'
        if e.get('credits') is not None else e.get('reason'))


def cmd_generate(a):
    m = find_model(a.model)
    params = build_params(m, a)
    e = call('POST', '/api/estimate', {'model': m['key'], 'params': params})
    cost = e.get('credits')
    if not a.yes:
        msg = (f'{m["name"]} will cost {"about " if e.get("approx") else ""}{cost} credits (${cost * 0.005:.2f}).'
               if cost is not None else f'{m["name"]}: {e.get("reason")}. Real cost shows after it runs.')
        out(a, {'needsConfirm': True, 'estimate': e, 'params': params}, msg + ' Re-run with --yes to spend it.')
        sys.exit(EXIT_NEEDS_CONFIRM)
    job = call('POST', '/api/generate', {'model': m['key'], 'params': params, 'estCredits': cost})
    if a.wait:
        job = wait_job(job['id'], quiet=a.json)
    out(a, job, job_line(job) + ('' if a.wait else f'\nRunning. Check with: studio job {job["id"]}'))
    if job['status'] == 'failed':
        sys.exit(1)


def cmd_jobs(a):
    js = call('GET', '/api/jobs')[:a.limit]
    out(a, js, '\n'.join(job_line(j) for j in js) or 'No jobs yet.')


def cmd_job(a):
    j = wait_job(a.id, quiet=a.json) if a.wait else call('GET', f'/api/jobs/{a.id}')
    out(a, j, job_line(j))


def cmd_board(a):
    if a.action == 'list':
        bs = call('GET', '/api/boards')
        return out(a, bs, '\n'.join(f'{b["id"]}  {b["status"]:<11} {b["scenes"]:>2} scenes  {b["title"]}' for b in bs)
                   or 'No storyboards yet.')
    if a.action == 'create':
        with open(a.target, encoding='utf-8') as f:
            b = call('POST', '/api/boards/create', json.load(f))
        return out(a, b, f'Created {b["id"]} with {len(b["scenes"])} scenes. Open http://localhost:4950 > Storyboards.')
    bid = a.target
    if a.action == 'show':
        b = call('GET', f'/api/boards/{bid}')
        lines = [f'{b["title"]}  [{b["status"]}]  std {b["_costs"]["std"]} cr / pro {b["_costs"]["pro"]} cr',
                 f'board note: {b.get("note") or "-"}']
        for s in b['scenes']:
            lines.append(f'  {s["n"]:>2} {s["start"]:>5.1f}-{s["end"]:<5.1f} frame:{s.get("frameStatus")} '
                         f'clip:{s.get("clipStatus")}  {s.get("line", "")[:50]}' +
                         (f'\n      NOTE: {s["note"]}' if s.get('note') else ''))
        return out(a, b, '\n'.join(lines))
    if a.action == 'frames':
        b = call('POST', f'/api/boards/{bid}/frames', {'all': a.all})
        return out(a, b, f'Drawing frames. {b.get("frameCredits", 0)} credits spent on frames so far.')
    if a.action == 'render':
        b = call('GET', f'/api/boards/{bid}')
        cost = b['_costs'][a.mode]
        if not a.yes:
            out(a, {'needsConfirm': True, 'credits': cost},
                f'Making every clip at {a.mode} costs {cost} credits (${cost * 0.005:.2f}). Re-run with --yes.')
            sys.exit(EXIT_NEEDS_CONFIRM)
        b = call('POST', f'/api/boards/{bid}/render', {'mode': a.mode})
        return out(a, b, f'Rendering {bid}: {b["status"]}.')
    if a.action == 'song':
        if not a.yes:
            out(a, {'needsConfirm': True, 'credits': 12}, 'A Suno song costs 12 credits ($0.06). Re-run with --yes.')
            sys.exit(EXIT_NEEDS_CONFIRM)
        return out(a, call('POST', f'/api/boards/{bid}/song', {}), 'Writing the song.')
    if a.action == 'assemble':
        return out(a, call('POST', f'/api/boards/{bid}/assemble', {}), 'Cutting the video (free).')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='studio', description='Control a running Somnei Studio server.')
    ap.add_argument('--json', action='store_true', help='print JSON')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='print JSON')
    sub = ap.add_subparsers(dest='cmd', required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *x, **k: _add(*x, parents=[common], **k)

    sub.add_parser('doctor', help='check server, key, ffmpeg').set_defaults(fn=cmd_doctor)
    sub.add_parser('credits', help='kie.ai credit balance').set_defaults(fn=cmd_credits)
    p = sub.add_parser('models', help='list models'); p.add_argument('--kind'); p.set_defaults(fn=cmd_models)
    p = sub.add_parser('model', help='show a model\'s settings'); p.add_argument('key'); p.set_defaults(fn=cmd_model)
    p = sub.add_parser('upload', help='add files to the media library'); p.add_argument('files', nargs='+'); p.set_defaults(fn=cmd_upload)
    sub.add_parser('assets', help='list the media library').set_defaults(fn=cmd_assets)

    for name, fn, hlp in (('generate', cmd_generate, 'run a model'), ('cost', cmd_cost, 'estimate a run')):
        p = sub.add_parser(name, help=hlp)
        p.add_argument('model')
        p.add_argument('-p', '--prompt', help='text, or - to read from stdin')
        p.add_argument('-s', '--set', action='append', metavar='KEY=VALUE', help='a setting, repeatable')
        p.add_argument('-m', '--media', action='append', metavar='KEY=FILE|ASSET_ID|JOB_ID|URL', help='a media input, repeatable')
        if name == 'generate':
            p.add_argument('--yes', action='store_true', help='spend the credits')
            p.add_argument('--wait', action='store_true', help='block until finished')
        p.set_defaults(fn=fn)

    p = sub.add_parser('jobs', help='recent generations'); p.add_argument('--limit', type=int, default=15); p.set_defaults(fn=cmd_jobs)
    p = sub.add_parser('job', help='one generation'); p.add_argument('id'); p.add_argument('--wait', action='store_true'); p.set_defaults(fn=cmd_job)

    p = sub.add_parser('board', help='storyboards')
    p.add_argument('action', choices=['list', 'create', 'show', 'frames', 'render', 'song', 'assemble'])
    p.add_argument('target', nargs='?', help='spec.json for create, board id otherwise')
    p.add_argument('--mode', choices=['std', 'pro'], default='std')
    p.add_argument('--all', action='store_true', help='frames: redraw every scene')
    p.add_argument('--yes', action='store_true')
    p.set_defaults(fn=cmd_board)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except StudioError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Somnei Studio MCP server (stdio, standard library only).

Gives any MCP client (Claude Code, Claude Desktop, Cursor, Codex) tools to price,
run and track kie.ai generations and storyboards through a running studio server.

Register with Claude Code:
    claude mcp add somnei-studio -- python /path/to/somnei-studio/mcp_server.py

Spending tools (generate, board_render, board_song) refuse to run until called
again with confirm=true, and they report the credit cost first. Agents should show
that cost to the human before confirming.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli  # noqa: E402  (shares the HTTP client and upload logic)

PROTOCOL = '2025-06-18'
S = {'type': 'string'}
OBJ = {'type': 'object'}


def tool(name, desc, props=None, required=()):
    return {'name': name, 'description': desc,
            'inputSchema': {'type': 'object', 'properties': props or {}, 'required': list(required)}}


TOOLS = [
    tool('credits', 'kie.ai credit balance. 1 credit = $0.005.'),
    tool('list_models', 'List generation models. kind: video, edit, avatar, image, audio, upscale.',
         {'kind': S}),
    tool('describe_model', 'Every setting of one model: names, allowed values, defaults, which inputs take '
         'images/videos/audio. Call before generate.', {'model': S}, ['model']),
    tool('upload_file', 'Add a local image, video or audio file to the studio media library. Returns an asset id '
         'usable in any media setting.', {'path': S}, ['path']),
    tool('list_assets', 'Media library contents (id, kind, name, duration).'),
    tool('estimate', 'Credit cost of a run without spending anything.', {'model': S, 'params': OBJ}, ['model', 'params']),
    tool('generate', 'Run a model. params keys come from describe_model; media settings take asset ids, local file '
         'paths or URLs. Without confirm=true this only returns the cost. Show the cost to the user and get their '
         'OK before confirming. A finished job id also works as a media input, to chain results.', {'model': S, 'params': OBJ, 'confirm': {'type': 'boolean'},
                                   'wait': {'type': 'boolean', 'description': 'block up to 10 min for the result'}},
         ['model', 'params']),
    tool('get_job', 'Status and output files of one generation.', {'id': S, 'wait': {'type': 'boolean'}}, ['id']),
    tool('list_jobs', 'Recent generations, newest first.', {'limit': {'type': 'integer'}}),
    tool('board_create', 'Create a storyboard for human review. spec: {title, subtitle, hook, product, style, '
         'refs:[{label,path,role:character|product|style|setting}], clipLock, song:{lyrics,style,title,vocalGender}, video:{model:"kling3",mode:"std"}, '
         'frameResolution:"1K", scenes:[{start,end,line,picture,motion,tags,still,sound,clipModel,refIdx,lock,'
         'fromPrev}]}. See skills/storyboard/references/storyboard-spec.md.',
         {'spec': OBJ}, ['spec']),
    tool('board_list', 'All storyboards.'),
    tool('board_get', 'One storyboard with scene statuses, costs and the human\'s notes (scene.note, note).',
         {'id': S}, ['id']),
    tool('board_update', 'Edit a scene (line, caption, picture, motion, start, end, sound, still, clipModel, note, '
         'lock, fromPrev) or, without scene, the board (title, subtitle, style, note, captions, clipLock).',
         {'id': S, 'scene': S, 'fields': OBJ}, ['id', 'fields']),
    tool('board_frames', 'Draw start frames for every scene that has none (Nano Banana 2, 8 credits each at 1K). '
         'all=true redraws every scene.', {'id': S, 'all': {'type': 'boolean'}}, ['id']),
    tool('board_frame', 'Redraw one scene\'s frame.', {'id': S, 'scene': S}, ['id', 'scene']),
    tool('board_render', 'Approve the storyboard and make every clip, then auto-cut the final video. Without '
         'confirm=true returns the cost only. Only confirm after the human approves.',
         {'id': S, 'mode': {'type': 'string', 'enum': ['std', 'pro']}, 'confirm': {'type': 'boolean'}}, ['id']),
    tool('board_song', 'Generate the storyboard\'s song with Suno (12 credits, 2 takes). Needs confirm=true.',
         {'id': S, 'confirm': {'type': 'boolean'}}, ['id']),
    tool('board_assemble', 'Re-cut the final video from existing clips (free).', {'id': S}, ['id']),
]


def media_params(model, params):
    by = {p['name']: p for p in model['params']}
    out = {}
    for k, v in params.items():
        p = by.get(k)
        if p and p.get('media'):
            vals = v if isinstance(v, list) else [v]
            vals = [cli.upload(x)['id'] if isinstance(x, str) and os.path.isfile(x) else x for x in vals]
            v = vals if p.get('multiple') else vals[0]
        out[k] = v
    return out


def wait(jid, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = cli.call('GET', f'/api/jobs/{jid}')
        if j['status'] != 'running':
            return j
        time.sleep(6)
    return cli.call('GET', f'/api/jobs/{jid}')


def run(name, a):
    if name == 'credits':
        c = cli.call('GET', '/api/credits')['credits']
        return {'credits': c, 'usd': round(c * 0.005, 2)}
    if name == 'list_models':
        return [{k: m[k] for k in ('key', 'name', 'kind', 'blurb')}
                for m in cli.call('GET', '/api/models')['models'] if not a.get('kind') or m['kind'] == a['kind']]
    if name == 'describe_model':
        return cli.find_model(a['model'])
    if name == 'upload_file':
        return cli.upload(a['path'])
    if name == 'list_assets':
        return [{k: x.get(k) for k in ('id', 'kind', 'name', 'duration')} for x in cli.call('GET', '/api/assets')]
    if name in ('estimate', 'generate'):
        m = cli.find_model(a['model'])
        params = media_params(m, a.get('params') or {})
        for p in m['params']:
            if p['name'] not in params and p.get('default') is not None and not p.get('media'):
                params[p['name']] = p['default']
        e = cli.call('POST', '/api/estimate', {'model': m['key'], 'params': params})
        if name == 'estimate' or not a.get('confirm'):
            return {'needsConfirm': name == 'generate', 'estimate': e, 'params': params,
                    'message': 'Show this cost to the user. Call generate again with confirm=true once they agree.'}
        job = cli.call('POST', '/api/generate', {'model': m['key'], 'params': params, 'estCredits': e.get('credits')})
        return wait(job['id']) if a.get('wait') else job
    if name == 'get_job':
        return wait(a['id']) if a.get('wait') else cli.call('GET', f'/api/jobs/{a["id"]}')
    if name == 'list_jobs':
        return cli.call('GET', '/api/jobs')[:a.get('limit', 15)]
    if name == 'board_create':
        return cli.call('POST', '/api/boards/create', a['spec'])
    if name == 'board_list':
        return cli.call('GET', '/api/boards')
    if name == 'board_get':
        return cli.call('GET', f'/api/boards/{a["id"]}')
    if name == 'board_update':
        return cli.call('POST', f'/api/boards/{a["id"]}/update', {'scene': a.get('scene'), 'fields': a['fields']})
    if name == 'board_frames':
        return cli.call('POST', f'/api/boards/{a["id"]}/frames', {'all': bool(a.get('all'))})
    if name == 'board_frame':
        return cli.call('POST', f'/api/boards/{a["id"]}/frame', {'scene': a['scene']})
    if name == 'board_render':
        b = cli.call('GET', f'/api/boards/{a["id"]}')
        mode = a.get('mode') or b.get('video', {}).get('mode', 'std')
        if not a.get('confirm'):
            return {'needsConfirm': True, 'credits': b['_costs'][mode], 'mode': mode,
                    'message': 'Show this cost to the user and only confirm after they approve the storyboard.'}
        return cli.call('POST', f'/api/boards/{a["id"]}/render', {'mode': mode})
    if name == 'board_song':
        if not a.get('confirm'):
            return {'needsConfirm': True, 'credits': 12}
        return cli.call('POST', f'/api/boards/{a["id"]}/song', {})
    if name == 'board_assemble':
        return cli.call('POST', f'/api/boards/{a["id"]}/assemble', {})
    raise cli.StudioError(f'unknown tool {name}')


def slim(obj):
    """Board payloads carry cache fields nobody needs in context."""
    if isinstance(obj, dict):
        return {k: slim(v) for k, v in obj.items() if k not in ('urls', 'log')}
    if isinstance(obj, list):
        return [slim(x) for x in obj]
    return obj


def handle(msg):
    mid, method, params = msg.get('id'), msg.get('method'), msg.get('params') or {}
    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': params.get('protocolVersion', PROTOCOL),
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'somnei-studio', 'version': '0.3.0'},
            'instructions': 'Generate video, image and audio ads through kie.ai. Always estimate first and get the '
                            'user\'s OK before any call with confirm=true. Storyboards are reviewed by the user at '
                            'http://localhost:4950 (Storyboards tab); read their notes with board_get.'}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOLS}}
    if method == 'tools/call':
        try:
            res = slim(run(params['name'], params.get('arguments') or {}))
            return {'jsonrpc': '2.0', 'id': mid,
                    'result': {'content': [{'type': 'text', 'text': json.dumps(res, indent=1)}], 'isError': False}}
        except Exception as e:  # tool errors go back to the model, not the transport
            return {'jsonrpc': '2.0', 'id': mid,
                    'result': {'content': [{'type': 'text', 'text': f'Error: {e}'}], 'isError': True}}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if mid is None:
        return None  # notification
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'method not found: {method}'}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except Exception as e:
            reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(e)}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()

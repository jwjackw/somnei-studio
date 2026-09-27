"""Offline tests: no network, no credits. Run with  python -m unittest discover tests"""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
import mcp_server  # noqa: E402


def M(key):
    m = server.model_by_id(key)
    assert m, key
    return m


class Catalog(unittest.TestCase):
    def test_every_model_is_well_formed(self):
        kinds = {k['key'] for k in server.models()['kinds']}
        seen = set()
        for m in server.models()['models']:
            with self.subTest(model=m['key']):
                self.assertNotIn(m['key'], seen)
                seen.add(m['key'])
                self.assertIn(m['kind'], kinds)
                self.assertTrue(m['create']['path'].startswith('/api/v1/'))
                self.assertIn(m['create']['bodyStyle'], ('jobs_input', 'flat'))
                if m['create']['bodyStyle'] == 'jobs_input':
                    self.assertTrue(m['create'].get('model'), 'jobs endpoint needs a model id')
                if m['poll'] == 'custom':
                    self.assertIn('{taskId}', m['pollPath'])
                names = [p['name'] for p in m['params']]
                self.assertEqual(len(names), len(set(names)))
                for p in m['params']:
                    if 'default' in p and p.get('enum'):
                        self.assertIn(p['default'], p['enum'], p['name'])

    def test_every_price_table_covers_every_enum_combination(self):
        for m in server.models()['models']:
            c = m.get('cost')
            if not c or not c.get('by'):
                continue
            with self.subTest(model=m['key']):
                combos = [[]]
                for b in c['by']:
                    if b.startswith('@has:'):
                        vals = ['true', 'false']
                    else:
                        p = next(p for p in m['params'] if p['name'] == b)
                        vals = [str(v).lower() if isinstance(v, bool) else str(v)
                                for v in (p.get('enum') or [True, False])]
                    combos = [x + [v] for x in combos for v in vals]
                for combo in combos:
                    self.assertIn('|'.join(combo), c['rates'])


class Requests(unittest.TestCase):
    def test_jobs_body_nests_under_input(self):
        path, body = server.build_request(M('kling3'), {'prompt': 'hi', 'duration': '5', 'image_urls': ['u']})
        self.assertEqual(path, '/api/v1/jobs/createTask')
        self.assertEqual(body['model'], 'kling-3.0/video')
        self.assertEqual(body['input']['image_urls'], ['u'])
        self.assertEqual(body['input']['duration'], '5')  # Kling wants a string

    def test_flat_body_for_veo(self):
        path, body = server.build_request(M('veo3'), {'prompt': 'hi', 'model': 'veo3', 'imageUrls': ['a', 'b']})
        self.assertEqual(path, '/api/v1/veo/generate')
        self.assertEqual(body['imageUrls'], ['a', 'b'])
        self.assertNotIn('input', body)

    def test_model_switches_to_text_to_video_without_frame(self):
        _, body = server.build_request(M('wan27-i2v'), {'prompt': 'hi', 'duration': 5})
        self.assertEqual(body['model'], 'wan/2-7-text-to-video')
        _, body = server.build_request(M('wan27-i2v'), {'prompt': 'hi', 'first_frame_url': 'u'})
        self.assertEqual(body['model'], 'wan/2-7-image-to-video')

    def test_image_to_image_switch_and_drop(self):
        _, body = server.build_request(M('gpt-image-2'), {'prompt': 'hi', 'input_urls': ['u']})
        self.assertEqual(body['model'], 'gpt-image-2-image-to-image')
        _, body = server.build_request(M('minimax-h3'), {'prompt': 'hi', 'duration': 6, 'first_frame_url': 'u',
                                                         'aspect_ratio': '9:16'})
        self.assertNotIn('aspect_ratio', body['input'])  # MiniMax i2v rejects it

    def test_local_only_params_are_not_sent(self):
        _, body = server.build_request(M('kling-avatar'), {'image_url': 'i', 'audio_url': 'a', 'prompt': 'p',
                                                           'tier': 'pro'})
        self.assertEqual(body['model'], 'kling/ai-avatar-v1-pro')
        self.assertNotIn('tier', body['input'])

    def test_types_are_coerced(self):
        _, body = server.build_request(M('seedance25'), {'prompt': 'x', 'duration': '7', 'generate_audio': 'true'})
        self.assertEqual(body['input']['duration'], 7)
        self.assertIs(body['input']['generate_audio'], True)

    def test_empty_values_are_dropped(self):
        _, body = server.build_request(M('kling3'), {'prompt': 'x', 'image_urls': [], 'duration': ''})
        self.assertNotIn('image_urls', body['input'])
        self.assertNotIn('duration', body['input'])


class Costs(unittest.TestCase):
    def test_per_second_with_audio(self):
        self.assertEqual(server.estimate(M('kling3'), {'duration': '7', 'mode': 'pro', 'sound': True})['credits'], 189)

    def test_flat_by_setting(self):
        self.assertEqual(server.estimate(M('veo3'), {'model': 'veo3'})['credits'], 250)
        self.assertEqual(server.estimate(M('veo3'), {})['credits'], 60)  # default is Fast

    def test_has_video_discount(self):
        e = server.estimate(M('seedance25'), {'resolution': '720p', 'duration': 5, 'reference_video_urls': ['v']})
        self.assertEqual(e['credits'], 190)

    def test_duration_from_asset(self):
        assets = [{'id': 'a1', 'url': 'http://x/a.mp3', 'duration': 9.2}]
        self.assertEqual(server.estimate(M('omnihuman'), {'audio_url': 'http://x/a.mp3'}, assets)['credits'], 270)
        self.assertIsNone(server.estimate(M('omnihuman'), {'audio_url': 'zzz'}, assets)['credits'])

    def test_characters(self):
        self.assertEqual(server.estimate(M('tts'), {'text': 'x' * 2000})['credits'], 12)

    def test_unpriced(self):
        m = dict(M('kling3'), cost=None)
        self.assertIsNone(server.estimate(m, {})['credits'])


class Storyboard(unittest.TestCase):
    def test_clip_length_and_cost(self):
        b = {'video': {'model': 'kling3', 'mode': 'std'}}
        s = {'start': 0, 'end': 1.2}
        self.assertEqual(server.clip_seconds(s, 'kling3'), 3)  # Kling minimum
        self.assertEqual(server.clip_seconds({'start': 0, 'end': 4.1}, 'kling3'), 5)
        self.assertEqual(server.clip_cost(b, s, 'pro'), 54)
        self.assertEqual(server.clip_cost(b, dict(s, still=True)), 0)
        self.assertEqual(server.clip_cost(b, dict(s, clipModel='veo3')), 60)

    def test_captions_file(self):
        b = {'scenes': [{'start': 0, 'end': 1.5, 'line': '"Your Honor"'}, {'start': 1.5, 'end': 3, 'line': 'x',
                                                                           'noCaption': True}]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.ass')
            server.write_captions(b, p)
            with open(p, encoding='utf-8') as f:
                txt = f.read()
        self.assertIn('Dialogue: 0,0:00:00.00,0:00:01.50,Cap,,0,0,0,,Your Honor', txt)
        self.assertNotIn(',x\n', txt)
        self.assertIn('PlayResY: 1920', txt)


class Locks(unittest.TestCase):
    def test_frame_prompt_labels_and_locks_each_reference(self):
        refs = [{'label': 'Jess', 'role': 'character'}, {'label': 'Trimmer', 'role': 'product'}]
        p = server.frame_prompt({'style': 'soft 3d look'}, {'picture': 'Jess in court'}, refs)
        self.assertTrue(p.startswith('image references: image 1 = Jess; image 2 = Trimmer'))
        self.assertIn('image 1: reproduce this exact person', p)
        self.assertIn('image 2: reproduce this exact product', p)
        self.assertTrue(p.endswith('soft 3d look\n\nJess in court'))
        self.assertEqual(p, p.replace('IMAGE', 'image'))  # no capitalised instructions for Nano Banana

    def test_frame_prompt_without_refs_is_just_style_and_picture(self):
        self.assertEqual(server.frame_prompt({}, {'picture': 'a room'}, []), 'a room')

    def test_clip_lock_default_override_and_off(self):
        self.assertIn('one continuous shot', server.clip_prompt({}, {'motion': 'she waves'}))
        self.assertTrue(server.clip_prompt({'clipLock': 'camera locked.'}, {'motion': 'x'}).endswith('camera locked.'))
        self.assertEqual(server.clip_prompt({}, {'motion': 'x', 'lock': ''}), 'x')


class SongTiming(unittest.TestCase):
    WORDS = [['[Intro]\nHey', 2.0, 2.3], ['guys.', 2.4, 2.8], ["It's", 3.0, 3.2], ['me.', 3.3, 3.6],
             ['[Verse 1]\nI’m', 5.0, 5.2], ['sorry', 5.3, 5.8], ['for', 5.9, 6.0], ['the', 6.1, 6.2],
             ['cuts.', 6.3, 6.9], ["I'm", 8.0, 8.2], ['sorry', 8.3, 8.8], ['for', 8.9, 9.0], ['the', 9.1, 9.2],
             ['bumps.', 9.3, 9.9]]

    def board(self):
        return {'scenes': [{'n': 1, 'line': "Hey guys. It's me."}, {'n': 2, 'line': "I'm sorry for the cuts."},
                           {'n': 3, 'line': "I'm sorry for the bumps."},
                           {'n': 4, 'line': 'Break up with your razor.', 'still': True}]}

    def test_scenes_cut_on_their_sung_line(self):
        b = self.board()
        missed = server.align_scenes(b, self.WORDS, duration=30)
        self.assertEqual(missed, [])
        self.assertAlmostEqual(b['song']['offset'], 1.75)       # first word lands 0.25s into the video
        s = b['scenes']
        self.assertEqual(s[0]['start'], 0.0)
        self.assertAlmostEqual(s[1]['start'], 5.0 - 1.75 - 0.12, places=2)
        self.assertAlmostEqual(s[2]['start'], 8.0 - 1.75 - 0.12, places=2)  # repeated words don't confuse it
        self.assertEqual(s[0]['end'], s[1]['start'])             # scenes are contiguous
        self.assertAlmostEqual(s[3]['start'], 9.9 - 1.75 + 0.15, places=2)  # unsung end card after last line
        self.assertAlmostEqual(s[3]['end'] - s[3]['start'], 2.5, places=2)

    def test_suno_multiword_tokens_do_not_shift_later_scenes(self):
        # real Suno output from 2026-09-26: "in 20" and "is 60%" came back as single words
        words = [['[Intro]\nPool', 1.1, 1.4], ['party', 1.5, 1.9], ['in 20', 2.0, 2.5], ['minutes!', 2.6, 3.1],
                 ['[Verse 1]\nAnd', 3.3, 3.5], ['my', 3.6, 3.8], ['legs', 3.9, 4.2], ['are', 4.3, 4.5],
                 ['not', 4.6, 4.8], ['ready.', 4.9, 5.4], ['And', 17.0, 17.2], ['I', 17.3, 17.4],
                 ['make', 17.5, 18.0], ['it', 18.5, 18.8], ['on', 18.9, 19.3], ['time!', 19.4, 20.0],
                 ['[Outro]\nThe', 28.1, 28.2], ['Peach', 28.3, 28.5], ['is 60%', 28.6, 29.9], ['off', 30.0, 30.1]]
        b = {'scenes': [{'n': 1, 'line': 'Pool party in 20 minutes!'}, {'n': 2, 'line': 'And my legs are not ready.'},
                        {'n': 3, 'line': 'And I make it on time!'}, {'n': 4, 'line': 'The Peach is 60% off.'}]}
        self.assertEqual(server.align_scenes(b, words, duration=40), [])
        self.assertAlmostEqual(b['scenes'][1]['start'], 3.3 - 0.85 - 0.12, places=2)   # not the chorus "And"
        self.assertAlmostEqual(b['scenes'][2]['start'], 17.0 - 0.85 - 0.12, places=2)
        self.assertAlmostEqual(b['scenes'][3]['start'], 28.1 - 0.85 - 0.12, places=2)

    def test_unmatched_lines_are_reported(self):
        b = self.board()
        b['scenes'][2]['line'] = 'a line suno never sang'
        self.assertEqual(server.align_scenes(b, self.WORDS), [3])

    def test_lipsync_scene_costs_per_second_of_audio(self):
        b = {'video': {'model': 'kling3', 'mode': 'std'}}
        s = {'start': 0, 'end': 2.2, 'clipModel': 'omnihuman'}
        self.assertEqual(server.clip_seconds(s, 'omnihuman'), 3)
        self.assertEqual(server.clip_cost(b, s, 'std'), 81)
        self.assertEqual(server.clip_cost(b, dict(s, clipModel='kling-avatar'), 'pro'), 48)


class MCP(unittest.TestCase):
    def test_handshake_and_tool_schemas(self):
        r = mcp_server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        self.assertEqual(r['result']['serverInfo']['name'], 'somnei-studio')
        tools = mcp_server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools']
        for t in tools:
            with self.subTest(tool=t['name']):
                self.assertEqual(t['inputSchema']['type'], 'object')
                for req in t['inputSchema']['required']:
                    self.assertIn(req, t['inputSchema']['properties'])
        self.assertIsNone(mcp_server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_spending_tools_demand_confirmation(self):
        for t in mcp_server.TOOLS:
            if t['name'] in ('generate', 'board_render', 'board_song'):
                self.assertIn('confirm', t['inputSchema']['properties'])


if __name__ == '__main__':
    unittest.main()

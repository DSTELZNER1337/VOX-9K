"""Model-free regression tests. Run using the existing .venv interpreter."""
import asyncio
import importlib.util
import json
import pathlib
import struct
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, filename, mocks):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    previous = {key: sys.modules.get(key) for key in mocks}
    sys.modules.update(mocks)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return module


kokoro = types.ModuleType('pykokoro')
kokoro.GenerationConfig = lambda **kw: types.SimpleNamespace(**kw)
kokoro.SynthesisConfig = lambda **kw: types.SimpleNamespace(**kw)
kokoro.KokoroSynthesizer = Mock()
server = load('vox_test_server', 'server.py', {'pykokoro': kokoro})
torch = types.ModuleType('torch')
torch.cuda = types.SimpleNamespace(is_available=lambda: False)
torch.__version__ = 'mock'
torch.bfloat16 = 'mock-bfloat16'
sidecar = load('vox_test_sidecar', 'qwen_fast_server.py', {'torch': torch})
import numpy as np
from fastapi.testclient import TestClient


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.providers = patch.object(server, 'available_onnx_providers', return_value=['CPUExecutionProvider'])
        self.providers.start()
        assets = patch.object(server, 'installed_kokoro_assets', return_value={})
        assets.start()
        self.addCleanup(assets.stop)
        self.addCleanup(self.providers.stop)

    def post(self, **kw):
        return self.client.post('/tts', json={'text': 'Hello.', **kw})

    def test_static_routes(self):
        for path in ['/', '/background.png']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_system_info(self):
        with patch.object(server, 'qwen_sidecar_health', return_value=None):
            self.assertEqual(self.client.get('/system-info').status_code, 200)

    def test_empty_text(self):
        self.assertEqual(self.post(text='  ').status_code, 400)

    def test_text_limit(self):
        self.assertEqual(self.post(text='a' * 3001).status_code, 400)

    def test_invalid_compute(self):
        self.assertEqual(self.post(compute='metal').status_code, 400)

    def test_unavailable_compute(self):
        self.assertEqual(self.post(compute='cuda').status_code, 400)

    def test_invalid_engine(self):
        self.assertEqual(self.post(engine='other').status_code, 400)

    def test_qwen_redirect_explanation(self):
        self.assertEqual(self.post(engine='qwen').status_code, 400)

    def test_invalid_voice(self):
        with patch.object(server, 'synthesize_kokoro') as synth:
            self.assertEqual(self.post(voice='../not-a-voice').status_code, 400)
            synth.assert_not_called()

    def test_non_object_json(self):
        for data in [[], ['hello'], 123, 'hello']:
            self.assertEqual(self.client.post('/tts', json=data).status_code, 400)

    def test_non_string_text(self):
        self.assertEqual(self.post(text=['hello']).status_code, 400)

    def test_body_limit(self):
        self.assertEqual(self.client.post('/tts', data=b'x' * 70000, content_type='application/json').status_code, 413)

    def test_foreign_origin(self):
        self.assertEqual(self.client.post('/tts', json={'text': 'hello'}, headers={'Origin': 'https://unrelated.example'}).status_code, 403)

    def test_rebound_host(self):
        self.assertEqual(self.client.get('/', headers={'Host': 'attacker.example:5000'}).status_code, 403)

    def test_failure_redacts_details(self):
        with patch.object(server, 'synthesize_kokoro', side_effect=RuntimeError('PRIVATE/PATH')):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('PRIVATE', response.get_data(as_text=True))

    def test_wav_response(self):
        with patch.object(server, 'synthesize_kokoro', return_value=b'RIFFfake'):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'audio/wav')
        response.close()

    def test_provider_detection_exception(self):
        self.providers.stop()
        with patch.object(server, 'ort', types.SimpleNamespace(get_available_providers=Mock(side_effect=RuntimeError))):
            self.assertEqual(server.available_onnx_providers(), [])

    def test_explicit_provider_configuration(self):
        with patch.object(server, 'KokoroSynthesizer', return_value=Mock()) as factory:
            server.create_kokoro_synthesizer('cpu')
        self.assertEqual(factory.call_args.args[0].provider, 'cpu')

    def test_engine_reuse(self):
        with patch.dict(server.kokoro_synthesizers, {}, clear=True), patch.object(server, 'create_kokoro_synthesizer', return_value=object()) as create:
            self.assertIs(server.get_kokoro_synthesizer('cpu'), server.get_kokoro_synthesizer('cpu'))
            create.assert_called_once()

    def test_temp_cleanup_after_save_failure(self):
        synth = Mock()
        synth.synthesize_text.return_value.save_wav.side_effect = RuntimeError('disk full')
        before = set(server.TEMP_DIR.iterdir())
        with patch.object(server, 'get_kokoro_synthesizer', return_value=synth):
            with self.assertRaises(RuntimeError):
                server.synthesize_kokoro('hello', 'af_sarah', 'cpu')
        self.assertEqual(set(server.TEMP_DIR.iterdir()), before)

    def test_sidecar_failure(self):
        import urllib.error
        with patch.object(server.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')):
            self.assertIsNone(server.qwen_sidecar_health())

    def test_unrelated_service_is_not_sidecar(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"status":"ok"}'
        with patch.object(server.urllib.request, 'urlopen', return_value=response):
            self.assertIsNone(server.qwen_sidecar_health())

    def test_sidecar_readiness_identity(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'service': 'vox-9k-qwen', 'model': server.QWEN_MODEL_ID, 'status': 'warming'}).encode()
        with patch.object(server.urllib.request, 'urlopen', return_value=response):
            self.assertEqual(server.qwen_sidecar_health()['status'], 'warming')

    def test_owned_sidecar_pipe_closed_and_reaped(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(server, 'qwen_sidecar_process', process), patch.object(server, 'qwen_sidecar_owned', True):
            server.stop_qwen_sidecar()
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once()

    def test_unowned_sidecar_is_preserved(self):
        process = Mock()
        with patch.object(server, 'qwen_sidecar_process', process), patch.object(server, 'qwen_sidecar_owned', False):
            server.stop_qwen_sidecar()
        process.terminate.assert_not_called()
        process.stdin.close.assert_not_called()

    def test_failed_kokoro_warmup_closes_model(self):
        synth = Mock()
        synth.synthesize_text.side_effect = RuntimeError('warmup failed')
        with patch.object(server, 'KokoroSynthesizer', return_value=synth):
            with self.assertRaises(RuntimeError):
                server.create_kokoro_synthesizer('cpu')
        synth.close.assert_called_once()

    def test_successful_temp_wav_cleanup(self):
        synth = Mock()
        synth.synthesize_text.return_value.save_wav.side_effect = lambda path: pathlib.Path(path).write_bytes(b'RIFF')
        before = set(server.TEMP_DIR.iterdir())
        with patch.object(server, 'get_kokoro_synthesizer', return_value=synth):
            self.assertEqual(server.synthesize_kokoro('hello', 'af_sarah', 'cpu'), b'RIFF')
        self.assertEqual(set(server.TEMP_DIR.iterdir()), before)

    def test_sidecar_shutdown_timeout_terminates_and_reaps(self):
        import subprocess
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired('mock', 3), None]
        with patch.object(server, 'qwen_sidecar_process', process), patch.object(server, 'qwen_sidecar_owned', True):
            server.stop_qwen_sidecar()
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)


async def collect(response):
    return [part async for part in response.body_iterator]


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(sidecar.app, base_url='http://127.0.0.1:5001')  # No lifespan/model load.
        sidecar._model = None
        sidecar.update_state(status='ready', error=None)
        sidecar._current_generation.update(request_id=None, cancel_event=None)
        if hasattr(sidecar, '_cancelled_requests'):
            sidecar._cancelled_requests.clear()
            sidecar._client_sequences.clear()

    def tearDown(self):
        sidecar.cancel_generation()
        sidecar._model = None
        self.client.close()

    def fake_model(self, fail=False):
        closed = threading.Event()
        def generate(**kw):
            try:
                if fail:
                    raise RuntimeError('PRIVATE/PATH')
                yield np.array([0.0, .25, -.25], dtype='<f4'), 24000, {}
                yield np.array([.5], dtype='<f4'), 24000, {}
            finally:
                closed.set()
        sidecar._model = types.SimpleNamespace(generate_custom_voice_streaming=generate)
        return closed

    def test_no_model_returns_503(self):
        self.assertEqual(self.client.post('/stream', json={'text': 'hello'}).status_code, 503)

    def test_invalid_requests(self):
        for body in [{'text': ''}, {'text': 'a' * 3001}, {'text': 'hi', 'speaker': 'bad'}, {'text': 'hi', 'chunk_size': 25}]:
            self.assertEqual(self.client.post('/stream', json=body).status_code, 400)

    def test_foreign_origin_cancel(self):
        sidecar.begin_generation('owner')
        response = self.client.post('/cancel', json={'request_id': 'owner'}, headers={'Origin': 'https://unrelated.example'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(sidecar._current_generation['cancel_event'].is_set())

    def test_rebound_host(self):
        self.assertEqual(self.client.get('/health', headers={'Host': 'attacker.example:5001'}).status_code, 403)

    def test_cancel_by_id(self):
        event = sidecar.begin_generation('new')
        self.assertFalse(sidecar.cancel_generation('old'))
        self.assertFalse(event.is_set())
        self.assertTrue(sidecar.cancel_generation('new'))
        self.assertTrue(event.is_set())

    def test_unscoped_cancel_rejected(self):
        self.assertIn(self.client.post('/cancel', json={}).status_code, (400, 422))

    def test_new_generation_supersedes_old(self):
        first = sidecar.begin_generation('first')
        second = sidecar.begin_generation('second')
        self.assertTrue(first.is_set())
        sidecar.finish_generation('first', first)
        self.assertIs(sidecar._current_generation['cancel_event'], second)

    def test_frames_and_cleanup(self):
        closed = self.fake_model()
        parts = asyncio.run(collect(sidecar.stream(sidecar.StreamRequest(text='hello', request_id='x'))))
        self.assertEqual([struct.unpack('<IIII', p[:16]) for p in parts], [(12, 24000, 0, 0), (4, 24000, 1, 0), (0, 24000, 2, 1)])
        self.assertTrue(closed.is_set())
        self.assertIsNone(sidecar._current_generation['request_id'])
        self.assertTrue(sidecar._model_lock.acquire(blocking=False))
        sidecar._model_lock.release()

    def test_error_frame_redacts_details(self):
        self.fake_model(fail=True)
        parts = asyncio.run(collect(sidecar.stream(sidecar.StreamRequest(text='hello', request_id='x'))))
        self.assertEqual(struct.unpack('<IIII', parts[0][:16])[3], 2)
        self.assertNotIn(b'PRIVATE', parts[0])

    def test_cancelled_before_iteration(self):
        self.fake_model()
        response = sidecar.stream(sidecar.StreamRequest(text='hi', request_id='old'))
        newer = sidecar.begin_generation('new')
        self.assertEqual(asyncio.run(collect(response)), [])
        self.assertIs(sidecar._current_generation['cancel_event'], newer)

    def test_disconnect_closes_model_iterator(self):
        closed = self.fake_model()
        response = sidecar.stream(sidecar.StreamRequest(text='hello', request_id='x'))
        async def disconnect():
            iterator = response.body_iterator
            await anext(iterator)
            await iterator.aclose()
        asyncio.run(disconnect())
        self.assertTrue(closed.is_set())
        self.assertIsNone(sidecar._current_generation['request_id'])

    def test_cleanup_runs_while_holding_model_lock(self):
        locked = []
        def generate(**kw):
            try:
                yield np.zeros(2, dtype='<f4'), 24000, {}
                yield np.zeros(2, dtype='<f4'), 24000, {}
            finally:
                acquired = sidecar._model_lock.acquire(blocking=False)
                locked.append(not acquired)
                if acquired:
                    sidecar._model_lock.release()
        sidecar._model = types.SimpleNamespace(generate_custom_voice_streaming=generate)
        response = sidecar.stream(sidecar.StreamRequest(text='hi', request_id='x'))
        async def cancel_after_first():
            iterator = response.body_iterator
            await anext(iterator)
            sidecar.cancel_generation('x')
            async for _ in iterator:
                pass
        asyncio.run(cancel_after_first())
        self.assertEqual(locked, [True])

    def test_cancel_does_not_start_another_generation_step(self):
        advanced = []
        def generate(**kw):
            yield np.zeros(2, dtype='<f4'), 24000, {}
            advanced.append(True)
            yield np.zeros(2, dtype='<f4'), 24000, {}
        sidecar._model = types.SimpleNamespace(generate_custom_voice_streaming=generate)
        response = sidecar.stream(sidecar.StreamRequest(text='hi', request_id='x'))
        async def run():
            iterator = response.body_iterator
            await anext(iterator)
            sidecar.cancel_generation('x')
            async for _ in iterator:
                pass
        asyncio.run(run())
        self.assertEqual(advanced, [])

    def test_cancel_arriving_before_stream_is_remembered(self):
        sidecar.cancel_generation('client:2:0')
        self.assertTrue(sidecar.begin_generation('client:2:0').is_set())

    def test_delayed_older_read_cannot_supersede_new_read(self):
        current = sidecar.begin_generation('client:3:0')
        stale = sidecar.begin_generation('client:2:9')
        self.assertTrue(stale.is_set())
        self.assertFalse(current.is_set())

    def test_cancelled_waiter_exits_without_model_lock(self):
        self.fake_model()
        response = sidecar.stream(sidecar.StreamRequest(text='hi', request_id='waiting'))
        sidecar._model_lock.acquire()
        try:
            async def run():
                task = asyncio.create_task(collect(response))
                await asyncio.sleep(.02)
                sidecar.cancel_generation('waiting')
                self.assertEqual(await asyncio.wait_for(task, timeout=1), [])
            asyncio.run(run())
        finally:
            sidecar._model_lock.release()

    def test_oversized_sidecar_body(self):
        self.assertEqual(self.client.post('/stream', content=b'x' * 70000, headers={'Content-Type': 'application/json'}).status_code, 413)

    def test_invalid_language(self):
        self.assertEqual(self.client.post('/stream', json={'text': 'hi', 'language': 'Unknown'}).status_code, 400)

    def test_model_and_graphs_reused_between_reads(self):
        self.fake_model()
        model = sidecar._model
        model.warmup = Mock()
        factory = Mock()
        factory.from_pretrained.return_value = model
        with patch.dict(sys.modules, {'faster_qwen3_tts': types.SimpleNamespace(FasterQwen3TTS=factory)}):
            sidecar.load_model()
            for request_id in ['reuse1', 'reuse2']:
                asyncio.run(collect(sidecar.stream(sidecar.StreamRequest(text='hi', request_id=request_id))))
        self.assertIs(sidecar._model, model)
        factory.from_pretrained.assert_called_once()
        model.warmup.assert_called_once_with(prefill_len=100)

    def test_model_init_failure_is_recoverable_503(self):
        factory = Mock()
        factory.from_pretrained.side_effect = RuntimeError('PRIVATE/PATH')
        with patch.dict(sys.modules, {'faster_qwen3_tts': types.SimpleNamespace(FasterQwen3TTS=factory)}):
            sidecar.load_model()
        response=self.client.post('/stream', json={'text': 'hello'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('PRIVATE',response.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)

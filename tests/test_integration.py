"""Actual localhost HTTP with synthetic inference; no model loading."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import uvicorn
from werkzeug.serving import make_server
from test_backend import server, sidecar


class LocalHttpIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask = make_server('127.0.0.1', 0, server.app)
        cls.flask_thread = threading.Thread(target=cls.flask.serve_forever, daemon=True)
        cls.flask_thread.start()
        cls.main_url = f'http://127.0.0.1:{cls.flask.server_port}'
        cls.sock = socket.socket()
        cls.sock.bind(('127.0.0.1', 0))
        cls.sidecar_url = f'http://127.0.0.1:{cls.sock.getsockname()[1]}'
        cls.uvicorn = uvicorn.Server(uvicorn.Config(sidecar.app, lifespan='off', log_level='error'))
        cls.uvicorn_thread = threading.Thread(target=cls.uvicorn.run, kwargs={'sockets': [cls.sock]}, daemon=True)
        cls.uvicorn_thread.start()
        deadline = time.monotonic() + 5
        while not cls.uvicorn.started and time.monotonic() < deadline:
            time.sleep(.01)
        if not cls.uvicorn.started:
            raise RuntimeError('Synthetic sidecar did not start')

    @classmethod
    def tearDownClass(cls):
        cls.flask.shutdown()
        cls.flask.server_close()
        cls.flask_thread.join(3)
        cls.uvicorn.should_exit = True
        cls.uvicorn_thread.join(3)
        cls.sock.close()
        if cls.uvicorn_thread.is_alive():
            raise RuntimeError('Synthetic HTTP service did not terminate')

    def test_main_page_and_script(self):
        for path in ['/', '/vox_helpers.js']:
            self.assertEqual(httpx.get(self.main_url + path, headers={'Host': 'localhost:5000'}).status_code, 200)

    def test_main_validation_over_http(self):
        response = httpx.post(self.main_url + '/tts', headers={'Host': 'localhost:5000'}, json={'text': ''})
        self.assertEqual(response.status_code, 400)

    def test_cross_site_main_denied(self):
        response = httpx.post(self.main_url + '/tts', headers={'Host': 'localhost:5000', 'Origin': 'https://unrelated.example'}, json={'text': 'hello'})
        self.assertEqual(response.status_code, 403)

    def test_sidecar_health_over_http(self):
        response = httpx.get(self.sidecar_url + '/health', headers={'Host': 'localhost:5001'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['service'], 'vox-9k-qwen')

    def test_sidecar_cors_preflight(self):
        response = httpx.options(self.sidecar_url + '/stream', headers={'Host': 'localhost:5001', 'Origin': 'http://127.0.0.1:5000', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Content-Type'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://127.0.0.1:5000')

    def test_stream_and_concurrent_cancel(self):
        closed, step = threading.Event(), threading.Event()
        def generate(**kw):
            try:
                yield np.zeros(128, dtype='<f4'), 24000, {}
                step.wait(3)
                yield np.zeros(128, dtype='<f4'), 24000, {}
            finally:
                closed.set()
        import types
        with patch.object(sidecar, '_model', types.SimpleNamespace(generate_custom_voice_streaming=generate)):
            sidecar.update_state(status='ready')
            with httpx.stream('POST', self.sidecar_url + '/stream', headers={'Host': 'localhost:5001'}, json={'text':'hello', 'request_id':'http-cancel'}, timeout=5) as response:
                parts = response.iter_raw()
                self.assertEqual(len(next(parts)), 528)
                result = httpx.post(self.sidecar_url + '/cancel', headers={'Host': 'localhost:5001'}, json={'request_id':'http-cancel'})
                self.assertTrue(result.json()['cancelled'])
                step.set()
                self.assertEqual(list(parts), [])
            self.assertTrue(closed.wait(2))

    def test_disconnect_releases_lock(self):
        closed = threading.Event()
        def generate(**kw):
            try:
                for _ in range(100):
                    time.sleep(.01)
                    yield np.zeros(128, dtype='<f4'), 24000, {}
            finally:
                closed.set()
        import types
        with patch.object(sidecar, '_model', types.SimpleNamespace(generate_custom_voice_streaming=generate)):
            sidecar.update_state(status='ready')
            with httpx.stream('POST', self.sidecar_url + '/stream', headers={'Host': 'localhost:5001'}, json={'text':'hello', 'request_id':'http-disconnect'}, timeout=5) as response:
                next(response.iter_raw())
            self.assertTrue(closed.wait(2))
            deadline = time.monotonic() + 2
            while sidecar._model_lock.locked() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(sidecar._model_lock.locked())
            self.assertIsNone(sidecar._current_generation['request_id'])

    def test_parent_pipe_eof_terminates_owned_child(self):
        # Exercise the actual watcher in a separate process without entering lifespan.
        code = f'import sys; sys.path.insert(0,{str(pathlib.Path(__file__).parent)!r}); from test_backend import sidecar; print("watching",flush=True); sidecar.watch_parent_pipe()'
        process = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(process.stdout.readline().strip(), b'watching')
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(3)
            process.stdout.close()
            process.stderr.close()

    def test_windows_cli_launch_without_models(self):
        probe=socket.socket()
        try:
            probe.bind(('127.0.0.1',5000))
        except OSError:
            self.skipTest('Port 5000 already in use; existing service preserved')
        finally:
            probe.close()
        root=pathlib.Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env.update(VOX_SKIP_WARMUP='1',VOX_DISABLE_QWEN='1',PYTHONDONTWRITEBYTECODE='1')
        log_path=root/'audit'/'cli-smoke.txt'
        with log_path.open('w') as log:
            process=subprocess.Popen([sys.executable,'server.py'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+10
                response=None
                while time.monotonic()<deadline and process.poll() is None:
                    try:
                        response=httpx.get('http://127.0.0.1:5000/',timeout=.3)
                        break
                    except httpx.TransportError:
                        time.sleep(.05)
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code,200)
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Headless launcher lifecycle tests; never import pywebview or neural models."""
from pathlib import Path
import json
import subprocess
import tempfile
import threading
import types
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop

class DesktopServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/"temp")
        self.addCleanup(self.temp.cleanup)
        self.base=patch.object(desktop,"BASE_DIR",Path(self.temp.name));self.base.start();self.addCleanup(self.base.stop)
        self.process=Mock();self.process.poll.return_value=None
        self.spawn=patch.object(desktop.subprocess,"Popen",return_value=self.process).start();self.addCleanup(patch.stopall)
        self.services=desktop.DesktopServices(startup_timeout=1);self.addCleanup(self.services.close)
    def health(self,instance=None):
        return {"service":"vox-9k","api_version":1,"instance_id":instance or self.services.instance_id}
    def test_external_service_reused_without_spawn(self):
        with patch.object(desktop,"application_health",return_value=self.health("external")):
            self.assertEqual(self.services.connect(),desktop.APP_URL)
        self.services.close();self.spawn.assert_not_called();self.process.terminate.assert_not_called()
    def test_unrelated_port_conflict_is_not_stopped(self):
        with patch.object(desktop,"application_health",return_value=None),patch.object(desktop,"port_in_use",return_value=True):
            with self.assertRaisesRegex(desktop.DesktopStartupError,"Port 5000"):
                self.services.connect()
        self.spawn.assert_not_called()
    def test_owned_service_waits_for_matching_identity(self):
        with patch.object(desktop,"application_health",side_effect=[None,None,self.health()]),patch.object(desktop,"port_in_use",return_value=False):
            self.assertEqual(self.services.connect(),desktop.APP_URL)
        kwargs=self.spawn.call_args.kwargs
        self.assertEqual(kwargs["env"]["VOX_INSTANCE_ID"],self.services.instance_id)
        self.assertEqual(kwargs["env"]["VOX_DESKTOP_PARENT_PIPE"],"1")
        self.assertEqual(self.spawn.call_args.args[0][-1],str(Path(self.temp.name)/"server.py"))
    def test_port_acquired_by_another_instance_fails_safely(self):
        with patch.object(desktop,"application_health",side_effect=[None,self.health("other")]),patch.object(desktop,"port_in_use",return_value=False):
            with self.assertRaisesRegex(desktop.DesktopStartupError,"Another VOX-9K"):
                self.services.connect()
        self.services.close();self.process.stdin.close.assert_called_once();self.process.wait.assert_called_once()
    def test_startup_process_failure(self):
        self.process.poll.return_value=2
        with patch.object(desktop,"application_health",return_value=None),patch.object(desktop,"port_in_use",return_value=False):
            with self.assertRaisesRegex(desktop.DesktopStartupError,"exited"):
                self.services.connect()
        self.services.close();self.process.stdin.close.assert_called_once()
    def test_readiness_timeout(self):
        self.services.startup_timeout=0
        with patch.object(desktop,"application_health",return_value=None),patch.object(desktop,"port_in_use",return_value=False):
            with self.assertRaisesRegex(desktop.DesktopStartupError,"ready in time"):
                self.services.connect()
    def test_close_before_start_never_spawns(self):
        self.services.close()
        with self.assertRaises(desktop.DesktopStartupError):self.services.connect()
        self.spawn.assert_not_called()
    def test_close_is_idempotent_and_reaps_owned_process(self):
        self.services.process=self.process
        self.services.close();self.services.close()
        self.process.stdin.close.assert_called_once();self.process.wait.assert_called_once();self.process.terminate.assert_not_called()
    def test_shutdown_escalates_only_owned_process(self):
        self.services.process=self.process
        self.process.wait.side_effect=[subprocess.TimeoutExpired("owned",7),subprocess.TimeoutExpired("owned",3),None]
        self.services.close()
        self.process.terminate.assert_called_once();self.process.kill.assert_called_once();self.assertEqual(self.process.wait.call_count,3)
    def test_spawn_failure_closes_log(self):
        self.spawn.side_effect=OSError("spawn failure")
        with patch.object(desktop,"application_health",return_value=None),patch.object(desktop,"port_in_use",return_value=False):
            with self.assertRaises(OSError):self.services.connect()
        self.assertIsNone(self.services._log)

class Event:
    def __init__(self):self.handlers=[]
    def __iadd__(self,handler):self.handlers.append(handler);return self
    def fire(self):
        for handler in self.handlers:handler()

class DesktopWindowTests(unittest.TestCase):
    def setUp(self):
        self.window=Mock();self.window.events=types.SimpleNamespace(closed=Event())
        self.webview=Mock();self.webview.create_window.return_value=self.window
        self.services=Mock();self.services.closed=threading.Event();self.services.connect.return_value=desktop.APP_URL
        self.services.close.side_effect=self.services.closed.set
        self.webview.start.side_effect=lambda callback,**kwargs:(callback(),self.window.events.closed.fire())
    def test_window_reuses_ui_and_close_handler(self):
        self.assertEqual(desktop.main(self.webview,self.services),0)
        self.window.load_url.assert_called_once_with(desktop.APP_URL)
        self.assertEqual(self.webview.create_window.call_args.args[0],"VOX-9K")
        self.assertTrue(self.webview.create_window.call_args.kwargs["resizable"])
        self.assertEqual(self.webview.start.call_args.kwargs["gui"],"edgechromium")
        self.assertGreaterEqual(self.services.close.call_count,1)
    def test_failed_startup_shows_safe_error_and_cleans_up(self):
        self.services.connect.side_effect=RuntimeError("<unsafe>")
        self.assertEqual(desktop.main(self.webview,self.services),1)
        self.assertIn("&lt;unsafe&gt;",self.window.load_html.call_args.args[0]);self.window.load_url.assert_not_called()
    def test_window_creation_failure_cleans_up(self):
        self.webview.create_window.side_effect=RuntimeError("GUI failure")
        self.assertEqual(desktop.main(self.webview,self.services),1);self.services.close.assert_called()
    def test_renderer_failure_cleans_up(self):
        self.webview.start.side_effect=RuntimeError("WebView2 missing")
        self.assertEqual(desktop.main(self.webview,self.services),1);self.services.close.assert_called()
    def test_missing_optional_dependency_does_not_start_service(self):
        with patch.object(desktop.importlib,"import_module",side_effect=ImportError):
            self.assertEqual(desktop.main(services=self.services),1)
        self.services.connect.assert_not_called()
    def test_closed_window_does_not_navigate(self):
        self.services.closed.set();self.assertEqual(desktop.main(self.webview,self.services),0);self.window.load_url.assert_not_called()

class DesktopHealthTests(unittest.TestCase):
    def response(self,data):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps(data).encode();return response
    def test_health_checks_service_and_protocol(self):
        for data,valid in [({"service":"vox-9k","api_version":1,"instance_id":"x"},True),({"status":"ok"},False),({"service":"other","api_version":1,"instance_id":"x"},False)]:
            with patch.object(desktop.urllib.request,"urlopen",return_value=self.response(data)):
                self.assertEqual(desktop.application_health() is not None,valid)
    def test_health_transport_failure(self):
        with patch.object(desktop.urllib.request,"urlopen",side_effect=OSError):self.assertIsNone(desktop.application_health())

if __name__=="__main__":unittest.main(verbosity=2)

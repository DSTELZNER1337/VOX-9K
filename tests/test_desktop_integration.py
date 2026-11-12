"""Real desktop service ownership without a GUI or model initialization."""
from pathlib import Path
import os,socket,sys,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop

class DesktopProcessIntegrationTests(unittest.TestCase):
    def setUp(self):
        if desktop.port_in_use():self.skipTest('Port 5000 occupied; existing service preserved')
        env=patch.dict(os.environ,{"VOX_SKIP_WARMUP":"1","VOX_DISABLE_QWEN":"1","PYTHONDONTWRITEBYTECODE":"1"})
        env.start();self.addCleanup(env.stop)
        self.owner=desktop.DesktopServices(startup_timeout=15);self.addCleanup(self.owner.close)
    def assert_stopped(self):
        deadline=time.monotonic()+5
        while desktop.application_health(timeout=.2) is not None and time.monotonic()<deadline:time.sleep(.05)
        self.assertIsNone(desktop.application_health(timeout=.2))
    def test_owned_flask_exits_on_close(self):
        self.assertEqual(self.owner.connect(),desktop.APP_URL)
        process=self.owner.process
        self.assertEqual(desktop.application_health()["instance_id"],self.owner.instance_id)
        self.owner.close();self.assertIsNotNone(process.poll());self.assert_stopped()
    def test_reused_external_flask_survives_window_close(self):
        self.owner.connect()
        external=desktop.DesktopServices();self.addCleanup(external.close)
        external.connect();self.assertIsNone(external.process);external.close()
        self.assertEqual(desktop.application_health()["instance_id"],self.owner.instance_id)
        self.owner.close();self.assert_stopped()

if __name__=='__main__':unittest.main(verbosity=2)

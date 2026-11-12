"""Model-free regression tests for installed-only Kokoro resolution."""
import sys,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from test_backend import server

class NotInstalledError(Exception): pass

class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.factory=Mock()
        self.modules=patch.dict(sys.modules,{"onnxvoice":types.SimpleNamespace(OnnxVoice=self.factory),"onnxvoice.errors":types.SimpleNamespace(NotInstalledError=NotInstalledError)})
        self.modules.start();self.addCleanup(self.modules.stop)
    def test_installed_artifacts_used_without_catalog(self):
        self.factory.return_value.resolve.return_value.artifact_path.side_effect=lambda role:Path(role)
        self.assertEqual(server.installed_kokoro_assets(),{"model_path":Path("model"),"voices_path":Path("voices"),"model_config_path":Path("vocab")})
        self.factory.assert_called_once_with(cache_dir=server.KOKORO_CACHE_DIR,offline=True)
        self.factory.return_value.resolve.assert_called_once_with("kokoro:v1.0",quality="fp32",distribution="github-model-files-v1.0-timestamped-r4")
    def test_missing_installation_preserves_bootstrap(self):
        self.factory.return_value.resolve.side_effect=NotInstalledError("missing")
        self.assertEqual(server.installed_kokoro_assets(),{})
    def test_corruption_is_not_hidden_by_download_fallback(self):
        self.factory.return_value.resolve.side_effect=ValueError("checksum mismatch")
        with self.assertRaises(ValueError):server.installed_kokoro_assets()
    def test_config_passes_installed_paths(self):
        with patch.object(server,"installed_kokoro_assets",return_value={"model_path":Path("local.onnx")}),patch.object(server,"kokoro_auto_preference",return_value="cpu"):
            config=server.build_kokoro_config("auto")
        self.assertEqual(config.model_path,Path("local.onnx"));self.assertEqual(config.provider,"cpu")

    def test_auto_records_actual_cuda_fallback(self):
        synth=Mock()
        with patch.object(server,"kokoro_cuda_failed",False),patch.object(server,"available_onnx_providers",return_value=["CUDAExecutionProvider","CPUExecutionProvider"]),patch.object(server,"installed_kokoro_assets",return_value={}),patch.object(server,"KokoroSynthesizer",return_value=synth),patch.object(server,"kokoro_active_providers",return_value=["CPUExecutionProvider"]):
            self.assertIs(server.create_kokoro_synthesizer("auto"),synth)
            self.assertEqual(server.kokoro_auto_preference(),"cpu")
            self.assertFalse(server.kokoro_compute_available("cuda"))
    def test_explicit_cuda_rejects_cpu_fallback(self):
        synth=Mock()
        with patch.object(server,"kokoro_cuda_failed",False),patch.object(server,"available_onnx_providers",return_value=["CUDAExecutionProvider","CPUExecutionProvider"]),patch.object(server,"installed_kokoro_assets",return_value={}),patch.object(server,"KokoroSynthesizer",return_value=synth),patch.object(server,"kokoro_active_providers",return_value=["CPUExecutionProvider"]):
            with self.assertRaisesRegex(RuntimeError,"fell back to CPU"):server.create_kokoro_synthesizer("cuda")
            synth.close.assert_called_once()

    def test_active_provider_reads_actual_ort_session(self):
        session=types.SimpleNamespace(session=types.SimpleNamespace(get_providers=lambda:["CPUExecutionProvider"]))
        adapter=types.SimpleNamespace(_owned_sessions=lambda:[session],diagnostics=lambda:types.SimpleNamespace(sessions=[types.SimpleNamespace(providers_active=["CUDAExecutionProvider"])]))
        synth=types.SimpleNamespace(_renderer=types.SimpleNamespace(_backend=types.SimpleNamespace(_runtime=types.SimpleNamespace(_runtime=adapter))))
        self.assertEqual(server.kokoro_active_providers(synth),["CPUExecutionProvider"])
    def test_missing_session_diagnostics_are_unknown(self):
        self.assertIsNone(server.kokoro_active_providers(types.SimpleNamespace()))

if __name__=="__main__":unittest.main(verbosity=2)

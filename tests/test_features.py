"""Deterministic local export/background tests, without neural inference."""
from io import BytesIO
from pathlib import Path
import hashlib
import struct
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch

import numpy as np
from PIL import Image
import soundfile as sf
from test_backend import server,sidecar
from audio_export import ExportJobs,write_chunk,qwen_frames,ExportCancelled,RATE
from backgrounds import BackgroundStore
from chunk_cache import ChunkCache


def image_bytes(fmt="PNG",size=(8,8)):
    out=BytesIO();Image.new("RGB",size,(17,23,41)).save(out,format=fmt);return out.getvalue()


def wait_job(jobs,key):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=jobs.status(key)
        if state["state"]!="generating" and jobs.active is None:return state
        time.sleep(.005)
    raise AssertionError("Job did not terminate")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.jobs=ExportJobs(self.root,self.frames,cancel_remote=lambda key:None)
        self.addCleanup(self.jobs.close)

    def frames(self,text,*args):
        value={"one":.2,"two":-.4}.get(text,.1)
        yield np.full(1000,value,dtype=np.float32),RATE

    def test_wav_headers_order_duration_and_actual_size(self):
        key=self.jobs.create(["one","two"],"kokoro","af_sarah","cpu")
        data=wait_job(self.jobs,key)
        self.assertEqual(data["state"],"ready")
        self.assertEqual(data["size"],4044);self.assertAlmostEqual(data["duration"],2000/RATE)
        with wave.open(str(self.jobs.jobs[key]["path"]),"rb") as audio:
            self.assertEqual((audio.getnchannels(),audio.getsampwidth(),audio.getframerate(),audio.getnframes()),(1,2,RATE,2000))
            pcm=np.frombuffer(audio.readframes(2000),dtype="<i2")
        self.assertGreater(pcm[400],6000);self.assertLess(pcm[1400],-12000)
        self.assertEqual(pcm[0],0);self.assertEqual(pcm[999],0);self.assertEqual(pcm[1000],0);self.assertEqual(pcm[-1],0)

    def test_pcm_frame_seams_not_faded(self):
        out=BytesIO();cancel=threading.Event()
        with wave.open(out,"wb") as wav:
            wav.setparams((1,2,RATE,0,"NONE","not compressed"))
            write_chunk(wav,iter([(np.full(500,.25),RATE),(np.full(500,.25),RATE)]),cancel,[0],time.monotonic())
        with wave.open(BytesIO(out.getvalue()),"rb") as wav:pcm=np.frombuffer(wav.readframes(1000),dtype="<i2")
        self.assertEqual(pcm[499],pcm[500]);self.assertGreater(pcm[500],8000)

    def test_mismatched_rate_fails_and_cleans_temp(self):
        self.jobs.generate=lambda *a:iter([(np.zeros(20),22050)])
        key=self.jobs.create(["one"],"kokoro","af_sarah","cpu")
        self.assertEqual(wait_job(self.jobs,key)["state"],"failed")
        self.assertFalse(self.jobs.jobs[key]["path"].exists())

    def test_invalid_samples_fail_and_clean(self):
        self.jobs.generate=lambda *a:iter([(np.array([float("nan")]),RATE)])
        key=self.jobs.create(["one"],"qwen","Ryan","auto")
        self.assertEqual(wait_job(self.jobs,key)["state"],"failed")
        self.assertFalse(list(self.root.glob("*.wav")))

    def test_failure_is_redacted_and_cleaned(self):
        def fail(*a):raise RuntimeError("PRIVATE/PATH")
        self.jobs.generate=fail
        key=self.jobs.create(["one"],"kokoro","af_sarah","cpu")
        status=wait_job(self.jobs,key)
        self.assertEqual(status["state"],"failed");self.assertNotIn("PRIVATE",status["error"])
        self.assertFalse(list(self.root.glob("*.wav")))

    def test_cancel_and_concurrent_job_rejection(self):
        entered=threading.Event()
        def generate(*args):
            entered.set()
            cancel=args[-1]
            while not cancel.wait(.01):pass
            yield np.zeros(20),RATE
        self.jobs.generate=generate
        key=self.jobs.create(["one"],"qwen","Ryan","auto");self.assertTrue(entered.wait(1))
        with self.assertRaises(RuntimeError):self.jobs.create(["two"],"qwen","Ryan","auto")
        self.jobs.cancel(key)
        self.assertEqual(wait_job(self.jobs,key)["state"],"cancelled")
        self.assertFalse(list(self.root.glob("*.wav")))

    def test_abandoned_client_lease_cancels_generation(self):
        entered=threading.Event()
        def generate(*args):
            entered.set()
            while not args[-1].wait(.01):pass
            yield np.zeros(20),RATE
        self.jobs.generate=generate
        key=self.jobs.create(["one"],"qwen","Ryan","auto");self.assertTrue(entered.wait(1))
        self.jobs.jobs[key]["heartbeat"]-=121
        self.jobs.prune()
        self.assertEqual(wait_job(self.jobs,key)["state"],"cancelled")

    def test_export_size_limit(self):
        with patch("audio_export.MAX_BYTES",100):
            key=self.jobs.create(["one"],"kokoro","af_sarah","cpu")
            self.assertEqual(wait_job(self.jobs,key)["state"],"failed")
        self.assertFalse(list(self.root.glob("*.wav")))

    def test_open_windows_download_defers_cleanup_without_breaking_status(self):
        key=self.jobs.create(["one"],"kokoro","af_sarah","cpu");wait_job(self.jobs,key)
        self.jobs.jobs[key]["updated"]-=601
        with patch.object(Path,"unlink",side_effect=PermissionError("download open")):
            self.assertEqual(self.jobs.status(key)["state"],"ready")
            self.assertTrue(self.jobs.cancel(key))
        path=self.jobs.jobs[key]["path"]
        self.jobs.prune()
        self.assertFalse(path.exists())

    def test_expiry_and_abandoned_file_cleanup(self):
        key=self.jobs.create(["one"],"kokoro","af_sarah","cpu");wait_job(self.jobs,key)
        self.jobs.jobs[key]["updated"]-=601
        self.assertIsNone(self.jobs.status(key));self.assertFalse(list(self.root.glob("*.wav")))

    def test_cancel_ready_file(self):
        key=self.jobs.create(["one"],"kokoro","af_sarah","cpu");wait_job(self.jobs,key)
        self.assertTrue(self.jobs.cancel(key));self.assertFalse(self.jobs.jobs[key]["path"].exists())

    def test_qwen_frame_protocol_and_cancellation(self):
        pcm=np.array([.1,.2,.3],dtype="<f4").tobytes()
        raw=struct.pack("<IIII",len(pcm),RATE,0,0)+pcm+struct.pack("<IIII",0,RATE,1,1)
        with patch("audio_export.urllib.request.urlopen",return_value=BytesIO(raw)):
            result=list(qwen_frames("one","Ryan","export",threading.Event()))
            np.testing.assert_array_equal(result[0][0],np.frombuffer(pcm,dtype="<f4"))
        for invalid in (raw[:-3],struct.pack("<IIII",4,22050,0,0)+b"abcd",struct.pack("<IIII",4,RATE,5,0)+b"abcd"):
            with patch("audio_export.urllib.request.urlopen",return_value=BytesIO(invalid)):
                with self.assertRaises(ValueError):list(qwen_frames("one","Ryan","export",threading.Event()))
        event=threading.Event();event.set()
        with patch("audio_export.urllib.request.urlopen",return_value=BytesIO(raw)):
            with self.assertRaises(ExportCancelled):list(qwen_frames("one","Ryan","export",event))


class FeatureRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.jobs=ExportJobs(self.root/"exports",lambda *a:iter([(np.ones(1000,dtype=np.float32)*.2,RATE)]),lambda key:None)
        self.addCleanup(self.jobs.close)
        for name,value in (("export_jobs",self.jobs),("background_store",BackgroundStore(self.root/"user-data"))):
            p=patch.object(server,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(server,"kokoro_compute_available",return_value=True);p.start();self.addCleanup(p.stop)
        self.client=server.app.test_client()
        self.payload={"chunks":["one","two"],"engine":"kokoro","voice":"af_sarah","compute":"cpu"}

    def test_empty_long_invalid_and_nonobject_requests(self):
        for body in ([],{},dict(self.payload,chunks=[]),dict(self.payload,chunks=["x"*3001]),
                     dict(self.payload,chunks=["x"*1000]*21),dict(self.payload,chunks=["x"]*257),
                     dict(self.payload,voice="../voice"),dict(self.payload,engine="other"),dict(self.payload,voice=[]),
                     dict(self.payload,engine="qwen",voice="Ryan",compute="cpu")):
            self.assertEqual(self.client.post("/exports",json=body).status_code,400)

    def test_complete_download_and_measured_metrics(self):
        response=self.client.post("/exports",json=self.payload)
        self.assertEqual(response.status_code,202);key=response.json["id"]
        status=wait_job(self.jobs,key)
        self.assertEqual(self.client.get("/exports/"+key).json["size"],status["size"])
        response=self.client.get("/exports/"+key+"/file")
        self.assertEqual(response.status_code,200);self.assertEqual(len(response.data),4044)
        self.assertIn("VOX-9K-Recording.wav",response.headers["Content-Disposition"]);response.close()
        self.assertEqual(self.client.delete("/exports/"+key).status_code,200)
        self.assertEqual(self.client.get("/exports/"+key+"/file").status_code,409)
        self.assertEqual(self.client.get("/exports/not-a-path/file").status_code,404)

    def test_long_multichunk_export(self):
        body=dict(self.payload,chunks=["words "*200]*16)
        response=self.client.post("/exports",json=body)
        self.assertEqual(response.status_code,202)
        status=wait_job(self.jobs,response.json["id"])
        self.assertEqual(status["completed"],16);self.assertEqual(status["size"],32044)

    def test_export_security_body_bound_and_missing_jobs(self):
        self.assertEqual(self.client.post("/exports",json=self.payload,headers={"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.client.post("/exports",data=b"x"*70000,content_type="application/json").status_code,413)
        self.assertEqual(self.client.delete("/exports/missing").status_code,404)
        self.assertEqual(self.client.get("/features.js").status_code,200)

    def test_background_formats_content_and_default_untouched(self):
        original=hashlib.sha256((server.BASE_DIR/"background.png").read_bytes()).digest()
        for fmt in ("PNG","JPEG","WEBP"):
            response=self.client.post("/background-image?filename=../../outside.png",data=image_bytes(fmt),content_type="application/octet-stream")
            self.assertEqual(response.status_code,200)
            with Image.open(server.background_store.path) as image:self.assertEqual(image.format,"PNG")
            response=self.client.get("/background-image");self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(hashlib.sha256((server.BASE_DIR/"background.png").read_bytes()).digest(),original)
        self.assertFalse((self.root/"outside.png").exists())

    def test_valid_background_above_normal_json_body_limit(self):
        rng=np.random.default_rng(3)
        pixels=rng.integers(0,256,(256,256,3),dtype=np.uint8)
        data=BytesIO();Image.fromarray(pixels).save(data,format="PNG")
        self.assertGreater(len(data.getvalue()),65536)
        self.assertEqual(self.client.post("/background-image",data=data.getvalue()).status_code,200)
        self.assertEqual(self.client.post("/tts",data=b"x"*70000,content_type="application/json").status_code,413)

    def test_background_invalid_active_content_and_size(self):
        for data in (b"<svg xmlns='http://www.w3.org/2000/svg'/>",b"not an image",image_bytes()[:20]):
            self.assertEqual(self.client.post("/background-image",data=data).status_code,400)
        self.assertEqual(self.client.post("/background-image",data=b"x"*(8*1024*1024+1)).status_code,413)
        self.assertFalse(server.background_store.path.exists())

    def test_background_dimension_limit(self):
        self.assertEqual(self.client.post("/background-image",data=image_bytes(size=(8193,1))).status_code,400)

    def test_background_persistence_restore_and_security(self):
        self.client.post("/background-image",data=image_bytes())
        reopened=BackgroundStore(server.background_store.directory)
        self.assertTrue(reopened.path.is_file())
        for method in ("post","delete"):
            response=getattr(self.client,method)("/background-image",data=image_bytes() if method=="post" else None,headers={"Origin":"https://evil.example"})
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.delete("/background-image").status_code,200)
        self.assertFalse(reopened.path.exists())
        response=self.client.get("/background-image");self.assertEqual(response.status_code,200);response.close()

    def test_background_storage_permission_failure_is_safe_and_reported(self):
        with patch.object(server.background_store,"save",side_effect=PermissionError("PRIVATE/PATH")):
            response=self.client.post("/background-image",data=image_bytes())
        self.assertEqual(response.status_code,500)
        self.assertIn("application data",response.json["error"])
        self.assertNotIn("PRIVATE",response.json["error"])

    def test_restore_permission_failure_is_safe_and_retains_current_image(self):
        self.client.post("/background-image",data=image_bytes())
        with patch.object(server.background_store,"restore",side_effect=PermissionError("PRIVATE/PATH")):
            response=self.client.delete("/background-image")
        self.assertEqual(response.status_code,500)
        self.assertNotIn("PRIVATE",response.json["error"])
        self.assertTrue(server.background_store.path.exists())

    def test_atomic_write_failure_preserves_prior_background_and_removes_temp(self):
        store=server.background_store
        store.save(image_bytes())
        original=store.path.read_bytes()
        with patch("backgrounds.os.replace",side_effect=PermissionError("PRIVATE/PATH")):
            response=self.client.post("/background-image",data=image_bytes("JPEG"))
        self.assertEqual(response.status_code,500)
        self.assertEqual(store.path.read_bytes(),original)
        self.assertEqual(list(store.directory.glob("*.tmp")),[])

    def test_missing_picker_file_does_not_turn_into_a_filesystem_read_endpoint(self):
        response=self.client.post("/background-image",json={"path":"C:/private/image.png"})
        self.assertEqual(response.status_code,400)
        self.assertFalse(server.background_store.path.exists())

    def test_kokoro_native_decode(self):
        out=BytesIO();sf.write(out,np.full(500,.2),RATE,format="WAV",subtype="FLOAT")
        with patch.object(server,"synthesize_kokoro",return_value=out.getvalue()):
            frames=list(server.export_frames("one","kokoro","af_sarah","cpu","id",threading.Event()))
        self.assertEqual(frames[0][1],RATE);self.assertEqual(len(frames[0][0]),500)

    def test_qwen_cache_reused_without_generation(self):
        cache=ChunkCache(self.root/"pcm")
        with cache.record("one","Ryan") as record:
            record.write(np.full(500,.3,dtype="<f4").tobytes());record.complete=True
        with patch.object(server,"pcm_cache",cache),patch.object(server,"qwen_frames") as generate:
            frames=list(server.export_frames("one","qwen","Ryan","auto","id",threading.Event()))
            generate.assert_not_called();self.assertEqual(len(frames[0][0]),500)


class CacheAndCoordinationTests(unittest.TestCase):
    def test_only_complete_cache_is_reused_and_limits_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=ChunkCache(directory)
            with cache.record("first","Ryan") as record:record.write(b"abcd")
            self.assertIsNone(cache.find("first","Ryan"))
            with cache.record("first","Ryan") as record:record.write(b"abcd");record.complete=True
            self.assertIsNotNone(cache.find("first","Ryan"))
            with patch("chunk_cache.MAX_CHUNK_BYTES",2):
                with cache.record("second","Ryan") as record:record.write(b"abcd");record.complete=True
                self.assertIsNone(cache.find("second","Ryan"))
            with patch("chunk_cache.MAX_CACHE_BYTES",0):cache.prune()
            self.assertFalse(list(Path(directory).iterdir()))

    def test_qwen_export_cannot_cancel_active_playback(self):
        event=threading.Event()
        with patch.object(sidecar,"_current_generation",{"request_id":"playback","cancel_event":event}):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as error:sidecar.begin_generation("export",only_if_idle=True)
            self.assertEqual(error.exception.status_code,409);self.assertFalse(event.is_set())
            new=sidecar.begin_generation("new-playback")
            self.assertTrue(event.is_set())
            sidecar.finish_generation("new-playback",new)

    def test_playback_can_supersede_export_without_stale_cleanup(self):
        with patch.object(sidecar,"_current_generation",{"request_id":None,"cancel_event":None}):
            export=sidecar.begin_generation("export",only_if_idle=True)
            playback=sidecar.begin_generation("playback")
            self.assertTrue(export.is_set())
            sidecar.finish_generation("export",export)
            self.assertIs(sidecar._current_generation["cancel_event"],playback)
            sidecar.finish_generation("playback",playback)


if __name__=="__main__":unittest.main()

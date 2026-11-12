"""Explicit native-window acceptance. Uses cached neural models and audible playback.

Run separately from headless tests. Requires pywebview, the installed engines and
an interactive Windows desktop. Results do not establish perceptual audio quality.
"""
from pathlib import Path
import json
import os
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ["HF_HUB_OFFLINE"]="1"
os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
import desktop
import webview
import psutil

OUT=ROOT/"audit"/"runtime-v1-2026-11-11"
OUT.mkdir(parents=True,exist_ok=True)
RESULT={"checks":{},"audio_quality":"Requires owner listening; playback state alone does not verify quality."}
services=desktop.DesktopServices()
owned_pids=[]
completed=threading.Event()


def save():
    (OUT/"desktop-native-acceptance.json").write_text(json.dumps(RESULT,indent=2))


def wait(window,expression,timeout=120):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=window.evaluate_js(expression)
        if value:return value
        if services.closed.is_set():raise RuntimeError("Window closed during native acceptance")
        time.sleep(.1)
    raise TimeoutError("Native acceptance condition timed out: "+expression)


def read(window,engine,voice,text):
    window.evaluate_js("document.getElementById('engineSelect').value="+json.dumps(engine)+";document.getElementById('engineSelect').dispatchEvent(new Event('change'));document.getElementById('voiceSelect').value="+json.dumps(voice)+";document.getElementById('computeSelect').value="+json.dumps("cpu" if engine=="kokoro" else "auto")+";document.getElementById('promptText').value="+json.dumps(text)+";document.getElementById('readButton').click();")


def checks(window):
    global owned_pids
    try:
        RESULT["capabilities"]=window.evaluate_js("({url:location.href,userAgent:navigator.userAgent,segmenter:typeof Intl.Segmenter,uuid:typeof crypto.randomUUID,fetch:typeof fetch,stream:typeof ReadableStream,audioContext:typeof AudioContext,audioSource:typeof AudioBufferSourceNode,controls:!!document.getElementById('readButton')})")
        assert RESULT["capabilities"]["url"]==desktop.APP_URL+"/"
        assert all(RESULT["capabilities"][name]=="function" for name in ("segmenter","uuid","fetch","stream","audioContext","audioSource"))
        if services.process:
            process=psutil.Process(services.process.pid)
            owned_pids=[process.pid]+[p.pid for p in process.children(recursive=True)]
        passage="VOX nine K is testing native desktop playback. The speech is generated locally on this computer."
        read(window,"kokoro","af_sarah",passage)
        wait(window,"currentAudio && !currentAudio.paused && currentAudio.currentTime > 0.2")
        RESULT["checks"]["kokoro_playback_started"]=True
        RESULT["compute_status"]=window.evaluate_js("({preference:systemInfo.auto_preference,label:document.getElementById('computeInfo').textContent,cudaEnabled:!document.getElementById('cudaOption').disabled})")
        window.evaluate_js("document.getElementById('pauseButton').click()")
        wait(window,"isPaused && currentAudio && currentAudio.paused",5)
        paused=window.evaluate_js("currentAudio.currentTime")
        time.sleep(.3)
        assert abs(window.evaluate_js("currentAudio.currentTime")-paused)<.1
        window.evaluate_js("document.getElementById('pauseButton').click()")
        wait(window,"currentAudio && !isPaused && currentAudio.currentTime > "+str(paused+.15),5)
        RESULT["checks"]["kokoro_pause_resume"]=True
        window.evaluate_js("document.getElementById('speedSlider').value='1.2';document.getElementById('speedSlider').dispatchEvent(new Event('input'));document.getElementById('volumeSlider').value='0.4';document.getElementById('volumeSlider').dispatchEvent(new Event('input'))")
        RESULT["kokoro_settings"]=window.evaluate_js("({rate:currentAudio.playbackRate,volume:currentAudio.volume,preservesPitch:currentAudio.preservesPitch})")
        window.evaluate_js("document.getElementById('stopButton').click()")
        wait(window,"!isActive && !currentAudio && fetchControllers.size===0",5)
        RESULT["checks"]["kokoro_stop"]=True
        read(window,"qwen","Ryan",passage)
        wait(window,"qwenCurrentSource && qwenAudioContext && qwenAudioContext.state==='running' && qwenFirstAudioStarted")
        RESULT["checks"]["qwen_pcm_playback_started"]=True
        window.evaluate_js("document.getElementById('pauseButton').click()")
        wait(window,"isPaused && qwenAudioContext.state==='suspended'",5)
        window.evaluate_js("document.getElementById('pauseButton').click()")
        wait(window,"!isPaused && qwenAudioContext.state==='running'",5)
        RESULT["checks"]["qwen_pause_resume"]=True
        RESULT["qwen_volume"]=window.evaluate_js("qwenGainNode.gain.value")
        window.evaluate_js("document.getElementById('stopButton').click()")
        wait(window,"!isActive && !qwenAudioContext && !qwenCurrentSource",5)
        RESULT["checks"]["qwen_stop"]=True
        read(window,"qwen","Aiden",passage)
        wait(window,"qwenCurrentSource && qwenAudioContext.state==='running' && qwenFirstAudioStarted")
        RESULT["checks"]["qwen_second_voice_after_cancel"]=True
        window.evaluate_js("document.getElementById('stopButton').click()")
        read(window,"kokoro","am_michael",passage)
        wait(window,"currentAudio && !currentAudio.paused && currentAudio.currentTime>0.2")
        RESULT["checks"]["switch_back_to_kokoro"]=True
        window.evaluate_js("document.getElementById('stopButton').click()")
        RESULT["outcome"]="passed"
        RESULT["native_checks_completed"]=True
        save()
        print("NATIVE CHECKS PASSED; retaining window for 45 seconds for browser/owner inspection",flush=True)
        time.sleep(45)
    except Exception as error:
        RESULT.update(outcome="failed",error=str(error),traceback=traceback.format_exc())
        print(traceback.format_exc(),flush=True)
    finally:
        completed.set()
        save()
        window.destroy()


original_create=webview.create_window

def instrumented_create(*args,**kwargs):
    window=original_create(*args,**kwargs)
    started=threading.Event()
    def loaded():
        if not started.is_set() and window.get_current_url() in (desktop.APP_URL,desktop.APP_URL+"/"):
            started.set()
            threading.Thread(target=checks,args=(window,),daemon=True).start()
    window.events.loaded+=loaded
    return window


if __name__=="__main__":
    webview.create_window=instrumented_create
    code=desktop.main(webview,services)
    RESULT["launcher_exit_code"]=code
    RESULT["owned_pids"]=owned_pids
    deadline=time.monotonic()+5
    while any(psutil.pid_exists(pid) for pid in owned_pids) and time.monotonic()<deadline:time.sleep(.1)
    RESULT["owned_processes_remaining"]=[pid for pid in owned_pids if psutil.pid_exists(pid)]
    if not completed.is_set():RESULT.update(outcome="failed",error="Native checks did not reach the application page")
    save()
    print(json.dumps(RESULT,indent=2))

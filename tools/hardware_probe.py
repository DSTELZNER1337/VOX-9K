"""Explicit, small cached Kokoro probe. Network is blocked inside this process."""
import argparse
import importlib.metadata
import io
import json
import os
import pathlib
import platform
import socket
import sys
import time
import traceback
import soundfile as sf

parser=argparse.ArgumentParser()
parser.add_argument('--mode', choices=['cpu','cuda'], default='cpu')
parser.add_argument('--baseline', action='store_true', help='Run the preserved starting source against the same installed environment/cache')
args=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
(root/'audit').mkdir(exist_ok=True)
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
def blocked(*args, **kwargs):
    raise OSError('Network disabled by the audit hardware probe; no downloads allowed')
socket.socket.connect=blocked
socket.create_connection=blocked
result={'platform': platform.platform(), 'python':sys.version, 'mode':args.mode,
        'text':'VOX nine K is a local speech application.', 'voice':'af_sarah',
        'conditions':'New process, existing cache, network blocked; WAV generation only, no browser playback',
        'text_length':39,'runs':[]}
started=time.perf_counter()
try:
    if args.baseline:
        import types
        server=types.ModuleType('server')
        server.__file__=str(root/'server.py')
        sys.modules['server']=server
        baseline=root/'audit'/'baseline-2026-11-11'/'server.py'
        exec(compile(baseline.read_text(), str(root/'server.py'), 'exec'), server.__dict__)
    else:
        import server
    result['import_seconds']=time.perf_counter()-started
    result['providers_detected']=server.available_onnx_providers()
    for index in range(2):
        tick=time.perf_counter()
        data=server.synthesize_kokoro(result['text'],result['voice'],args.mode)
        elapsed=time.perf_counter()-tick
        with sf.SoundFile(io.BytesIO(data)) as audio:
            duration=len(audio)/audio.samplerate
            rate=audio.samplerate
        result['runs'].append({'index':index,'seconds_to_complete_wav':elapsed,'audio_seconds':duration,'sample_rate':rate,'bytes':len(data),'audio_seconds_per_wall_second':duration/elapsed})
    result['outcome']='passed'
except Exception as error:
    result['outcome']='failed'
    result['error']=str(error)
    result['traceback']=traceback.format_exc()
finally:
    if 'server' in sys.modules:
        server.close_engines()
    result['total_seconds']=time.perf_counter()-started
    result['text_length']=len(result['text'])
    prefix='hardware-baseline-kokoro' if args.baseline else 'hardware-kokoro'
    (root/'audit'/f'{prefix}-{args.mode}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({key:value for key,value in result.items() if key!='traceback'},indent=2))

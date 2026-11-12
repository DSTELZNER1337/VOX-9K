"""Single disk-backed export job, bounded PCM writing and framed Qwen decoding."""
from pathlib import Path
import json
import math
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

RATE=24000
MAX_TEXT=20000
MAX_BYTES=96*1024*1024
MAX_SECONDS=1800
READY_TTL=600
CLIENT_LEASE=120


class ExportCancelled(Exception):
    pass


def checked_pcm(samples, rate):
    values=np.asarray(samples,dtype=np.float32)
    if rate!=RATE or values.ndim!=1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Expected finite mono 24 kHz PCM.")
    return values


def write_chunk(wav, frames, cancel, budget, started):
    """Keep PCM frame seams untouched; fade only 5 ms at text-chunk edges."""
    tail=np.empty(0,dtype=np.float32)
    head=0
    count=0
    def write(values):
        nonlocal count
        if not len(values):return
        count+=len(values)
        if budget[0]+len(values)*2+44>MAX_BYTES:raise ValueError("WAV size limit reached.")
        if cancel.is_set():raise ExportCancelled()
        if time.monotonic()-started>MAX_SECONDS:raise ValueError("Export time limit reached.")
        pcm=np.rint(np.clip(values,-1,1)*32767).astype("<i2")
        wav.writeframesraw(pcm.tobytes())
        budget[0]+=len(pcm)*2
    for values,rate in frames:
        if cancel.is_set():raise ExportCancelled()
        values=checked_pcm(values,rate).copy()
        n=min(len(values),120-head)
        if n>0:
            values[:n]*=np.arange(head,head+n,dtype=np.float32)/119
            head+=n
        combined=np.concatenate((tail,values))
        if len(combined)>120:
            write(combined[:-120])
            tail=combined[-120:]
        else:tail=combined
    if not len(tail):raise ValueError("No audio was generated.")
    tail*=np.linspace(1,0,len(tail),dtype=np.float32)
    write(tail)
    return count


def qwen_frames(text, voice, request_id, cancel, base_url="http://127.0.0.1:5001"):
    body=json.dumps({"text":text,"speaker":voice,"language":"English","chunk_size":8,
                     "request_id":request_id,"export":True}).encode()
    req=urllib.request.Request(base_url+"/stream",data=body,headers={"Content-Type":"application/json"})
    def exact(response,n):
        data=bytearray()
        while len(data)<n:
            if cancel.is_set():raise ExportCancelled()
            part=response.read(n-len(data))
            if not part:raise ValueError("Incomplete Qwen export stream.")
            data.extend(part)
        return data
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            index=0
            while True:
                size,rate,sequence,flags=struct.unpack("<IIII",exact(response,16))
                if rate!=RATE or sequence!=index or size>4*1024*1024 or size%4:
                    raise ValueError("Invalid Qwen export frame.")
                if flags==1 and size==0:return
                if flags!=0 or not size:raise ValueError("Qwen export failed or was interrupted.")
                yield checked_pcm(np.frombuffer(exact(response,size),dtype="<f4"),rate),rate
                index+=1
    except urllib.error.HTTPError as error:
        if error.code==409:raise ValueError("Qwen is reading in another window. Stop it before exporting.") from None
        raise ValueError("Qwen is unavailable. Wait until the engine is ready and retry.") from None


def cancel_qwen(request_id):
    if not request_id:return
    req=urllib.request.Request("http://127.0.0.1:5001/cancel",
        data=json.dumps({"request_id":request_id}).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=2):pass
    except OSError:pass


class ExportJobs:
    def __init__(self,directory,generate,cancel_remote=cancel_qwen):
        self.directory=Path(directory)
        self.generate=generate
        self.cancel_remote=cancel_remote
        self.lock=threading.RLock()
        self.jobs={}
        self.active=None

    def prune(self):
        with self.lock:
            now=time.monotonic()
            for key,job in list(self.jobs.items()):
                if key==self.active and now-job["heartbeat"]>CLIENT_LEASE:
                    self.cancel(key)
                if job["state"] in ("cancelled","failed"):
                    try:job["path"].unlink(missing_ok=True)
                    except OSError:pass
                if key!=self.active and now-job["updated"]>READY_TTL:
                    try:job["path"].unlink(missing_ok=True)
                    except OSError:continue  # An open Windows download can temporarily hold the file.
                    del self.jobs[key]
            if self.directory.exists():
                # Only this feature's own UUID filenames; stale files after a crash.
                for p in self.directory.glob("*.wav"):
                    if len(p.stem)==32 and all(c in "0123456789abcdef" for c in p.stem):
                        try:
                            if time.time()-p.stat().st_mtime>READY_TTL and all(j["path"]!=p for j in self.jobs.values()):
                                p.unlink(missing_ok=True)
                        except OSError:pass

    def create(self,chunks,engine,voice,compute):
        with self.lock:
            self.prune()
            if self.active:raise RuntimeError("An export is already running. Cancel it or wait.")
            if len(self.jobs)>=8:raise RuntimeError("Too many pending downloads. Download or cancel an existing export.")
            self.directory.mkdir(parents=True,exist_ok=True)
            key=uuid.uuid4().hex
            job={"id":key,"state":"generating","completed":0,"total":len(chunks),
                 "path":self.directory/(key+".wav"),"cancel":threading.Event(),
                 "request_id":None,"updated":time.monotonic(),"heartbeat":time.monotonic(),"error":None}
            self.jobs[key]=job;self.active=key
            threading.Thread(target=self._run,args=(job,list(chunks),engine,voice,compute),name="vox-wav-export",daemon=False).start()
            return key

    def _run(self,job,chunks,engine,voice,compute):
        budget=[0];started=time.monotonic()
        try:
            with wave.open(str(job["path"]),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
                for i,text in enumerate(chunks):
                    if job["cancel"].is_set():raise ExportCancelled()
                    request_id="export-"+job["id"]+":0:"+str(i)
                    with self.lock:job["request_id"]=request_id
                    frames=self.generate(text,engine,voice,compute,request_id,job["cancel"])
                    try:write_chunk(wav,frames,job["cancel"],budget,started)
                    finally:
                        close=getattr(frames,"close",None)
                        if close:close()
                    with self.lock:job["completed"]=i+1
            with self.lock:
                if job["cancel"].is_set():raise ExportCancelled()
                job.update(state="ready",duration=budget[0]/2/RATE,size=job["path"].stat().st_size)
        except ExportCancelled:
            with self.lock:job["state"]="cancelled"
        except Exception as error:
            with self.lock:
                job.update(state="failed",error=str(error) if isinstance(error,ValueError) else "Export failed. Check the local server console.")
            print("WAV export error:",error)
        finally:
            with self.lock:
                if job["state"]!="ready":job["path"].unlink(missing_ok=True)
                job["updated"]=time.monotonic();job["request_id"]=None
                if self.active==job["id"]:self.active=None

    def status(self,key):
        with self.lock:
            self.prune()
            job=self.jobs.get(key)
            if not job:return None
            job["heartbeat"]=time.monotonic()
            return {k:job[k] for k in ("id","state","completed","total","error","duration","size") if k in job}

    def cancel(self,key):
        with self.lock:
            job=self.jobs.get(key)
            if not job:return False
            job["cancel"].set()
            remote=job["request_id"]
            if job["state"]=="ready":
                job["state"]="cancelled"
                try:job["path"].unlink(missing_ok=True)
                except OSError:pass  # Retry during cleanup after an active download closes.
        if remote:
            threading.Thread(target=self.cancel_remote,args=(remote,),daemon=True).start()
        return True

    def close(self):
        with self.lock:keys=list(self.jobs)
        for key in keys:self.cancel(key)

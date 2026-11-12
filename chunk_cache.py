"""Bounded, short-lived native Qwen PCM reuse; never alters live playback."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import tempfile
import time

MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024
TTL = 1800


class ChunkCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, text, voice):
        key = hashlib.sha256(("qwen-v1\0"+voice+"\0"+text).encode("utf-8")).hexdigest()
        return self.directory / (key+".f32")

    def find(self, text, voice):
        path = self.path(text, voice)
        try:
            if 0 < path.stat().st_size <= MAX_CHUNK_BYTES and time.time()-path.stat().st_mtime < TTL:
                return path
        except OSError:
            pass
        return None

    def prune(self):
        files = []
        for p in self.directory.glob("*.f32"):
            if len(p.stem) != 64 or any(c not in "0123456789abcdef" for c in p.stem):
                continue
            try:
                stat=p.stat()
                if time.time()-stat.st_mtime > TTL:
                    p.unlink(missing_ok=True)
                else:
                    files.append((stat.st_mtime,stat.st_size,p))
            except OSError:
                pass
        total=sum(n for _,n,_ in files)
        for _,n,p in sorted(files):
            if total<=MAX_CACHE_BYTES:break
            try:p.unlink();total-=n
            except OSError:pass

    @contextmanager
    def record(self, text, voice):
        """Best-effort disk cache; publish only a fully exhausted, valid stream."""
        path = None
        handle = None
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            self.prune()
            handle = tempfile.NamedTemporaryFile(dir=self.directory,suffix=".part",delete=False)
            path=Path(handle.name)
            class Recorder:
                complete=False
                size=0
                disabled=False
                def write(self, data):
                    self.size+=len(data)
                    if self.size>MAX_CHUNK_BYTES:
                        self.disabled=True
                    if not self.disabled:
                        try:handle.write(data)
                        except OSError:self.disabled=True
            recorder=Recorder()
            yield recorder
            handle.close()
            if recorder.complete and recorder.size and not recorder.disabled:
                os.replace(path,self.path(text,voice))
                self.prune()
        finally:
            if handle:handle.close()
            if path:path.unlink(missing_ok=True)

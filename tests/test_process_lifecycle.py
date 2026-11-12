"""Real ownership pipe and native-import regression; no GUI or models."""
from pathlib import Path
import os,subprocess,sys,threading,unittest

class PipeLifecycleTests(unittest.TestCase):
    def test_native_import_and_parent_eof_cleanup(self):
        root=Path(__file__).resolve().parents[1]
        code=f"import sys,os,threading;sys.path.insert(0,{str(root)!r});from process_lifecycle import wait_for_parent_eof;threading.Thread(target=lambda:(wait_for_parent_eof(),os._exit(0)),daemon=True).start();import numpy;print('native-ready',flush=True);threading.Event().wait()"
        process=subprocess.Popen([sys.executable,'-B','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        lines=[];ready=threading.Event()
        def read_ready():
            lines.append(process.stdout.readline().strip());ready.set()
        reader=threading.Thread(target=read_ready,daemon=True);reader.start()
        try:
            self.assertTrue(ready.wait(15),'Native import stalled while the ownership pipe was open')
            self.assertEqual(lines,[b'native-ready'])
            process.stdin.close()
            self.assertEqual(process.wait(5),0)
        finally:
            if process.poll() is None:process.terminate();process.wait(5)
            if not process.stdin.closed:process.stdin.close()
            reader.join(2);process.stdout.close();process.stderr.close()

if __name__=='__main__':unittest.main(verbosity=2)

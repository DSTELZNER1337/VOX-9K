"""Inventory metadata only; never import inference packages or contact the network."""
from importlib.metadata import distributions
import json
import pathlib
import subprocess
import sys

name=sys.argv[1]
root=pathlib.Path(__file__).resolve().parents[1]
output=root/'audit'/name
output.mkdir(parents=True, exist_ok=True)
rows=[]
for dist in distributions():
    metadata=dist.metadata
    license_name=metadata.get('License-Expression') or metadata.get('License') or ''
    rows.append({'name':metadata['Name'],'version':dist.version,
                 'license':license_name[:180] if '\n' not in license_name else license_name.splitlines()[0],
                 'license_classifiers':[x for x in metadata.get_all('Classifier',[]) if x.startswith('License')],
                 'license_files':metadata.get_all('License-File',[]),
                 'requirements':dist.requires or []})
(output/'packages.json').write_text(json.dumps(sorted(rows,key=lambda x:x['name'].lower()),indent=2))
for filename,args in [('freeze.txt',['freeze']),('pip-check.txt',['check'])]:
    result=subprocess.run([sys.executable,'-m','pip',*args],capture_output=True,text=True)
    (output/filename).write_text(result.stdout+result.stderr)
    print(name,filename,'exit',result.returncode)

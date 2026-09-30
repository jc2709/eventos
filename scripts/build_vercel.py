"""Genera los archivos estáticos de Vercel; mantiene intacta la versión local."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'public'
if OUTPUT.exists():
    shutil.rmtree(OUTPUT)
shutil.copytree(ROOT / 'web', OUTPUT)
(OUTPUT / 'runtime.json').write_text(json.dumps({'mode': 'cloud'}))
print('Aula EDA: interfaz preparada en public, motor Python en api/lab.py')

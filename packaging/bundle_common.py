"""Shared PyInstaller data map; only runtime resources, never private projects."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = [(str(ROOT/'resources/comp_images'),'comp_images'),
        (str(ROOT/'resources/components'),'resources/components'),
        (str(ROOT/'resources/spice'),'resources/spice'),
        (str(ROOT/'resources/icons/icon.png'),'.'),
        (str(ROOT/'docs/MANUAL_ZH.md'),'.'),
        (str(ROOT/'docs/reference/计算方法与公式说明.docx'),'.'),
        (str(ROOT/'docs/reference/开关电源介绍与计算方法.docx'),'.'),
        (str(ROOT/'docs/reference/自动计算参数依据.docx'),'.'),
        (str(ROOT/'docs/tutorials/多路反激电源设计入门教程.docx'),'.')]
# Personal QR is an optional sidecar. PyInstaller must never collect the
# ignored source file into a public bundle just because it exists locally.
DATA += [(str(path), 'examples/'+path.name if path.is_dir() else 'examples')
         for path in (ROOT/'examples').iterdir() if path.name != '90W_QR_L6565_252_442V.json']
DATA += [(str(path),'docs') for path in (ROOT/'docs').glob('*.md')]
EXCLUDES = ['torch','PyQt5','PyQt6','PySide2','PySide6','IPython','jedi','parso',
    'zmq','notebook','nbformat','lark','plotly','pandas','pytest','cv2',
    'sklearn','dask','jupyter','prompt_toolkit','pygments']

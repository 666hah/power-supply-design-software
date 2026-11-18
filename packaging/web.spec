# Local service + static UI. No Node/Python installation required by recipient.
import sys
sys.path.insert(0, SPECPATH)
from bundle_common import ROOT, DATA, EXCLUDES
core_catalog = (str(ROOT/'resources/core_shapes/catalog.json'), 'resources/core_shapes')
a = Analysis([str(ROOT/'run_web.py')],pathex=[str(ROOT)],binaries=[],
    datas=DATA+[core_catalog, (str(ROOT/'web_app/static'),'web_app/static')]+([(str(ROOT/'web_app/pcs_static'),'web_app/pcs_static')] if (ROOT/'web_app/pcs_static').is_dir() else []),
    hiddenimports=['matplotlib.backends.backend_agg','matplotlib.backends.backend_svg','scipy.signal','control','docx',
                   'uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl',
                   'uvicorn.lifespan.on','cot_ui_schema'],
    excludes=EXCLUDES+['tkinter','matplotlib.backends.backend_tkagg',
                       'matplotlib.backends.backend_qtagg'],
    hookspath=[],runtime_hooks=[],noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='PowerDesignWeb',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True,
    icon=str(ROOT/'resources/icons/icon.ico'))
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PowerDesignWeb')

"""Nonmodal desktop preview controller. Tk reads stay on its own thread."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import messagebox

from transformer_preview_host import write_json


def make_scene(app):
    from transformer_preview_scene import build_scene
    state = getattr(app, '_winding_preview_state', {})
    core_name = state.get('core')
    if not core_name:
        raise ValueError('请先完成当前变压器计算，再打开 3D 结构预览。')
    config = app._winding_config()['winding_config']
    return build_scene(core_name, copy.deepcopy(app._winding_source or []), config,
        profile=copy.deepcopy(getattr(app, '_geometry_profile', None)),
        title='变压器 3D 结构 · ' + str(core_name), gap=state.get('gap'),
        stale=not getattr(app, '_snapshot_valid', True))


def worker_command(scene):
    if getattr(sys, 'frozen', False):
        prefix = [sys.executable, '--transformer-preview']
    else:
        prefix = [sys.executable, str(Path(__file__).with_name('transformer_preview_host.py'))]
    return prefix + [str(scene), '--parent-pid', str(os.getpid())]


class PreviewSession:
    def __init__(self, app, scene):
        self.app = app
        self.root = app.root
        self.directory = Path(tempfile.mkdtemp(prefix='power-design-preview-'))
        self.scene_file = self.directory / 'scene.json'
        self.process = None
        self.timer = None
        self.closed = False
        self.loaded = False
        self._last = None
        self._error_shown = False
        self.publish(scene)
        try:
            with (self.directory / 'host.log').open('w', encoding='utf-8') as stream:
                self.process = subprocess.Popen(worker_command(self.scene_file),
                    stdout=stream, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except BaseException:
            shutil.rmtree(self.directory)
            raise
        self._binding = self.root.bind('<Destroy>', self._destroyed, add='+')
        self._poll()

    def publish(self, scene):
        serialized = json.dumps(scene, ensure_ascii=True, allow_nan=False, sort_keys=True)
        if serialized != self._last:
            write_json(self.scene_file, scene)
            self._last = serialized

    def focus(self):
        write_json(self.directory / 'command.json', {'action': 'focus', 'time': time.time_ns()})

    def _destroyed(self, event):
        if event.widget == self.root:
            self.close()

    def _poll(self):
        if self.closed:
            return
        try:
            status = json.loads((self.directory / 'status.json').read_text('utf-8'))
        except (OSError, ValueError):
            status = {}
        if status.get('state') == 'ready':
            self.loaded = True
        if status.get('state') == 'error' and not self._error_shown:
            self._error_shown = True
            messagebox.showerror('3D 预览', status.get('message', '预览启动失败。'), parent=self.root)
        if self.process.poll() is not None:
            if not self.loaded and not self._error_shown:
                messagebox.showerror('3D 预览', '预览进程未完成启动。请检查程序包是否完整，以及 Microsoft Edge WebView2 Runtime 是否已安装。', parent=self.root)
            self.close()
            return
        self.timer = self.root.after(400, self._poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            try:
                self.root.after_cancel(self.timer)
            except tk.TclError:
                pass
        try:
            self.root.unbind('<Destroy>', self._binding)
        except tk.TclError:
            pass
        if self.process and self.process.poll() is None:
            # The worker also watches the parent process, including os._exit().
            write_json(self.directory / 'command.json', {'action': 'close'})
            import threading
            def reap():
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                finally:
                    shutil.rmtree(self.directory, ignore_errors=True)
            threading.Thread(target=reap, daemon=True).start()
        else:
            shutil.rmtree(self.directory, ignore_errors=True)


def open_preview(app):
    try:
        scene = make_scene(app)
        session = getattr(app, '_transformer_preview', None)
        if session is not None and not session.closed and session.process.poll() is None:
            session.publish(scene)
            session.focus()
        else:
            app._transformer_preview = PreviewSession(app, scene)
        if hasattr(app, 'status_var'):
            app.status_var.set('已打开三维预览。重新计算后会更新绕组结构。')
    except (OSError, ValueError, tk.TclError) as exc:
        messagebox.showerror('3D 结构预览', str(exc), parent=app.root)


def refresh_preview(app):
    session = getattr(app, '_transformer_preview', None)
    if session is None or session.closed or session.process.poll() is not None:
        return
    try:
        session.publish(make_scene(app))
    except (OSError, ValueError, tk.TclError) as exc:
        # Preserve the last geometry while explicitly clearing its validity.
        old = json.loads(session._last or '{}')
        old['stale'] = True
        old['notes'] = ['当前输入待修正：' + str(exc)]
        old.pop('signature', None)
        old['signature'] = hashlib.sha256(json.dumps(old, sort_keys=True,
            ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
        session.publish(old)


def mark_preview_stale(app):
    """Electrical edits invalidate the old picture without rebuilding geometry."""
    session = getattr(app, '_transformer_preview', None)
    if session is None or session.closed or session.process.poll() is not None:
        return
    old = json.loads(session._last or '{}')
    if old.get('stale'):
        return
    old['stale'] = True
    old['notes'] = ['电气参数已修改：当前结构对应上一有效计算，新计算完成后自动更新。'] + old.get('notes', [])
    old.pop('signature', None)
    old['signature'] = hashlib.sha256(json.dumps(old, sort_keys=True,
        ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
    try:
        session.publish(old)
    except OSError:
        # The renderer may have just exited; its lifecycle poll owns the error.
        pass


def refresh_from_result(app, result):
    """Keep an open view current even when the magnetics page is not selected."""
    session = getattr(app, '_transformer_preview', None)
    if session is None or session.closed or session.process.poll() is not None:
        return
    transformer = (result.get('mag') or {}).get('transformer') or {}
    from winding_layout import transformer_windings
    app._winding_source = transformer_windings(result)
    app._winding_preview_state = dict(core=transformer.get('core'),
        gap=copy.deepcopy(transformer.get('gap_design')))
    if transformer.get('core'):
        refresh_preview(app)
    else:
        session.publish(dict(schema='power-transformer.preview.v1',
            core=dict(model='当前拓扑无变压器', family='', status='dimensions_pending', notes=[]),
            windings=[], notes=['当前拓扑没有变压器，已清空上一工程的装配。'],
            title='当前拓扑无变压器', signature='no-transformer'))

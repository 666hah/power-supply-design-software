"""Isolated, offline WebView2 host for the transformer geometry viewer.

Importing this module never loads .NET or opens a GUI. The worker consumes one
owned scene file; it does not expose a general filesystem or execution bridge.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import os
import sys
import threading
import time

MAX_SCENE_BYTES = 32 * 1024 * 1024
MAX_PNG_BYTES = 24 * 1024 * 1024


def read_scene(path):
    path = Path(path)
    if path.stat().st_size > MAX_SCENE_BYTES:
        raise ValueError('3D 场景超过预览大小限制，请减少单次显示的绕制规模。')
    value = json.loads(path.read_text('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('3D 场景必须是对象。')
    return value


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), 'utf-8')
    os.replace(temporary, path)


def decode_png(data_url):
    prefix = 'data:image/png;base64,'
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError('仅接受 PNG 预览截图。')
    if len(data_url) > MAX_PNG_BYTES * 4 // 3 + len(prefix) + 4:
        raise ValueError('截图文件过大。')
    try:
        data = base64.b64decode(data_url[len(prefix):], validate=True)
    except ValueError:
        raise ValueError('PNG 数据无效。') from None
    if len(data) > MAX_PNG_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG 数据无效。')
    return data


class ScreenshotAPI:
    def __init__(self):
        self._window = None

    def core_mesh(self, model):
        """Read only a shipped catalogue entry, never a browser-supplied path."""
        try:
            from core_mesh_library import get_core_mesh
            return get_core_mesh(model)
        except (OSError, ValueError) as exc:
            return {'error': str(exc)}

    def save_png(self, data_url):
        try:
            data = decode_png(data_url)
            import webview
            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE, save_filename='变压器3D结构.png',
                file_types=('PNG 图片 (*.png)',))
            if not selected:
                return {'saved': False}
            path = Path(selected[0] if isinstance(selected, (tuple, list)) else selected)
            if path.suffix.lower() != '.png':
                path = path.with_suffix('.png')
            path.write_bytes(data)
            return {'saved': True, 'path': str(path)}
        except (OSError, ValueError) as exc:
            return {'saved': False, 'error': str(exc)}


def _watch_parent(pid):
    """Return an alive check and disposer without sending signals to a parent."""
    if not pid:
        return lambda: True, lambda: None
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        return (lambda: bool(handle) and kernel.WaitForSingleObject(handle, 0) == 258,
                lambda: kernel.CloseHandle(handle) if handle else None)
    def alive():
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    return alive, lambda: None


def run(scene_path, *, parent_pid=0, hidden=False):
    from app_resources import resource_path
    scene_path = Path(scene_path).resolve(strict=True)
    root = scene_path.parent
    read_scene(scene_path)  # Fail before creating a native window for bad input.
    asset = resource_path('resources/transformer_preview/index.html').resolve(strict=True)
    cache_path = root / 'webview-cache'
    cache_path.mkdir(exist_ok=True)
    import webview
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    api = ScreenshotAPI()
    window = webview.create_window('变压器 3D 结构预览', url=asset.as_uri(),
        js_api=api, width=1320, height=860, min_size=(900, 620),
        background_color='#f0f4fa', text_select=False, hidden=hidden)
    api._window = window
    ready = threading.Event()
    closed = threading.Event()
    alive, dispose = _watch_parent(parent_pid)
    window.events.loaded += ready.set
    window.events.closed += closed.set

    def publish(value):
        # JSON is data, never interpolate raw labels into executable code.
        js = 'window.updateScene(' + json.dumps(value, ensure_ascii=True, allow_nan=False) + ')'
        window.evaluate_js(js)
        diagnostics = window.evaluate_js('window.previewDiagnostics()')
        if not diagnostics or not diagnostics.get('ready') or diagnostics.get('fatal'):
            raise ValueError((diagnostics or {}).get('fatal') or '三维显示未能初始化。')
        write_json(root / 'status.json', {'state': 'ready', 'diagnostics': diagnostics})

    def monitor():
        try:
            if not ready.wait(35):
                raise RuntimeError('3D 窗口未完成载入，请检查 Microsoft Edge WebView2 Runtime。')
            previous = scene_path.stat().st_mtime_ns
            publish(read_scene(scene_path))
            last_command = None
            while not closed.wait(.35):
                if not alive() or not scene_path.exists():
                    window.destroy()
                    break
                stamp = scene_path.stat().st_mtime_ns
                if stamp != previous:
                    publish(read_scene(scene_path))
                    previous = stamp
                command_file = root / 'command.json'
                if command_file.exists():
                    command = json.loads(command_file.read_text('utf-8'))
                    if command != last_command:
                        last_command = command
                        if command.get('action') == 'close':
                            window.destroy()
                            break
                        if command.get('action') == 'focus':
                            window.restore()
                            window.show()
        except Exception as exc:
            write_json(root / 'status.json', {'state': 'error', 'message': str(exc)})
            if not closed.is_set():
                window.destroy()
        finally:
            dispose()
    # The host uses file:// assets and a data-only Python bridge. No local
    # server, external CDN, Elmer or LTspice process is needed for previewing.
    webview.start(monitor, gui='edgechromium' if sys.platform == 'win32' else None,
                  debug=False, http_server=False, private_mode=True, storage_path=str(cache_path))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('scene')
    parser.add_argument('--parent-pid', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        return run(args.scene, parent_pid=args.parent_pid)
    except Exception as exc:
        message = ('3D 预览启动失败。请安装 Microsoft Edge WebView2 Runtime，'
                   '并使用包含完整 _internal 目录的程序包。\n' + str(exc))
        try:
            write_json(Path(args.scene).parent / 'status.json', {'state': 'error', 'message': message})
        except OSError:
            pass
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

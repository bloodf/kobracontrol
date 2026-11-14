"""Test-only model of the part of OrcaSlicer's plugin audit policy that real plugins trip over.

OrcaSlicer v2.5.0 installs a CPython audit hook (src/slic3r/plugin/PluginAuditManager.cpp, `audit_hook`,
lines ~2168-2213) and judges the events in `audit_event_categories` (lines ~52-136) against the plugin's
grants (docs/HLSD/plugin-permissions.md). This module installs a test hook (`sys.addaudithook`; hooks cannot be
removed, so it is switched with `enable()` / `disable()`) that applies, while enabled:

    plugin scope   an event counts as the plugin's when the current thread is not the main thread and a frame
                   of src/kobracontrol is on its stack (stands in for the scope the trampoline opens and the
                   `_thread.start_new_thread` shim carries into plugin threads, PythonPluginBridge.cpp).
                   Off the main thread a missing grant is DENIED at once (doc "Runtime prompts"): PermissionError.
    denied paths   any path component secret(s)/cert(s)/certificate(s)/conf/config, or a name ending .conf/.ini,
                   is refused before any grant (doc "Denied paths", install_hook's default_denied_path_keywords).
    open           read-only mode (no w/a/x/+; `open_category`, line ~1202) is FsRead, anything else (including
                   os.open, whose mode is None) FsReadWrite. Allowed: inside an allowed root (the plugin storage
                   folder stands in for data_dir(), read-write; the plugin's own source folder, read-only, stands
                   in for the plugin package inside data_dir()), a read of the standard library, or a matching
                   fs_read / fs_readwrite target.
    FsRead events  os.listdir, os.scandir, os.walk: as a read of their path.
    FsCreate       os.mkdir, tempfile.mkstemp, tempfile.mkdtemp: only inside an allowed root (no grant list).
    FsDelete       os.remove, os.rmdir: only inside an allowed root.
    network        urllib.Request (by URL host), http.client.connect, socket.getaddrinfo, socket.connect (by host):
                   allowed when the host is in the declared `network` grants (normalised scheme://host, any port).
    process        subprocess.Popen: str(args) must equal a declared `process` target verbatim.
    targets        "<dir>/*" is a tree (the folder and everything below, both sides canonicalised with realpath);
                   anything else is an exact path (also matched by its realpath).

NOT modelled: the main thread's inline prompts (main-thread events are always allowed here), saved runtime
grants, full access, the granted-operation frame coverage for nested standard-library events (doc "Decision
order" step 2), resources_dir(), the denied file names (OrcaSlicer.conf, .install_state.json, ...), events
outside the list above (shutil.*, os.rename, os.chmod, socket.__new__, http.client.send, threading, ...), and
Windows path rules.
"""

import os
import sys
import sysconfig
import threading
import urllib.parse

SRC = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "kobracontrol"))
DENIED = {"secret", "secrets", "cert", "certs", "certificate", "certificates", "conf", "config"}
STDLIB = {os.path.realpath(p) for p in (sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"])}

_state = {"enabled": False, "fs_read": [], "fs_readwrite": [], "network": [], "process": [], "roots": [],
          "denials": []}
_installed = False


def enable(permissions, storage):
    """permissions: the kwargs plugin.py passed to orca.request_permissions; storage: the plugin storage folder."""
    _install()
    _state.update(fs_read=list(permissions.get("fs_read") or []), fs_readwrite=list(permissions.get("fs_readwrite") or []),
                  network=[_host(t) for t in permissions.get("network") or []] + list(permissions.get("network_socket") or []),
                  process=list(permissions.get("process") or []), roots=[os.path.realpath(storage)], denials=[])
    _state["enabled"] = True


def disable():
    _state["enabled"] = False


def denials():
    """[(event, target)] denied since enable()."""
    return list(_state["denials"])


def _install():
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def _host(target):
    text = str(target)
    return (urllib.parse.urlsplit(text).hostname or "") if "://" in text else text.rsplit(":", 1)[0]


def _in_scope():
    if threading.current_thread() is threading.main_thread():
        return False
    frame = sys._getframe(1)
    while frame is not None:
        if os.path.realpath(frame.f_code.co_filename).startswith(SRC + os.sep):
            return True
        frame = frame.f_back
    return False


def _inside(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _matches(path, targets):
    real = os.path.realpath(path)
    for t in targets:
        if t.endswith("/*"):
            if _inside(real, os.path.realpath(t[:-2])):
                return True
        elif path == t or real == os.path.realpath(t):
            return True
    return False


def _denied_name(path):
    parts = [p.lower() for p in os.path.realpath(path).split(os.sep) if p]
    return any(p in DENIED or p.endswith((".conf", ".ini")) for p in parts)


def _fs(path, write):
    if _denied_name(path):
        return False
    real = os.path.realpath(path)
    if any(_inside(real, r) for r in _state["roots"]):
        return True
    if not write and (_inside(real, SRC) or any(_inside(real, s) for s in STDLIB)):
        return True
    return _matches(path, _state["fs_readwrite" if write else "fs_read"])


def _create(path):
    return not _denied_name(path) and any(_inside(os.path.realpath(path), r) for r in _state["roots"])


def _decide(event, args):
    """None when the event is not judged, else (allowed, target)."""
    if event == "open":
        path, mode = args[0], args[1] if len(args) > 1 else None
        if not isinstance(path, (str, bytes, os.PathLike)):
            return None
        path = os.fsdecode(path)
        write = not mode or any(c in str(mode) for c in "wax+")
        return _fs(path, write), path
    if event in ("os.listdir", "os.scandir", "os.walk"):
        path = os.fsdecode(args[0]) if args and isinstance(args[0], (str, bytes, os.PathLike)) else "."
        return _fs(path, False), path
    if event in ("os.mkdir", "tempfile.mkstemp", "tempfile.mkdtemp", "os.remove", "os.rmdir"):
        path = os.fsdecode(args[0])
        return _create(path), path
    if event == "urllib.Request":
        host = urllib.parse.urlsplit(args[0]).hostname or ""
        return host in _state["network"], args[0]
    if event == "http.client.connect":
        return str(args[1]) in _state["network"], str(args[1])
    if event == "socket.getaddrinfo":
        return str(args[0]) in _state["network"], str(args[0])
    if event == "socket.connect":
        address = args[1]
        host = address[0] if isinstance(address, tuple) else str(address)
        if isinstance(address, str):   # AF_UNIX
            return None
        return host in _state["network"], host
    if event == "subprocess.Popen":
        return str(args[1]) in _state["process"], str(args[1])
    return None


_busy = threading.local()   # the hook's own work (sys._getframe, realpath, ...) raises audit events too


def _hook(event, args):
    if not _state["enabled"] or getattr(_busy, "on", False):
        return
    _busy.on = True
    try:
        decision = _decide(event, args) if _in_scope() else None
    finally:
        _busy.on = False
    if decision is None or decision[0]:
        return
    _state["denials"].append((event, decision[1]))
    raise PermissionError("kobracontrol test audit guard denied %s %r" % (event, decision[1]))

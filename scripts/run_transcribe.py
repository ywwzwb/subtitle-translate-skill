#!/usr/bin/env python3
"""Run the Qwen3-ASR transcribe tool and produce .txt/.srt/.json outputs.

The .json output is a word-level timestamp list [{text, start, end}]
(seconds), matching the input format of timestamp_to_yaml.py.

Executable path resolution (highest priority first):
    1. --exe argument
    2. TRANSCRIBE_EXE environment variable
    3. auto-download the q3asr runtime (default)

If no --exe/TRANSCRIBE_EXE is given, the q3asr runtime is auto-downloaded from
the ASR repo release manifest into ~/.cache/opencode-translate/asr/. The best
backend for this machine is probed (cuda->vulkan->metal->cpu), cached in
<skill_dir>/config.yaml (like terminology.yaml) and reused on later runs.
Overrides: TRANSCRIBE_BACKEND (cuda/vulkan/metal/cpu), TRANSCRIBE_MODEL
(default 1.7b), TRANSCRIBE_ASR_VER (default latest).

Timestamps from a --seek-start/--duration run are RELATIVE to the segment
start; use timestamp_to_yaml.py --offset to restore absolute times.

On Windows, transcribe.exe (a PyInstaller app) is launched in a fresh real
console (CREATE_NEW_CONSOLE) because its bundled Python uses the GBK codec
and crashes with UnicodeEncodeError whenever stdout/stderr is a pipe; a real
console uses WriteConsoleW so emoji/Chinese output never crashes.

Usage:
    python run_transcribe.py audio.mp3 [-y]
    python run_transcribe.py audio.mp3 --seek-start 1140 --duration 30 -y
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

ASR_REPO = 'ywwzwb/qwen3-asr-universal'
CACHE_ROOT = Path(os.environ.get('TRANSCRIBE_CACHE',
                                 Path.home() / '.cache' / 'opencode-translate' / 'asr'))
SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / 'config.yaml'

_OS_MAP = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}


def os_arch() -> tuple:
    os_name = _OS_MAP.get(platform.system(), platform.system().lower())
    m = platform.machine().lower()
    arch = 'arm64' if m in ('aarch64', 'arm64') else ('x64' if m in ('amd64', 'x86_64', 'x64') else m)
    return os_name, arch


def fetch_manifest(version='latest') -> dict:
    if version == 'latest':
        url = f'https://api.github.com/repos/{ASR_REPO}/releases/latest'
    else:
        url = f'https://api.github.com/repos/{ASR_REPO}/releases/tags/{version}'
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.load(r)
    for a in d['assets']:
        if a['name'] == 'manifest.json':
            murl = a['browser_download_url']
            with urllib.request.urlopen(murl, timeout=60) as r2:
                return json.load(r2)
    raise RuntimeError('release has no manifest.json')


def probe_backend() -> str:
    """Best backend this machine can run (cheapest reliable check).
    Returns 'cuda' | 'vulkan' | 'metal' | 'cpu'."""
    if platform.system() == 'Darwin':
        return 'metal'
    if shutil.which('nvidia-smi'):
        return 'cuda'
    if shutil.which('vulkaninfo'):
        return 'vulkan'
    return 'cpu'


def verify_backend(backend: str) -> bool:
    """Lightweight re-check that a saved backend still applies (handles a
    stale config.yaml copied to a different machine)."""
    if backend == 'cuda':
        return shutil.which('nvidia-smi') is not None
    if backend == 'vulkan':
        return shutil.which('vulkaninfo') is not None
    if backend == 'metal':
        return platform.system() == 'Darwin'
    if backend == 'cpu':
        return True
    return False


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return cfg.get('config', {}) if isinstance(cfg, dict) else {}


def save_config(**kw) -> None:
    cfg = load_config()
    cfg.update({k: v for k, v in kw.items() if v is not None})
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.safe_dump({'config': cfg}, f, allow_unicode=True, sort_keys=False)
    except OSError:
        pass  # read-only skill dir; probing still works per-run


def resolve_backend() -> str:
    """Backend to use: TRANSCRIBE_BACKEND > saved config > probe (saved)."""
    env = os.environ.get('TRANSCRIBE_BACKEND')
    if env and env != 'auto':
        return env
    saved = load_config().get('backend')
    if saved and verify_backend(saved):
        return saved
    b = probe_backend()
    save_config(backend=b)
    return b


def resolve_model() -> str:
    """Model to use: TRANSCRIBE_MODEL > saved config > '1.7b' (saved)."""
    env = os.environ.get('TRANSCRIBE_MODEL')
    if env:
        return env
    saved = load_config().get('model')
    if saved:
        return saved
    save_config(model='1.7b')
    return '1.7b'


def select_asset(manifest: dict, os_name: str, arch: str, backend: str) -> dict:
    assets = manifest['assets']
    cands = [a for a in assets if a['os'] == os_name and a['arch'] == arch]
    if not cands:
        raise RuntimeError(f'no asset for {os_name}-{arch}')
    for a in cands:
        if a['backend'] == backend:
            return a
    for a in cands:
        if a['backend'] == 'cpu':
            return a
    raise RuntimeError(f'no asset for {os_name}-{arch} (wanted backend {backend})')


def _download(url, dest):
    tmp = dest.with_suffix(dest.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, 'wb') as f:
            shutil.copyfileobj(resp, f, length=1 << 20)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def install_asset(cache: Path, zip_path: Path, cli_name: str, sha256=None) -> Path:
    if sha256:
        got = hashlib.file_digest(zip_path.open('rb'), 'sha256').hexdigest()
        if got != sha256:
            raise RuntimeError(f'sha256 mismatch: {zip_path}')
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(cache)
    exe = cache / cli_name
    if not exe.exists():
        raise RuntimeError(f'cli not found in zip: {cli_name}')
    return exe


def ensure_auto_exe(backend='auto', version='latest') -> tuple:
    """Return (exe_path, backend_name). Resolves backend via resolve_backend()
    when 'auto', downloads + verifies + extracts if not already cached."""
    os_name, arch = os_arch()
    if backend == 'auto':
        backend = resolve_backend()
    man = fetch_manifest(version)
    asset = select_asset(man, os_name, arch, backend)
    cache = CACHE_ROOT / version
    exe = cache / asset['cli']
    if exe.exists():
        return str(exe), asset['backend']
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / asset['filename']
    url = (f'https://github.com/{ASR_REPO}/releases/download/'
           f'{man["version"]}/{asset["filename"]}')
    _download(url, zip_path)
    exe = install_asset(cache, zip_path, asset['cli'], asset['sha256'])
    zip_path.unlink(missing_ok=True)
    return str(exe), asset['backend']


def resolve_exe(exe=None):
    if exe:
        return exe
    env = os.environ.get('TRANSCRIBE_EXE')
    if env:
        return env
    return None


def build_cmd(exe, audio, seek_start=None, duration=None, language=None,
              prec=None, no_dml=False, no_vulkan=False, yes=False,
              device=None, model=None):
    cmd = [exe, audio]
    if yes:
        cmd.append('-y')
    if seek_start is not None:
        cmd += ['--seek-start', str(seek_start)]
    if duration is not None:
        cmd += ['--duration', str(duration)]
    if language:
        cmd += ['--language', language]
    if prec:
        cmd += ['--prec', prec]
    if no_dml:
        cmd.append('--no-dml')
    if no_vulkan:
        cmd.append('--no-vulkan')
    if device:
        cmd += ['--device', device]
    if model:
        cmd += ['--model', model]
    return cmd


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='audio file (mp3/wav/...)')
    ap.add_argument('--exe', help='override transcribe executable path')
    ap.add_argument('--seek-start', type=float, help='start second to transcribe')
    ap.add_argument('--duration', type=float, help='how many seconds to transcribe')
    ap.add_argument('--language', '-l', help='force language (e.g. Chinese, English)')
    ap.add_argument('--prec', help='encoder precision: fp32/fp16/int8/int4')
    ap.add_argument('--no-dml', action='store_true', help='disable DirectML')
    ap.add_argument('--no-vulkan', action='store_true', help='disable Vulkan')
    ap.add_argument('--yes', '-y', action='store_true', help='overwrite existing outputs')
    args = ap.parse_args()

    exe = resolve_exe(args.exe)
    is_q3asr = False
    device = None
    model = None
    if not exe or not os.path.isfile(exe):
        if not args.exe and not os.environ.get('TRANSCRIBE_EXE'):
            backend = resolve_backend()
            model = resolve_model()
            version = os.environ.get('TRANSCRIBE_ASR_VER', 'latest')
            try:
                exe, backend_name = ensure_auto_exe(backend=backend, version=version)
            except Exception as e:
                sys.exit(f'error: no transcribe executable and auto-download failed\n'
                         f'Set the TRANSCRIBE_EXE environment variable or pass --exe.\n'
                         f'auto-download from {ASR_REPO} failed: {e}')
            is_q3asr = True
            device = backend
            print(f'auto-downloaded q3asr runtime ({backend_name}, model {model}, {version}): {exe}')
        else:
            sys.exit(f'error: transcribe executable not found: {exe}\n'
                     f'Set the TRANSCRIBE_EXE environment variable or pass --exe.')
    exe = os.path.abspath(exe)

    cmd = build_cmd(exe, args.input, args.seek_start, args.duration,
                    args.language, args.prec, args.no_dml, args.no_vulkan, args.yes,
                    device=device if is_q3asr else None,
                    model=model if is_q3asr else None)
    print('running:', ' '.join(cmd))
    workdir = os.path.dirname(os.path.abspath(args.input)) or '.'
    if os.name == 'nt':
        proc = subprocess.run(cmd, cwd=workdir,
                              creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        proc = subprocess.run(cmd, cwd=workdir)
    if proc.returncode != 0 and is_q3asr and device != 'cpu':
        print(f'q3asr failed with {device} backend; retrying on cpu', file=sys.stderr)
        cmd = build_cmd(exe, args.input, args.seek_start, args.duration,
                        args.language, args.prec, args.no_dml, args.no_vulkan, args.yes,
                        device='cpu', model=model)
        print('running:', ' '.join(cmd))
        if os.name == 'nt':
            proc = subprocess.run(cmd, cwd=workdir,
                                  creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.run(cmd, cwd=workdir)
    if proc.returncode != 0:
        log = os.path.join(os.path.dirname(exe), 'logs', 'latest.log')
        if os.path.isfile(log):
            with open(log, encoding='utf-8', errors='replace') as f:
                tail = f.readlines()[-30:]
            print('--- logs/latest.log tail ---', file=sys.stderr)
            print(''.join(tail), file=sys.stderr)
        sys.exit(f'error: transcribe failed with code {proc.returncode}')
    print('transcribe OK')


if __name__ == '__main__':
    main()

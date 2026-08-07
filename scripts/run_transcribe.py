#!/usr/bin/env python3
"""Run the Qwen3-ASR transcribe tool and produce .txt/.srt/.json outputs.

The .json output is a word-level timestamp list [{text, start, end}]
(seconds), matching the input format of timestamp_to_yaml.py.

Executable path resolution (highest priority first):
    1. --exe argument
    2. TRANSCRIBE_EXE environment variable
    3. DEFAULT_EXE (hardcoded below)

If no --exe/TRANSCRIBE_EXE is given and DEFAULT_EXE does not exist, the
q3asr runtime is auto-downloaded from the ASR repo release manifest into
~/.cache/opencode-translate/asr/ (backend from TRANSCRIBE_BACKEND,
default auto: cuda->vulkan->metal->cpu; version from TRANSCRIBE_ASR_VER).

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

DEFAULT_EXE = r'C:\Users\zwb\Documents\Qwen3-ASR-Transcribe\transcribe.exe'

ASR_REPO = 'ywwzwb/qwen3-asr-universal'
CACHE_ROOT = Path(os.environ.get('TRANSCRIBE_CACHE',
                                 Path.home() / '.cache' / 'opencode-translate' / 'asr'))

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


def _cuda_available():
    if platform.system() == 'Darwin':
        return False
    return shutil.which('nvidia-smi') is not None


def select_asset(manifest: dict, os_name: str, arch: str, backend: str) -> dict:
    assets = manifest['assets']
    cands = [a for a in assets if a['os'] == os_name and a['arch'] == arch]
    if not cands:
        raise RuntimeError(f'no asset for {os_name}-{arch}')
    if backend != 'auto':
        for a in cands:
            if a['backend'] == backend:
                return a
        raise RuntimeError(f'no {backend} asset for {os_name}-{arch}; have {[a["backend"] for a in cands]}')
    # auto: pick the fastest backend this machine can actually run.
    # - macOS: Metal is always present.
    # - Windows/Linux: CUDA only if nvidia-smi exists; otherwise CPU (always
    #   works). Vulkan is opt-in via TRANSCRIBE_BACKEND (hard to detect).
    if os_name == 'macos':
        order = ('metal', 'cpu')
    else:
        order = ('cuda', 'cpu') if _cuda_available() else ('cpu',)
    for b in order:
        for a in cands:
            if a['backend'] == b:
                return a
    raise RuntimeError(f'no asset for {os_name}-{arch}')


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
    """Return (exe_path, backend_name)."""
    os_name, arch = os_arch()
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
    return DEFAULT_EXE


def build_cmd(exe, audio, seek_start=None, duration=None, language=None,
              prec=None, no_dml=False, no_vulkan=False, yes=False):
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
    if not os.path.isfile(exe):
        if not args.exe and not os.environ.get('TRANSCRIBE_EXE'):
            backend = os.environ.get('TRANSCRIBE_BACKEND', 'auto')
            version = os.environ.get('TRANSCRIBE_ASR_VER', 'latest')
            try:
                exe, backend_name = ensure_auto_exe(backend=backend, version=version)
            except Exception as e:
                sys.exit(f'error: transcribe executable not found: {exe}\n'
                         f'Set the TRANSCRIBE_EXE environment variable or pass --exe.\n'
                         f'auto-download from {ASR_REPO} failed: {e}')
            print(f'auto-downloaded q3asr runtime ({backend_name}, {version}): {exe}')
        else:
            sys.exit(f'error: transcribe executable not found: {exe}\n'
                     f'Set the TRANSCRIBE_EXE environment variable or pass --exe.')
    exe = os.path.abspath(exe)

    cmd = build_cmd(exe, args.input, args.seek_start, args.duration,
                    args.language, args.prec, args.no_dml, args.no_vulkan, args.yes)
    print('running:', ' '.join(cmd))
    workdir = os.path.dirname(os.path.abspath(args.input)) or '.'
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

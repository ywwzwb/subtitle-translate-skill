#!/usr/bin/env python3
"""Run the Qwen3-ASR transcribe tool and produce .txt/.srt/.json outputs.

The .json output is a word-level timestamp list [{text, start, end}]
(seconds), matching the input format of timestamp_to_yaml.py.

Executable path resolution (highest priority first):
    1. --exe argument
    2. TRANSCRIBE_EXE environment variable
    3. DEFAULT_EXE (hardcoded below)

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
import os
import subprocess
import sys

DEFAULT_EXE = r'C:\Users\zwb\Documents\Qwen3-ASR-Transcribe\transcribe.exe'


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

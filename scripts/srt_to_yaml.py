#!/usr/bin/env python3
"""Convert an SRT subtitle file into the main.yaml format used by the
translating-subtitles skill.

Usage:
    python3 srt_to_yaml.py input.srt [output.yaml]

Output schema (literal block scalars):
    main:
      - from: HH:MM:SS,mmm
        to: HH:MM:SS,mmm
        en: |
          <original subtitle text, line breaks preserved>
"""
import re
import sys


def normalize_ts(ts):
    ts = ts.replace('.', ',')
    hhmmss, ms = ts.split(',')
    h, m, s = hhmmss.split(':')
    return f'{int(h):02d}:{int(m):02d}:{int(s):02d},{ms.ljust(3, "0")[:3]}'


def parse_srt(path):
    with open(path, encoding='utf-8-sig') as f:
        content = f.read().replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.split('\n')
        if re.fullmatch(r'\d{1,4}', lines[0].strip()):
            lines = lines[1:]
        if not lines:
            continue
        m = re.match(
            r'(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})',
            lines[0],
        )
        if not m:
            continue
        text = '\n'.join(lines[1:]).strip()
        if text:
            cues.append({'from': normalize_ts(m.group(1)),
                         'to': normalize_ts(m.group(2)),
                         'en': text})
    return cues


def emit_yaml(cues):
    out = ['main:']
    for c in cues:
        out.append(f'  - from: {c["from"]}')
        out.append(f'    to: {c["to"]}')
        out.append('    en: |')
        for line in c['en'].split('\n'):
            out.append(f'        {line.rstrip()}')
        out.append('')
    return '\n'.join(out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else 'main.yaml'
    cues = parse_srt(src)
    if not cues:
        print(f'error: no cues parsed from {src}', file=sys.stderr)
        sys.exit(1)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(emit_yaml(cues))
    print(f'{len(cues)} cues -> {dst}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Merge main.yaml (main + annotations) into an ASS file with three tracks.

Usage:
    python3 yaml_to_ass.py main.yaml [output.ass]

Input schema:
    main:
      - from: HH:MM:SS,mmm
        to: HH:MM:SS,mmm
        en: |...
        chs: |...           # optional; falls back to en
    annotations:
      - from: HH:MM:SS,mmm
        text: ...           # <=20 chars; to is auto-computed at ~4 chars/sec

Output: three separate tracks (each its own Layer + Style), so styles can be
adjusted later per track:
    Layer 0 / Style Translation  — Simplified Chinese, fs56, bottom (main line)
    Layer 1 / Style Original     — original-language text, fs36, just above it
    Layer 2 / Style Annotation   — top-left corner, fs26

Annotation timing:
    - Duration = text length / 4 chars per second.
    - Annotations sharing the same start time (one sentence, several terms)
      are merged into a single event, lines stacked with \\N.
    - If an annotation's end would reach the next annotation's start, the end
      is clamped to just before that start so they never overlap.
"""
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit('error: PyYAML is required (pip install pyyaml)')

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Translation,Noto Sans CJK SC,56,&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,80,80,81,1
Style: Original,Noto Sans CJK SC,36,&H00FFFFFF,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,80,80,45,1
Style: Annotation,Noto Sans CJK SC,26,&H00FFE066,&H000000FF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,1,1,7,40,40,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts_to_ms(ts):
    ts = ts.replace('.', ',')
    hhmmss, ms = ts.split(',')
    h, m, s = hhmmss.split(':')
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def ms_to_ass(ms):
    return (f'{ms // 3600000}:{ms % 3600000 // 60000:02d}'
            f':{ms % 60000 // 1000:02d}.{ms % 1000 // 10:02d}')


def text_len(t):
    return len(re.sub(r'\s+', '', t))


def build_annotation_events(annotations):
    anns = [{'start': ts_to_ms(a['from']),
             'end': ts_to_ms(a['from']) + int(text_len(a['text']) * 1000 / 4),
             'text': a['text'].replace('\n', r'\N')}
            for a in annotations]
    anns.sort(key=lambda a: (a['start'], a['end']))

    events = []
    i = 0
    while i < len(anns):
        j = i
        while j + 1 < len(anns) and anns[j + 1]['start'] == anns[i]['start']:
            j += 1
        start = anns[i]['start']
        end = max(a['end'] for a in anns[i:j + 1])
        text = r'\N'.join(a['text'] for a in anns[i:j + 1])
        if j + 1 < len(anns) and end >= anns[j + 1]['start']:
            end = anns[j + 1]['start'] - 1
        events.append((start, 2,
                       f'Dialogue: 2,{ms_to_ass(start)},{ms_to_ass(end)},'
                       f'Annotation,,0,0,0,,{text}'))
        i = j + 1
    return events


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else 'output.ass'
    with open(src, encoding='utf-8') as f:
        data = yaml.safe_load(f)

    events = []
    for item in data.get('main', []):
        chs = (item.get('chs') or '').strip()
        en = (item.get('en') or '').strip()
        start_ms = ts_to_ms(item['from'])
        start = ms_to_ass(start_ms)
        end = ms_to_ass(ts_to_ms(item['to']))
        if chs:
            chs = chs.replace(chr(10), r'\N')
            events.append((start_ms, 0,
                           f'Dialogue: 0,{start},{end},Translation,,0,0,0,,'
                           f'{chs}'))
        if en:
            en = en.replace(chr(10), r'\N')
            events.append((start_ms, 1,
                           f'Dialogue: 1,{start},{end},Original,,0,0,0,,'
                           f'{en}'))

    events.extend(build_annotation_events(data.get('annotations', [])))
    events.sort(key=lambda e: (e[0], e[1]))

    with open(dst, 'w', encoding='utf-8') as f:
        f.write(HEADER)
        for _, _, line in events:
            f.write(line + '\n')
    print(f'{len(events)} events -> {dst}')


if __name__ == '__main__':
    main()

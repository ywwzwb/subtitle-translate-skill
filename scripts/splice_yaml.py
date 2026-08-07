#!/usr/bin/env python3
"""Splice a re-transcribed segment back into main.yaml (non-destructive).

Replaces every main cue whose time interval intersects the segment window
[seg.first.from, seg.last.to] with the segment's cues, preserving all other
cues and the annotations list. Always writes to a NEW output file.

Usage:
    python splice_yaml.py main.yaml segment.yaml out.yaml [--dry-run]

If the inserted word count is below 50% of the deleted word count, a
warning is printed (the re-transcription may have missed words).
"""
import argparse
import sys


def ts_to_ms(ts):
    ts = ts.replace('.', ',')
    hhmmss, ms = ts.split(',')
    h, m, s = hhmmss.split(':')
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def intersect(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def word_count(cue):
    return len(str(cue.get('en', '')).split())


def splice(data, seg_cues):
    main_cues = data.get('main', [])
    if not seg_cues:
        raise ValueError('segment has no cues')
    sorted_cues = sorted(seg_cues, key=lambda c: ts_to_ms(c['from']))
    seg_start = ts_to_ms(sorted_cues[0]['from'])
    seg_end = ts_to_ms(sorted_cues[-1]['to'])
    deleted = [c for c in main_cues
               if intersect(ts_to_ms(c['from']), ts_to_ms(c['to']),
                            seg_start, seg_end)]
    kept = [c for c in main_cues if c not in deleted]
    merged = kept + seg_cues
    merged.sort(key=lambda c: ts_to_ms(c['from']))
    new_data = dict(data)
    new_data['main'] = merged
    deleted_words = sum(word_count(c) for c in deleted)
    inserted_words = sum(word_count(c) for c in seg_cues)
    warn = inserted_words < deleted_words * 0.5
    return new_data, len(deleted), len(seg_cues), warn, deleted


def to_yaml(data):
    out = ['main:']
    for c in data.get('main', []):
        out.append(f'  - from: {c["from"]}')
        out.append(f'    to: {c["to"]}')
        out.append('    en: |')
        for line in str(c.get('en', '')).split('\n'):
            out.append(f'        {line}')
        chs = c.get('chs')
        if chs:
            out.append('    chs: |')
            for line in str(chs).split('\n'):
                out.append(f'        {line}')
        out.append('')
    if data.get('annotations'):
        out.append('annotations:')
        for a in data['annotations']:
            out.append(f'  - from: {a["from"]}')
            out.append(f'    text: {a["text"]}')
    return '\n'.join(out)


def main():
    try:
        import yaml
    except ImportError:
        sys.exit('error: PyYAML is required (pip install pyyaml)')

    ap = argparse.ArgumentParser()
    ap.add_argument('main_yaml')
    ap.add_argument('segment_yaml')
    ap.add_argument('output')
    ap.add_argument('--dry-run', action='store_true',
                    help='only print which cues would be replaced')
    args = ap.parse_args()

    with open(args.main_yaml, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    with open(args.segment_yaml, encoding='utf-8') as f:
        seg = yaml.safe_load(f)
    seg_cues = seg.get('main', [])

    new_data, deleted, inserted, warn, deleted_cues = splice(data, seg_cues)
    print(f'deleted {deleted} cues, inserted {inserted} cues')
    if args.dry_run:
        for c in deleted_cues:
            print(f'{c["from"]} -> {c["to"]}: {c.get("en", "")}')
    if warn:
        print('WARNING: inserted word count < 50% of deleted — '
              'the re-transcription may have missed words. '
              'Review before committing.')
    if not args.dry_run:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(to_yaml(new_data))
        print(f'wrote {args.output}')


if __name__ == '__main__':
    main()

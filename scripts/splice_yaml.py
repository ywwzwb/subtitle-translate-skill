#!/usr/bin/env python3
"""Splice a re-transcribed segment back into main.yaml (non-destructive).

Replaces every main cue whose time interval intersects the deletion window
with the segment's cues, preserving all other cues and the annotations list.
Always writes to a NEW output file.

The deletion window is the REQUESTED re-transcription window
(--seek-start/--duration, matching run_transcribe.py), NOT the segment's
actual content range — if the ASR output was truncated at the tail, using the
content range would silently drop main cues in the un-transcribed tail.

Safety checks:
  * coverage: if --seek-start/--duration are given and the segment's content
    does not reach ~1s of the window end (or starts beyond ~1s of the window
    start), the re-transcription is considered truncated -> error (--force to
    override).
  * loss: every deleted cue whose (normalized) text is not found in the
    inserted segment text is printed as a LOSS line. Truncated segments are
    already rejected by the coverage check; a LOSS warning means the segment
    may have rephrased or skipped a deleted cue's content — review it.
  * the deleted cue list is always printed so every splice is auditable.

Usage:
    python splice_yaml.py main.yaml segment.yaml out.yaml [--dry-run]
    python splice_yaml.py main.yaml segment.yaml out.yaml --seek-start 1077 --duration 59
    python splice_yaml.py main.yaml segment.yaml out.yaml --seek-start 1077 --duration 59 --dry-run
    python splice_yaml.py main.yaml segment.yaml out.yaml --force
"""
import argparse
import re
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


def norm_text(s):
    """Normalize a cue/segment text for loss matching (lowercase words)."""
    return ' '.join(re.findall(r'[a-z0-9]+', str(s).lower()))


def splice(data, seg_cues, window_start_ms=None, window_end_ms=None):
    main_cues = data.get('main', [])
    if not seg_cues:
        raise ValueError('segment has no cues')
    sorted_cues = sorted(seg_cues, key=lambda c: ts_to_ms(c['from']))
    seg_start = ts_to_ms(sorted_cues[0]['from'])
    seg_end = ts_to_ms(sorted_cues[-1]['to'])
    # Deletion window: the REQUESTED re-transcription window if provided, else
    # the segment's actual content range (less safe).
    del_start = window_start_ms if window_start_ms is not None else seg_start
    del_end = window_end_ms if window_end_ms is not None else seg_end
    deleted = [c for c in main_cues
               if intersect(ts_to_ms(c['from']), ts_to_ms(c['to']),
                            del_start, del_end)]
    kept = [c for c in main_cues if c not in deleted]
    merged = kept + seg_cues
    merged.sort(key=lambda c: ts_to_ms(c['from']))
    new_data = dict(data)
    new_data['main'] = merged
    deleted_words = sum(word_count(c) for c in deleted)
    inserted_words = sum(word_count(c) for c in seg_cues)
    warn = inserted_words < deleted_words * 0.5
    return new_data, len(deleted), len(seg_cues), warn, deleted


def find_losses(deleted_cues, seg_cues):
    """Deleted cues whose content is absent from the inserted segment text.

    Zero-duration 'ghost' cues (spaces/punctuation artifacts with from==to)
    are skipped — removing them is expected.
    """
    seg_text = ' ' + norm_text(' '.join(c.get('en', '') for c in seg_cues)) + ' '
    losses = []
    for c in deleted_cues:
        if ts_to_ms(c['from']) >= ts_to_ms(c['to']):
            continue
        t = norm_text(c.get('en', ''))
        if t and t not in seg_text:
            losses.append(c)
    return losses


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
    ap.add_argument('--seek-start', type=float,
                    help='re-transcription start in seconds (match run_transcribe.py --seek-start)')
    ap.add_argument('--duration', type=float,
                    help='re-transcription duration in seconds (match run_transcribe.py --duration)')
    ap.add_argument('--dry-run', action='store_true',
                    help='only print what would change, do not write output')
    ap.add_argument('--force', action='store_true',
                    help='proceed despite a truncated segment coverage check')
    args = ap.parse_args()

    with open(args.main_yaml, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    with open(args.segment_yaml, encoding='utf-8') as f:
        seg = yaml.safe_load(f)
    seg_cues = seg.get('main', [])

    window_start_ms = window_end_ms = None
    if args.seek_start is not None and args.duration is not None:
        window_start_ms = int(round(args.seek_start * 1000))
        window_end_ms = int(round((args.seek_start + args.duration) * 1000))
    elif args.seek_start is not None or args.duration is not None:
        sys.exit('error: --seek-start and --duration must be given together')

    new_data, deleted, inserted, warn, deleted_cues = splice(
        data, seg_cues, window_start_ms, window_end_ms)

    # Coverage check: the segment must cover the requested window.
    if window_start_ms is not None:
        sorted_cues = sorted(seg_cues, key=lambda c: ts_to_ms(c['from']))
        seg_start = ts_to_ms(sorted_cues[0]['from'])
        seg_end = ts_to_ms(sorted_cues[-1]['to'])
        tail_gap = window_end_ms - seg_end
        head_gap = seg_start - window_start_ms
        if tail_gap > 1000 or head_gap > 1000:
            msg = (f'error: segment covers {seg_start / 1000:.2f}s..{seg_end / 1000:.2f}s '
                   f'but the requested window is {args.seek_start:.2f}s..'
                   f'{args.seek_start + args.duration:.2f}s '
                   f'(truncated by {max(tail_gap, head_gap) / 1000:.2f}s). '
                   f'Re-transcribe with a wider window, or pass --force to continue.')
            if not args.force:
                print(msg, file=sys.stderr)
                sys.exit(1)
            print(f'WARNING: {msg}', file=sys.stderr)

    print(f'deleted {deleted} cues, inserted {inserted} cues')
    if deleted_cues:
        print('deleted cues:')
        for c in deleted_cues:
            print(f'  {c["from"]} -> {c["to"]}: {c.get("en", "")}')

    losses = find_losses(deleted_cues, seg_cues)
    if losses:
        print('LOSS: cues deleted but their content was not found in the re-transcription:')
        for c in losses:
            print(f'  {c["from"]} -> {c["to"]}: {c.get("en", "")}')
        print('Review these — if they were good sentences, re-transcribe with a wider '
              'window (they are probably truncated, not lost).')

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

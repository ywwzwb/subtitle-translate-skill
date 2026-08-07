#!/usr/bin/env python3
"""Convert a word-level timestamped JSON (e.g. whisper/ASR output) into the
main.yaml format used by the translating-subtitles skill.

Input JSON is a list of word tokens:
    [{"text": "On", "start": 21.36, "end": 21.52}, ...]
Times are floats in seconds. Whitespace/punctuation may appear as their own
tokens (e.g. " ", ". ", ", ").

Steps:
  1. Reconstruct the transcript by concatenating all token texts (spaces and
     punctuation tokens included).
  2. Segment into sentences at sentence-final punctuation (. ! ? …) or at
     long silences (gap between consecutive words >= --gap seconds).
  3. Any sentence whose estimated on-screen width exceeds --max-width units
     is split into two or more fragments at soft delimiters (, ; : 、).
     Width estimate: CJK char = 1.0, latin/digit = 0.6, space = 0.25.
  4. Short fragments are merged back into the sentence: a fragment narrower
     than 0.6 * max-width is joined to its neighbour (forward when it ends
     with a soft delimiter, else backward), up to a combined width of
     1.6 * max-width. A single-fragment sentence with no terminal
     punctuation (an orphan cut off by an ASR pause) is merged into the next
     sentence, but only across a silence shorter than --merge-gap — a longer
     pause is a real beat and stays separate. Complete short utterances
     ("Cheese.", "Tights.") and section headers are kept.
  5. Each fragment gets from/to from the start of its first word and the
     end of its last word.

The segmentation is a best-effort draft: review it afterwards and re-split
any line that is still too long or split unnaturally, re-reading the JSON
to recompute each part's start/end time.

Usage:
    python3 timestamp_to_yaml.py timestamp.json [main.yaml]
Options:
    --max-width N   width threshold per subtitle line (default 30)
    --gap SEC       silence threshold for sentence split (default 1.5)
    --offset SEC   add this many seconds to all timestamps (default 0)
    --merge-gap SEC max silence across which an orphan may merge (default 2.0)
"""
import argparse
import json
import sys

SOFT = ',;:，、'
SENT_FINAL = '.!?…。？！'


def width(text):
    w = 0.0
    for ch in text:
        if ch == ' ':
            w += 0.25
        elif ord(ch) > 0x2E7F:
            w += 1.0
        else:
            w += 0.6
    return w


def is_sentence_final(text):
    s = text.rstrip()
    return bool(s) and s[-1] in SENT_FINAL


def fmt_ms(sec):
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms2 = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms2:03d}'


def to_yaml(cues):
    out = ['main:']
    for c in cues:
        out.append(f'  - from: {c["from"]}')
        out.append(f'    to: {c["to"]}')
        out.append('    en: |')
        for line in c['en'].split('\n'):
            out.append(f'        {line}')
        out.append('')
    return '\n'.join(out)


def convert(tokens, max_width=30.0, gap=1.5, offset=0.0, merge_gap=2.0):
    content = [i for i, t in enumerate(tokens) if t['text'].strip()]

    sentences = []
    cur = []
    for k, i in enumerate(content):
        cur.append(i)
        g = 0.0
        if k + 1 < len(content):
            g = tokens[content[k + 1]]['start'] - tokens[i]['end']
        if is_sentence_final(tokens[i]['text']) or g >= gap:
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)

    def span_text(idx_list):
        return ''.join(tokens[j]['text'] for j in range(idx_list[0], idx_list[-1] + 1))

    def hard_split(indices, max_w):
        out = []
        cur = []
        for i in indices:
            cur.append(i)
            if width(span_text(cur)) > max_w and len(cur) > 1:
                out.append(cur[:-1])
                cur = [i]
        if cur:
            out.append(cur)
        return out

    short_w = max_width * 0.6
    cap_w = max_width * 1.6

    def frag_tiny(frag):
        return len(span_text(frag).split()) <= 2

    def frag_span(frag):
        words = [i for i in frag if tokens[i]['text'].strip()]
        return tokens[words[0]]['start'], tokens[words[-1]]['end']

    def merge_in_sentence(frags):
        changed = True
        while changed:
            changed = False
            i = 0
            while i < len(frags):
                if width(span_text(frags[i])) >= short_w:
                    i += 1
                    continue
                text = span_text(frags[i]).strip()
                leadin = bool(text) and text[-1] in SOFT
                candidates = []
                if i > 0:
                    candidates.append(
                        (i - 1, width(span_text(frags[i - 1] + frags[i]))))
                if i + 1 < len(frags):
                    candidates.append(
                        (i + 1, width(span_text(frags[i] + frags[i + 1]))))
                candidates.sort(key=lambda c: (0 if c[0] == (i + 1 if leadin else i - 1) else 1, c[1]))
                merged_here = False
                for j, combined in candidates:
                    if combined <= cap_w or frag_tiny(frags[i]):
                        if j < i:
                            frags[j] = frags[j] + frags[i]
                            del frags[i]
                        else:
                            frags[i] = frags[i] + frags[j]
                            del frags[i + 1]
                        changed = True
                        merged_here = True
                        break
                if merged_here:
                    continue
                i += 1
        return frags

    all_frags = []
    for sent in sentences:
        segments = []
        seg = []
        for i in sent:
            seg.append(i)
            if tokens[i]['text'].rstrip()[-1:] in SOFT:
                segments.append(seg)
                seg = []
        if seg:
            segments.append(seg)

        frags = []
        cur = []
        for seg in segments:
            if cur and width(span_text(cur + seg)) <= max_width:
                cur = cur + seg
            else:
                if cur:
                    frags.append(cur)
                cur = seg
            if width(span_text(cur)) > max_width:
                frags.extend(hard_split(cur, max_width))
                cur = []
        if cur:
            frags.append(cur)

        merged = []
        for frag in frags:
            if merged and not any(ch.isalnum() for ch in span_text(frag)):
                merged[-1] = merged[-1] + frag
            else:
                merged.append(frag)
        frags = merge_in_sentence(merged)
        all_frags.append(frags)

    # Cross-sentence: a single-fragment sentence that is short and has no
    # terminal punctuation is an orphan HEAD cut off by an ASR pause — merge it
    # forward into the next sentence, but only across a short silence
    # (< merge_gap): a longer pause ("But first," / "in 1981,") is a real beat
    # and must stay separate. Never merge backward (that would glue a head
    # onto the previous complete sentence).
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(all_frags):
            frags = all_frags[i]
            if len(frags) == 1:
                text = span_text(frags[0]).strip()
                if (text and not is_sentence_final(text)
                        and width(span_text(frags[0])) < short_w
                        and i + 1 < len(all_frags) and all_frags[i + 1]):
                    cur_start, cur_end = frag_span(frags[0])
                    nxt = all_frags[i + 1][0]
                    nxt_start, _ = frag_span(nxt)
                    if nxt_start - cur_end < merge_gap:
                        combined = width(span_text(frags[0] + nxt))
                        if combined <= cap_w or frag_tiny(frags[0]):
                            all_frags[i + 1][0] = frags[0] + nxt
                            all_frags[i + 1] = merge_in_sentence(all_frags[i + 1])
                            del all_frags[i]
                            changed = True
                            continue
            i += 1

    cues = []
    for frags in all_frags:
        for frag in frags:
            text = span_text(frag).strip()
            if not text:
                continue
            words = [i for i in frag if tokens[i]['text'].strip()]
            cues.append({
                'from': fmt_ms(tokens[words[0]]['start'] + offset),
                'to': fmt_ms(tokens[words[-1]]['end'] + offset),
                'en': text,
            })
    return cues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output', nargs='?', default='main.yaml')
    ap.add_argument('--max-width', type=float, default=30)
    ap.add_argument('--gap', type=float, default=1.5)
    ap.add_argument('--offset', type=float, default=0.0,
                    help='seconds to add to every timestamp (segment re-transcription)')
    ap.add_argument('--merge-gap', type=float, default=2.0,
                    help='max silence (seconds) across which an orphan fragment '
                         'may be merged into a neighbouring sentence (default 2.0)')
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list) or not all(
            isinstance(t, dict) and 'text' in t and 'start' in t and 'end' in t
            for t in data):
        sys.exit('error: expected a JSON list of {"text","start","end"} tokens')

    cues = convert(data, args.max_width, args.gap, args.offset, args.merge_gap)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(to_yaml(cues))
    print(f'{len(cues)} cues -> {args.output}')


if __name__ == '__main__':
    main()

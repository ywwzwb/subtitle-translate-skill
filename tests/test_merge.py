import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from timestamp_to_yaml import convert


def tokens(text, gap_after=()):
    """Build word-level tokens like the ASR json: words, spaces, punctuation
    each as separate tokens. Times advance uniformly; a token whose index is in
    gap_after gets a long trailing silence to force a sentence boundary."""
    toks = []
    t = 10.0
    pieces = re.findall(r'\S+|\s+', text)
    for k, piece in enumerate(pieces):
        dur = 0.3 if piece.strip() else 0.1
        toks.append({'text': piece, 'start': round(t, 3),
                     'end': round(t + dur, 3)})
        if k in gap_after:
            t += 2.0
        t += dur
    return toks


class TestMergeShortFragments(unittest.TestCase):
    def test_comma_leadin_fragment_merges_forward(self):
        # "We witnessed ... using mercury, phosphorus, and a blowtorch."
        text = ("We witnessed the precision choreography needed using "
                "mercury, phosphorus, and a blowtorch.")
        cues = convert(tokens(text), max_width=30.0)
        ens = [c['en'] for c in cues]
        self.assertNotIn('mercury,', ens)
        self.assertTrue(any(e.startswith('mercury, phosphorus')
                            for e in ens),
                        f'expected mercury lead-in merged forward, got {ens}')

    def test_short_tail_merges_backward(self):
        text = "these ingenious devices store millions upon millions of bits of data."
        cues = convert(tokens(text), max_width=30.0)
        ens = [c['en'] for c in cues]
        self.assertEqual(len(cues), 1)
        self.assertEqual(ens[0].strip(),
                         'these ingenious devices store millions upon millions '
                         'of bits of data.')

    def test_single_word_orphan_sentence_merges_forward(self):
        # "The" cut off by a short pause, then the rest of the sentence.
        text = ("A photoresistant coating. The disc is delicately retrieved "
                "from the application machine.")
        pieces = re.findall(r'\S+|\s+', text)
        gap_after = {}
        for k, p in enumerate(pieces):
            if p == '. ':
                gap_after[k] = True
            if p.strip() == 'The':
                gap_after[k] = True
        toks = []
        t = 10.0
        for k, piece in enumerate(pieces):
            dur = 0.3 if piece.strip() else 0.1
            toks.append({'text': piece, 'start': round(t, 3),
                         'end': round(t + dur, 3)})
            if k in gap_after:
                t += 1.0
            t += dur
        cues = convert(toks, max_width=30.0)
        ens = [c['en'] for c in cues]
        self.assertNotIn('The', [e.strip() for e in ens])
        self.assertTrue(any(e.strip().startswith('The disc is delicately')
                            for e in ens),
                        f'expected "The" merged into next sentence, got {ens}')

    def test_big_pause_orphan_not_merged(self):
        # "But first," and "in 1981," are each followed by a ~2.5s pause — real
        # beats that must stay separate despite lacking terminal punctuation.
        text = ("See you soon. But first, in 1981, Japanese and Dutch "
                "scientists invented a device")
        pieces = re.findall(r'\S+|\s+', text)
        toks = []
        t = 10.0
        for k, piece in enumerate(pieces):
            dur = 0.3 if piece.strip() else 0.1
            toks.append({'text': piece, 'start': round(t, 3),
                         'end': round(t + dur, 3)})
            if piece.strip() in ('first,', '1981,'):
                t += 2.5  # long pause after "But first," and after "in 1981,"
            t += dur
        cues = convert(toks, max_width=30.0)
        ens = [c['en'].strip() for c in cues]
        self.assertIn('But first,', ens)
        self.assertIn('in 1981,', ens)

    def test_short_utterance_with_terminal_punct_is_kept(self):
        # "Cheese." is a complete short beat between two long pauses: keep it.
        text = ("and we'll show you how. Cheese. Mozzarella is a relative "
                "newcomer to our diets")
        toks = []
        t = 10.0
        pieces = re.findall(r'\S+|\s+', text)
        for k, piece in enumerate(pieces):
            dur = 0.3 if piece.strip() else 0.1
            toks.append({'text': piece, 'start': round(t, 3),
                         'end': round(t + dur, 3)})
            if piece.strip() == 'Cheese.':
                t += 2.0
            t += dur
        cues = convert(toks, max_width=30.0)
        ens = [c['en'].strip() for c in cues]
        self.assertIn('Cheese.', ens)
        self.assertIn("and we'll show you how.", ens)

    def test_combined_width_cap_blocks_merge(self):
        # A short tail (>2 words) must NOT merge when it would blow past the cap.
        # "aaaa..." = 24 a's (24*0.6 = 14.4u) repeated so prev fragment is wide.
        prev = "a" * 70  # 42u, a hard-split fragment already over max_width
        tail = "alpha beta gamma delta"  # 4 words, width ~ 0.6*19 + 0.75 = 12.15u
        text = prev + " " + tail + "."
        cues = convert(tokens(text), max_width=30.0)
        ens = [c['en'] for c in cues]
        joined = ' '.join(ens)
        self.assertIn(tail, joined)
        # the short tail (>2 words) should only merge if under cap; 42+12 = 54u
        # > 45 cap, so it stays a separate cue.
        self.assertTrue(any(e.strip().startswith('alpha beta gamma delta')
                            for e in ens) or 'alpha beta gamma delta.' in ens)


if __name__ == '__main__':
    unittest.main()

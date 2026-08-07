import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import splice_yaml
from splice_yaml import splice


class TestSplice(unittest.TestCase):
    def test_replaces_overlapping_keeps_others(self):
        main = [
            {'from': '00:00:00,000', 'to': '00:00:03,000', 'en': 'A sentence one.'},
            {'from': '00:00:03,500', 'to': '00:00:06,000', 'en': 'Bad region here.'},
            {'from': '00:00:07,000', 'to': '00:00:09,000', 'en': 'Keep me.'},
        ]
        seg = [
            {'from': '00:00:03,000', 'to': '00:00:04,000', 'en': 'Re-a.'},
            {'from': '00:00:04,000', 'to': '00:00:05,000', 'en': 'Re-b.'},
        ]
        new_data, deleted, inserted, warn, deleted_cues = splice({'main': main}, seg)
        texts = [c['en'] for c in new_data['main']]
        self.assertIn('A sentence one.', texts)
        self.assertNotIn('Bad region here.', texts)
        self.assertIn('Re-a.', texts)
        self.assertIn('Re-b.', texts)
        self.assertIn('Keep me.', texts)
        self.assertEqual(deleted, 1)
        self.assertEqual(inserted, 2)
        self.assertFalse(warn)

    def test_keeps_annotations(self):
        data = {
            'main': [{'from': '00:00:00,000', 'to': '00:00:02,000', 'en': 'X.'}],
            'annotations': [{'from': '00:00:00,000', 'text': '一个注解'}],
        }
        seg = [{'from': '00:00:00,500', 'to': '00:00:01,000', 'en': 'Y.'}]
        new_data, _, _, _, _ = splice(data, seg)
        self.assertEqual(new_data['annotations'],
                         [{'from': '00:00:00,000', 'text': '一个注解'}])

    def test_word_drop_warning(self):
        main = [{'from': '00:00:00,000', 'to': '00:00:04,000',
                 'en': 'one two three four five six seven eight'}]
        seg = [{'from': '00:00:00,000', 'to': '00:00:04,000', 'en': 'one'}]
        _, deleted, inserted, warn, _ = splice({'main': main}, seg)
        self.assertEqual(deleted, 1)
        self.assertEqual(inserted, 1)
        self.assertTrue(warn)

    def test_no_overlap_means_append(self):
        main = [{'from': '00:00:00,000', 'to': '00:00:02,000', 'en': 'Keep.'}]
        seg = [{'from': '00:00:10,000', 'to': '00:00:11,000', 'en': 'New.'}]
        new_data, deleted, inserted, warn, deleted_cues = splice({'main': main}, seg)
        self.assertEqual(deleted, 0)
        self.assertEqual(inserted, 1)
        self.assertEqual(len(new_data['main']), 2)

    def test_unsorted_segment_cues_compute_correct_window(self):
        main = [
            {'from': '00:00:00,000', 'to': '00:00:02,000', 'en': 'Keep A.'},
            {'from': '00:00:03,000', 'to': '00:00:06,000', 'en': 'Bad region.'},
            {'from': '00:00:04,200', 'to': '00:00:04,800', 'en': 'Inside bad.'},
            {'from': '00:00:08,000', 'to': '00:00:09,000', 'en': 'Keep B.'},
        ]
        seg = [
            {'from': '00:00:05,000', 'to': '00:00:06,000', 'en': 'Re-b.'},
            {'from': '00:00:03,000', 'to': '00:00:04,000', 'en': 'Re-a.'},
        ]
        new_data, deleted, inserted, warn, deleted_cues = splice({'main': main}, seg)
        self.assertEqual(deleted, 2)
        texts = [c['en'] for c in new_data['main']]
        self.assertNotIn('Bad region.', texts)
        self.assertNotIn('Inside bad.', texts)
        self.assertIn('Keep A.', texts)
        self.assertIn('Keep B.', texts)

    def test_dry_run_prints_deleted_cue_preview(self):
        main = [
            {'from': '00:00:00,000', 'to': '00:00:02,000', 'en': 'Keep.'},
            {'from': '00:00:03,500', 'to': '00:00:06,000', 'en': 'Bad region here.'},
        ]
        seg = [{'from': '00:00:03,000', 'to': '00:00:04,000', 'en': 'Re-a.'}]
        with tempfile.TemporaryDirectory() as d:
            main_f = os.path.join(d, 'main.yaml')
            seg_f = os.path.join(d, 'seg.yaml')
            out_f = os.path.join(d, 'out.yaml')
            with open(main_f, 'w', encoding='utf-8') as f:
                f.write(splice_yaml.to_yaml({'main': main}))
            with open(seg_f, 'w', encoding='utf-8') as f:
                f.write(splice_yaml.to_yaml({'main': seg}))
            buf = io.StringIO()
            with mock.patch.object(sys, 'argv',
                                   ['splice_yaml.py', main_f, seg_f, out_f, '--dry-run']), \
                 contextlib.redirect_stdout(buf):
                splice_yaml.main()
            out = buf.getvalue()
            self.assertIn('deleted 1 cues', out)
            self.assertIn('Bad region here.', out)
            self.assertIn('00:00:03,500', out)
            self.assertNotIn('wrote', out)


if __name__ == '__main__':
    unittest.main()

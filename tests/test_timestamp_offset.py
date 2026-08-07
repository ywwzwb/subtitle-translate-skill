import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from timestamp_to_yaml import convert


class TestConvert(unittest.TestCase):
    def test_offset(self):
        tokens = [
            {'text': 'Hello', 'start': 0.0, 'end': 0.5},
            {'text': ' ', 'start': 0.5, 'end': 0.5},
            {'text': 'world.', 'start': 0.5, 'end': 1.0},
        ]
        cues = convert(tokens, offset=10.0)
        self.assertEqual(cues[0]['from'], '00:00:10,000')
        self.assertEqual(cues[0]['to'], '00:00:11,000')
        self.assertEqual(cues[0]['en'], 'Hello world.')

    def test_no_offset_default(self):
        tokens = [{'text': 'Hi.', 'start': 2.0, 'end': 2.5}]
        cues = convert(tokens)
        self.assertEqual(cues[0]['from'], '00:00:02,000')
        self.assertEqual(cues[0]['to'], '00:00:02,500')


if __name__ == '__main__':
    unittest.main()

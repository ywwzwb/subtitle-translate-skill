import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import yaml_to_ass


class TestYamlToAssThreeTracks(unittest.TestCase):
    def build(self, data):
        lines = []
        events = []
        for item in data.get('main', []):
            chs = (item.get('chs') or '').strip()
            en = (item.get('en') or '').strip()
            sm = yaml_to_ass.ts_to_ms(item['from'])
            start = yaml_to_ass.ms_to_ass(sm)
            end = yaml_to_ass.ms_to_ass(yaml_to_ass.ts_to_ms(item['to']))
            if chs:
                events.append((sm, 0, f'Dialogue: 0,{start},{end},Translation,,0,0,0,,{chs}'))
            if en:
                events.append((sm, 1, f'Dialogue: 1,{start},{end},Original,,0,0,0,,{en}'))
        events.extend(yaml_to_ass.build_annotation_events(data.get('annotations', [])))
        events.sort(key=lambda e: (e[0], e[1]))
        return [e[2] for e in events]

    def test_three_tracks(self):
        data = {
            'main': [
                {'from': '00:00:01,000', 'to': '00:00:03,000',
                 'en': 'Hello there.', 'chs': '你好'},
                {'from': '00:00:04,000', 'to': '00:00:06,000',
                 'en': 'World.', 'chs': '世界'},
            ],
            'annotations': [
                {'from': '00:00:01,000', 'text': '注解'},
            ],
        }
        events = self.build(data)
        layers = [int(e.split('Dialogue: ', 1)[1].split(',', 1)[0]) for e in events]
        styles = [e.split(',', 4)[3] for e in events]
        self.assertEqual(layers, [0, 1, 2, 0, 1])
        self.assertEqual(styles, ['Translation', 'Original', 'Annotation',
                                  'Translation', 'Original'])
        # translation carries chs, original carries en — separate events
        self.assertIn(',,你好', events[0])
        self.assertIn(',,Hello there.', events[1])
        self.assertIn(',,注解', events[2])
        self.assertIn(',,世界', events[3])
        self.assertIn(',,World.', events[4])

    def test_no_chs_falls_back_to_original_only(self):
        data = {'main': [{'from': '00:00:01,000', 'to': '00:00:03,000',
                          'en': 'Only original.'}]}
        events = self.build(data)
        self.assertEqual(len(events), 1)
        self.assertIn('Original', events[0])
        self.assertNotIn('Translation', events[0])

    def test_header_has_three_styles(self):
        self.assertIn('Style: Translation,', yaml_to_ass.HEADER)
        self.assertIn('Style: Original,', yaml_to_ass.HEADER)
        self.assertIn('Style: Annotation,', yaml_to_ass.HEADER)


if __name__ == '__main__':
    unittest.main()

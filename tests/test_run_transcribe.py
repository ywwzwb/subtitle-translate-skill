import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import run_transcribe


class TestResolveExe(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_default(self):
        self.assertEqual(run_transcribe.resolve_exe(), run_transcribe.DEFAULT_EXE)

    @mock.patch.dict(os.environ, {'TRANSCRIBE_EXE': 'X:/custom.exe'}, clear=True)
    def test_env(self):
        self.assertEqual(run_transcribe.resolve_exe(), 'X:/custom.exe')

    @mock.patch.dict(os.environ, {'TRANSCRIBE_EXE': 'X:/custom.exe'}, clear=True)
    def test_exe_overrides_env(self):
        self.assertEqual(run_transcribe.resolve_exe('Y:/mine.exe'), 'Y:/mine.exe')


class TestBuildCmd(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            run_transcribe.build_cmd('t.exe', 'a.mp3', yes=True),
            ['t.exe', 'a.mp3', '-y'])

    def test_segment(self):
        cmd = run_transcribe.build_cmd('t.exe', 'a.mp3',
                                       seek_start=10.5, duration=30.0)
        self.assertIn('--seek-start', cmd)
        self.assertIn('10.5', cmd)
        self.assertIn('--duration', cmd)
        self.assertIn('30.0', cmd)

    def test_language_and_flags(self):
        cmd = run_transcribe.build_cmd('t.exe', 'a.mp3', language='English',
                                       no_dml=True, no_vulkan=True, prec='int8')
        self.assertIn('--language', cmd)
        self.assertIn('English', cmd)
        self.assertIn('--no-dml', cmd)
        self.assertIn('--no-vulkan', cmd)
        self.assertIn('--prec', cmd)
        self.assertIn('int8', cmd)


class TestMainExecutableResolution(unittest.TestCase):
    @mock.patch('os.path.isfile', return_value=True)
    def test_relative_exe_normalized_to_abspath(self, _isfile):
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0)
            with mock.patch.object(sys, 'argv',
                                   ['run_transcribe.py', 'audio.mp3',
                                    '--exe', 'tools/transcribe.exe', '--yes']):
                run_transcribe.main()
        cmd = run.call_args[0][0]
        self.assertTrue(os.path.isabs(cmd[0]))


if __name__ == '__main__':
    unittest.main()

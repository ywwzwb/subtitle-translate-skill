import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
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


class AssetSelectionTest(unittest.TestCase):
    def _manifest(self):
        return {"version": "v0.1.0", "assets": [
            {"os": "windows", "arch": "x64", "backend": "cpu", "filename": "qwen3-asr-windows-x64-cpu.zip", "sha256": "x", "cli": "q3asr.exe"},
            {"os": "windows", "arch": "x64", "backend": "cuda", "filename": "qwen3-asr-windows-x64-cuda.zip", "sha256": "x", "cli": "q3asr.exe"},
            {"os": "windows", "arch": "x64", "backend": "vulkan", "filename": "qwen3-asr-windows-x64-vulkan.zip", "sha256": "x", "cli": "q3asr.exe"},
            {"os": "linux", "arch": "x64", "backend": "cpu", "filename": "qwen3-asr-linux-x64-cpu.zip", "sha256": "x", "cli": "q3asr"},
            {"os": "macos", "arch": "arm64", "backend": "metal", "filename": "qwen3-asr-macos-arm64-metal.zip", "sha256": "x", "cli": "q3asr"},
        ]}

    def test_pick_cpu_on_windows(self):
        man = self._manifest()
        a = run_transcribe.select_asset(man, os_name="windows", arch="x64", backend="cpu")
        self.assertEqual(a["filename"], "qwen3-asr-windows-x64-cpu.zip")

    def test_select_explicit_backend(self):
        man = self._manifest()
        a = run_transcribe.select_asset(man, os_name="windows", arch="x64", backend="cuda")
        self.assertEqual(a["backend"], "cuda")

    def test_select_falls_back_to_cpu_when_backend_missing(self):
        man = {"version": "v", "assets": [a for a in self._manifest()["assets"] if a["os"] == "windows"]}
        a = run_transcribe.select_asset(man, os_name="windows", arch="x64", backend="vulkan")
        # vulkan exists here; use a backend that does NOT, e.g. 'metal' on windows
        a2 = run_transcribe.select_asset(man, os_name="windows", arch="x64", backend="metal")
        self.assertEqual(a2["backend"], "cpu")

    def test_no_match_raises(self):
        man = self._manifest()
        with self.assertRaises(RuntimeError):
            run_transcribe.select_asset(man, os_name="linux", arch="arm64", backend="cpu")

    def test_probe_backend(self):
        with mock.patch("run_transcribe.platform.system", return_value="Darwin"):
            self.assertEqual(run_transcribe.probe_backend(), "metal")
        with mock.patch("run_transcribe.platform.system", return_value="Windows"):
            with mock.patch("run_transcribe.shutil.which", side_effect=lambda n: n == "nvidia-smi"):
                self.assertEqual(run_transcribe.probe_backend(), "cuda")
            with mock.patch("run_transcribe.shutil.which", side_effect=lambda n: n == "vulkaninfo"):
                self.assertEqual(run_transcribe.probe_backend(), "vulkan")
            with mock.patch("run_transcribe.shutil.which", return_value=None):
                self.assertEqual(run_transcribe.probe_backend(), "cpu")

    def test_resolve_backend_env_wins(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "vulkan"}, clear=True):
            self.assertEqual(run_transcribe.resolve_backend(), "vulkan")

    def test_resolve_backend_reuses_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            with mock.patch.object(run_transcribe, "CONFIG_PATH", cfg):
                run_transcribe.save_config(backend="cpu")
                self.assertEqual(run_transcribe.resolve_backend(), "cpu")

    def test_resolve_backend_probes_and_saves_on_first_run(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            with mock.patch.object(run_transcribe, "CONFIG_PATH", cfg):
                with mock.patch("run_transcribe.probe_backend", return_value="cuda"):
                    self.assertEqual(run_transcribe.resolve_backend(), "cuda")
                # saved now; probe not called again (verify_backend mocked so the
                # saved backend passes re-verification on this machine)
                with mock.patch("run_transcribe.verify_backend", return_value=True):
                    with mock.patch("run_transcribe.probe_backend", return_value="cpu") as p:
                        self.assertEqual(run_transcribe.resolve_backend(), "cuda")
                        p.assert_not_called()

    def test_resolve_backend_stale_config_reprobes(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            with mock.patch.object(run_transcribe, "CONFIG_PATH", cfg):
                run_transcribe.save_config(backend="cuda")
                with mock.patch("run_transcribe.verify_backend", return_value=False):
                    with mock.patch("run_transcribe.probe_backend", return_value="cpu"):
                        self.assertEqual(run_transcribe.resolve_backend(), "cpu")

    def test_resolve_model_default_1_7b(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            with mock.patch.object(run_transcribe, "CONFIG_PATH", cfg):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(run_transcribe.resolve_model(), "1.7b")
                self.assertEqual(run_transcribe.load_config().get("model"), "1.7b")

    def test_resolve_model_env_wins(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_MODEL": "0.6b"}, clear=True):
            self.assertEqual(run_transcribe.resolve_model(), "0.6b")

    def test_cache_dir_layout(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            zip_path = d / "qwen3-asr-windows-x64-cpu.zip"
            with zipfile.ZipFile(zip_path, 'w') as z:
                z.writestr('q3asr.exe', 'binary')
            cache = d / "cache"
            cache.mkdir()
            run_transcribe.install_asset(cache, zip_path,
                                         "q3asr.exe", sha256=None)
            self.assertTrue((cache / "q3asr.exe").exists())


class DownloadTest(unittest.TestCase):
    def test_download_streams_to_dest(self):
        payload = b'x' * (1 << 20) + b'tail'
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'runtime.zip'
            resp = io.BytesIO(payload)
            resp.__enter__ = lambda: resp
            resp.__exit__ = lambda *a: False
            with mock.patch('urllib.request.urlopen', return_value=resp) as uo:
                run_transcribe._download('https://example.test/runtime.zip', dest)
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(dest.with_suffix('.zip.part').exists())
            self.assertGreater(uo.call_args[1]['timeout'], 0)

    def test_download_cleans_part_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'runtime.zip'
            part = dest.with_suffix('.zip.part')
            part.write_bytes(b'partial')
            with mock.patch('urllib.request.urlopen',
                            side_effect=OSError('connection lost')):
                with self.assertRaises(OSError):
                    run_transcribe._download('https://example.test/runtime.zip', dest)
            self.assertFalse(part.exists())
            self.assertFalse(dest.exists())

    def test_install_asset_verifies_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            zip_path = d / 'runtime.zip'
            with zipfile.ZipFile(zip_path, 'w') as z:
                z.writestr('q3asr.exe', 'binary')
            good = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            cache = d / 'cache'
            cache.mkdir()
            exe = run_transcribe.install_asset(cache, zip_path, 'q3asr.exe', sha256=good)
            self.assertTrue(exe.exists())
            with self.assertRaises(RuntimeError):
                run_transcribe.install_asset(cache, zip_path, 'q3asr.exe', sha256='deadbeef')


if __name__ == '__main__':
    unittest.main()

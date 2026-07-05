import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import vendor_fetch


class _FakeResponse:
    def __init__(self, data):
        self._buf = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ManifestAndCommitTests(unittest.TestCase):
    def test_load_manifest_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as repo_root:
            self.assertIsNone(vendor_fetch.load_manifest(repo_root))

    def test_load_manifest_reads_json(self):
        with tempfile.TemporaryDirectory() as repo_root:
            path = os.path.join(repo_root, vendor_fetch.MANIFEST_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"repo": "AlphaKretin/Pokemon-Tectonic-Mods", "commit": "abc123"}')
            manifest = vendor_fetch.load_manifest(repo_root)
            self.assertEqual(manifest["repo"], "AlphaKretin/Pokemon-Tectonic-Mods")
            self.assertEqual(manifest["commit"], "abc123")

    def test_installed_commit_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as vendor_dir:
            self.assertIsNone(vendor_fetch.installed_commit(vendor_dir))

    def test_needs_fetch_true_when_no_marker(self):
        with tempfile.TemporaryDirectory() as vendor_dir:
            manifest = {"repo": "owner/repo", "commit": "abc123"}
            self.assertTrue(vendor_fetch.needs_fetch(manifest, vendor_dir))

    def test_needs_fetch_false_when_commit_matches(self):
        with tempfile.TemporaryDirectory() as vendor_dir:
            marker_path = os.path.join(vendor_dir, vendor_fetch.COMMIT_MARKER_FILENAME)
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write("abc123")
            manifest = {"repo": "owner/repo", "commit": "abc123"}
            self.assertFalse(vendor_fetch.needs_fetch(manifest, vendor_dir))

    def test_needs_fetch_true_when_commit_differs(self):
        with tempfile.TemporaryDirectory() as vendor_dir:
            marker_path = os.path.join(vendor_dir, vendor_fetch.COMMIT_MARKER_FILENAME)
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write("old_commit")
            manifest = {"repo": "owner/repo", "commit": "new_commit"}
            self.assertTrue(vendor_fetch.needs_fetch(manifest, vendor_dir))


class ChecksumTests(unittest.TestCase):
    def test_mismatched_checksum_raises_before_extracting(self):
        data = b"not actually a zip file"
        with tempfile.TemporaryDirectory() as tmp:
            vendor_dir = os.path.join(tmp, "vendor")
            worker = vendor_fetch.VendorDownloadWorker("owner/repo", "abc123", vendor_dir, sha256="0" * 64)
            with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(data)), mock.patch.object(
                vendor_fetch.zipfile, "ZipFile", side_effect=AssertionError("should not reach extraction")
            ):
                with self.assertRaises(vendor_fetch.ChecksumMismatch):
                    worker._download_and_extract()

    def test_no_checksum_configured_skips_check(self):
        # sha256=None (e.g. an older manifest without one) shouldn't block
        # extraction on a checksum it was never given.
        data = b"not actually a zip file"
        with tempfile.TemporaryDirectory() as tmp:
            vendor_dir = os.path.join(tmp, "vendor")
            worker = vendor_fetch.VendorDownloadWorker("owner/repo", "abc123", vendor_dir, sha256=None)
            with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(data)):
                with self.assertRaises(Exception) as ctx:
                    worker._download_and_extract()
                # Fails at the (fake) zip extraction step, not the checksum check.
                self.assertNotIsInstance(ctx.exception, vendor_fetch.ChecksumMismatch)


if __name__ == "__main__":
    unittest.main()

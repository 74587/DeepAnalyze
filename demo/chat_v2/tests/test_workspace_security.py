import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from backend_app.services import workspace


class WorkspaceSecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = replace(
            workspace.settings,
            workspace_base_dir=self.temp_dir.name,
            upload_max_file_bytes=8,
            workspace_max_bytes=12,
            workspace_max_files=2,
            upload_chunk_bytes=4,
        )
        self.settings_patch = patch.object(workspace, "settings", self.settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_rejects_invalid_session_ids_and_relative_escape(self):
        for session_id in ["../outside", "a/b", "C:escape", ".", ".."]:
            with self.subTest(session_id=session_id), self.assertRaises(HTTPException):
                workspace.resolve_workspace_root(session_id)

        root = workspace.resolve_workspace_root("session-1")
        with self.assertRaises(HTTPException):
            workspace.resolve_workspace_path("session-1", "../session-2/secret.csv")
        self.assertEqual(root.parent, Path(self.temp_dir.name).resolve())

    async def test_rejects_upload_filename_traversal(self):
        upload = UploadFile(filename="../secret.txt", file=io.BytesIO(b"data"))
        with self.assertRaisesRegex(HTTPException, "Invalid upload filename"):
            await workspace.upload_files_to_workspace("session-1", [upload])
        self.assertFalse((Path(self.temp_dir.name) / "secret.txt").exists())

    async def test_streams_upload_and_enforces_file_size(self):
        accepted = UploadFile(filename="small.txt", file=io.BytesIO(b"12345678"))
        result = await workspace.upload_files_to_workspace("session-1", [accepted])
        self.assertEqual(result["files"][0]["size"], 8)

        oversized = UploadFile(filename="large.txt", file=io.BytesIO(b"123456789"))
        file_limit_settings = replace(self.settings, workspace_max_bytes=100)
        with (
            patch.object(workspace, "settings", file_limit_settings),
            self.assertRaisesRegex(HTTPException, "file size"),
        ):
            await workspace.upload_files_to_workspace("session-1", [oversized])
        self.assertFalse((workspace.resolve_workspace_root("session-1") / "large.txt").exists())

    async def test_enforces_workspace_total_size(self):
        first = UploadFile(filename="first.txt", file=io.BytesIO(b"12345678"))
        second = UploadFile(filename="second.txt", file=io.BytesIO(b"12345"))
        await workspace.upload_files_to_workspace("session-1", [first])
        with self.assertRaisesRegex(HTTPException, "Workspace size"):
            await workspace.upload_files_to_workspace("session-1", [second])

    def test_creates_reusable_sample_data_without_overwriting_user_file(self):
        roomy_settings = replace(
            self.settings,
            workspace_max_bytes=100_000,
            workspace_max_files=10,
        )
        with patch.object(workspace, "settings", roomy_settings):
            first = workspace.create_sample_data("session-sample")
            second = workspace.create_sample_data("session-sample")

            self.assertEqual(first["file"]["path"], "retail_sales_demo.csv")
            self.assertEqual(second["file"]["path"], "retail_sales_demo.csv")
            self.assertIn("recommended_prompt", first)
            content = (
                workspace.resolve_workspace_root("session-sample")
                / "retail_sales_demo.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("2025-04,East,Partner", content)


if __name__ == "__main__":
    unittest.main()

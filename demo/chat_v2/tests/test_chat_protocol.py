import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from backend_app.services import chat, workspace


def stream_text(text):
    yield text, {"choices": [{"finish_reason": "stop"}]}


class ChatProtocolIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        safe_settings = replace(
            chat.settings,
            workspace_base_dir=self.temp_dir.name,
            chat_max_rounds=3,
            chat_max_code_executions=2,
            chat_max_duration_sec=30,
            chat_max_response_chars=10_000,
        )
        self.chat_settings_patch = patch.object(chat, "settings", safe_settings)
        self.workspace_settings_patch = patch.object(workspace, "settings", safe_settings)
        self.chat_settings_patch.start()
        self.workspace_settings_patch.start()
        self.addCleanup(self.chat_settings_patch.stop)
        self.addCleanup(self.workspace_settings_patch.stop)

    def test_truncated_code_is_never_executed(self):
        execute_mock = Mock(return_value="must not run")
        with (
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('unsafe')"
            )),
            patch.object(chat, "execute_code_safe", execute_mock),
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-truncated"
            ))
        self.assertIn("[Protocol Error]", output)
        execute_mock.assert_not_called()

    def test_complete_code_then_answer_runs_once_and_saves_report(self):
        responses = iter([
            stream_text("<Analyze>plan</Analyze><Code>print('ok')</Code>"),
            stream_text("<Understand>result is valid</Understand><Answer>done</Answer>"),
        ])
        with (
            patch.object(chat, "_iter_local_stream", side_effect=lambda *_: next(responses)),
            patch.object(chat, "execute_code_safe", return_value="ok") as execute_mock,
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-complete"
            ))
        self.assertIn("<Execute>", output)
        self.assertIn("<Answer>done</Answer>", output)
        execute_mock.assert_called_once()
        reports = list(
            (Path(self.temp_dir.name) / "session-complete" / "generated").glob(
                "Answer_Report_*.md"
            )
        )
        self.assertEqual(len(reports), 1)

    def test_round_budget_stops_an_unfinished_workflow(self):
        limited_settings = replace(chat.settings, chat_max_rounds=1)
        with (
            patch.object(chat, "settings", limited_settings),
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('ok')</Code>"
            )),
            patch.object(chat, "execute_code_safe", return_value="ok"),
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-budget"
            ))
        self.assertIn("[Budget Exceeded]", output)

    def test_same_session_rejects_concurrent_run(self):
        lock = chat.try_acquire_session_run("session-busy")
        self.assertIsNotNone(lock)
        try:
            output = "".join(chat.bot_stream([], [], "session-busy"))
        finally:
            chat.release_session_run("session-busy", lock)
        self.assertIn("[Session Busy]", output)


if __name__ == "__main__":
    unittest.main()

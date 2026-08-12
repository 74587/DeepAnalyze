import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend_app.services import chat, workspace


def stream_text(text):
    yield text, {"choices": [{"finish_reason": "stop"}]}


def execution_outcome(result="ok"):
    return SimpleNamespace(
        result=result,
        execution_content=f"\n<Execute>\n```\n{result}\n```\n</Execute>\n",
    )


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
        execute_mock = Mock(return_value=execution_outcome("must not run"))
        with (
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('unsafe')"
            )),
            patch.object(chat, "execute_managed_code", execute_mock),
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
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ) as execute_mock,
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

    def test_format_drift_is_silently_normalized(self):
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text("Here is the result.\n<Answer>done</Answer>"),
        ):
            output = "".join(
                chat.bot_stream(
                    [
                        {"role": "user", "content": "first question"},
                        {"role": "assistant", "content": "<Answer>first</Answer>"},
                        {"role": "user", "content": "analyze"},
                    ],
                    [],
                    "session-normalized",
                )
            )
        self.assertEqual(
            output.split("\n<File>", 1)[0],
            "<Analyze>Here is the result.</Analyze>\n<Answer>done</Answer>",
        )
        self.assertNotIn("Protocol Warning", output)

    def test_initial_response_gets_analyze_open_tag_when_plain_text_starts_it(self):
        heywhale_shape = (
            "Thinking before the action block.\n"
            "</Analyze>\n<Answer>ok</Answer>"
        )
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text(heywhale_shape),
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-initial-prefix",
                )
            )
        self.assertIn(
            "<Analyze>Thinking before the action block.\n</Analyze>",
            output,
        )
        self.assertIn("<Answer>ok</Answer>", output)
        self.assertNotIn("Protocol Error", output)

    def test_follow_up_response_does_not_get_initial_analyze_tag(self):
        heywhale_shape = (
            "Thinking before the action block.\n"
            "</Analyze>\n<Answer>ok</Answer>"
        )
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text(heywhale_shape),
        ):
            output = "".join(
                chat.bot_stream(
                    [
                        {"role": "user", "content": "first question"},
                        {"role": "assistant", "content": "<Answer>first</Answer>"},
                        {"role": "user", "content": "follow up"},
                    ],
                    [],
                    "session-follow-up-no-prefix",
                )
            )
        self.assertIn("[Protocol Error]", output)

    def test_round_budget_stops_an_unfinished_workflow(self):
        limited_settings = replace(chat.settings, chat_max_rounds=1)
        with (
            patch.object(chat, "settings", limited_settings),
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('ok')</Code>"
            )),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
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

    def test_explicit_empty_file_selection_does_not_include_all_files(self):
        workspace_dir = workspace.get_session_workspace("session-selection")
        Path(workspace_dir, "input.csv").write_text("a\n1\n", encoding="utf-8")
        explicit_messages = [{"role": "user", "content": "analyze"}]
        chat._build_user_prompt(
            explicit_messages,
            [],
            workspace_dir,
            use_all_files_when_empty=False,
        )
        self.assertNotIn("# Data", explicit_messages[-1]["content"])

        legacy_messages = [{"role": "user", "content": "analyze"}]
        chat._build_user_prompt(
            legacy_messages,
            [],
            workspace_dir,
            use_all_files_when_empty=True,
        )
        self.assertIn("input.csv", legacy_messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()

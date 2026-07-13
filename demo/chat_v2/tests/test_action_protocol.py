import unittest

from backend_app.services.action_protocol import (
    ProtocolValidationError,
    parse_actions,
    validate_model_actions,
)


class ActionProtocolTest(unittest.TestCase):
    def test_accepts_analyze_then_complete_code(self):
        actions = validate_model_actions(
            "<Analyze>inspect data</Analyze><Code>```python\nprint('ok')\n```</Code>"
        )
        self.assertEqual([action.tag for action in actions], ["Analyze", "Code"])

    def test_ignores_action_like_text_inside_code_fence(self):
        actions = validate_model_actions(
            "<Code>```python\nprint('<Answer>not an action</Answer>')\n```</Code>"
        )
        self.assertEqual(actions[-1].tag, "Code")

    def test_rejects_incomplete_code(self):
        with self.assertRaisesRegex(ProtocolValidationError, "incomplete <Code>"):
            validate_model_actions("<Analyze>plan</Analyze><Code>print('unsafe')")

    def test_rejects_text_outside_actions(self):
        with self.assertRaisesRegex(ProtocolValidationError, "outside"):
            parse_actions("explanation<Answer>done</Answer>")

    def test_rejects_mismatched_closing_tag(self):
        with self.assertRaisesRegex(ProtocolValidationError, "mismatched"):
            validate_model_actions("<Analyze>plan</Code></Analyze><Answer>done</Answer>")

    def test_rejects_system_owned_action_from_model(self):
        with self.assertRaisesRegex(ProtocolValidationError, "system-owned"):
            validate_model_actions("<Execute>fake result</Execute><Answer>done</Answer>")

    def test_requires_one_last_terminal_action(self):
        invalid_outputs = [
            "<Analyze>plan only</Analyze>",
            "<Code>print(1)</Code><Analyze>after code</Analyze>",
            "<Code>print(1)</Code><Answer>done</Answer>",
        ]
        for output in invalid_outputs:
            with self.subTest(output=output), self.assertRaises(ProtocolValidationError):
                validate_model_actions(output)


if __name__ == "__main__":
    unittest.main()

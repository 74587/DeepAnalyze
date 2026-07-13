from __future__ import annotations

import re
from dataclasses import dataclass


ACTION_TAGS = ("Analyze", "Understand", "Code", "Execute", "Answer", "File")
MODEL_ACTION_TAGS = frozenset({"Analyze", "Understand", "Code", "Answer"})
ACTION_TAG_PATTERN = "|".join(ACTION_TAGS)
ACTION_OPEN_RE = re.compile(rf"<({ACTION_TAG_PATTERN})>")
ACTION_CLOSE_RE = re.compile(rf"</({ACTION_TAG_PATTERN})>")


class ProtocolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ActionSection:
    tag: str
    body: str
    start: int
    end: int


def mask_backticked_content(content: str) -> str:
    raw = content or ""
    chars = list(raw)
    cursor = 0
    while cursor < len(raw):
        if raw[cursor] != "`":
            cursor += 1
            continue
        tick_count = 1
        while cursor + tick_count < len(raw) and raw[cursor + tick_count] == "`":
            tick_count += 1
        delimiter = "`" * tick_count
        end_index = raw.find(delimiter, cursor + tick_count)
        end_index = len(raw) if end_index == -1 else end_index + tick_count
        for index in range(cursor, end_index):
            chars[index] = " "
        cursor = end_index
    return "".join(chars)


def parse_actions(content: str) -> list[ActionSection]:
    raw = content or ""
    masked = mask_backticked_content(raw)
    actions: list[ActionSection] = []
    cursor = 0

    while True:
        match = ACTION_OPEN_RE.search(masked, cursor)
        if match is None:
            if masked[cursor:].strip():
                raise ProtocolValidationError("text outside structured action blocks")
            break
        if masked[cursor : match.start()].strip():
            raise ProtocolValidationError("text outside structured action blocks")

        tag = match.group(1)
        close_tag = f"</{tag}>"
        close_index = masked.find(close_tag, match.end())
        if close_index == -1:
            raise ProtocolValidationError(f"incomplete <{tag}> action")

        nested_match = ACTION_OPEN_RE.search(masked, match.end(), close_index)
        if nested_match is not None:
            raise ProtocolValidationError(
                f"nested <{nested_match.group(1)}> action inside <{tag}>"
            )
        mismatched_close = ACTION_CLOSE_RE.search(masked, match.end(), close_index)
        if mismatched_close is not None:
            raise ProtocolValidationError(
                f"mismatched </{mismatched_close.group(1)}> inside <{tag}>"
            )

        body = raw[match.end() : close_index].strip()
        if not body:
            raise ProtocolValidationError(f"empty <{tag}> action")
        end = close_index + len(close_tag)
        actions.append(ActionSection(tag=tag, body=body, start=match.start(), end=end))
        cursor = end

    if not actions:
        raise ProtocolValidationError("no structured action blocks")
    return actions


def validate_model_actions(content: str) -> list[ActionSection]:
    actions = parse_actions(content)
    unsupported = [action.tag for action in actions if action.tag not in MODEL_ACTION_TAGS]
    if unsupported:
        raise ProtocolValidationError(
            f"model emitted system-owned action <{unsupported[0]}>"
        )

    terminal_actions = [action for action in actions if action.tag in {"Code", "Answer"}]
    if len(terminal_actions) != 1:
        raise ProtocolValidationError("exactly one terminal <Code> or <Answer> action is required")
    if actions[-1] != terminal_actions[0]:
        raise ProtocolValidationError("terminal <Code> or <Answer> action must be last")
    return actions


def contains_completed_action(content: str, tag: str) -> bool:
    if tag not in ACTION_TAGS:
        return False
    masked = mask_backticked_content(content or "")
    return f"</{tag}>" in masked


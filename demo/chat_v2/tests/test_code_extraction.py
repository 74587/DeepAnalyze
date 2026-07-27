from backend_app.services.chat import _extract_code_to_execute
from backend_app.services.execution_service import _truncate_output


def test_extract_code_python_fence():
    content = "```python\nprint('hi')\n```"
    assert _extract_code_to_execute(content) == "print('hi')"


def test_extract_code_py_fence():
    # Regression: ```py used to leave the language token inside the script,
    # producing an instant SyntaxError.
    content = "```py\nprint('hi')\n```"
    assert _extract_code_to_execute(content) == "print('hi')"


def test_extract_code_capitalized_fence():
    content = "```Python\nprint('hi')\n```"
    assert _extract_code_to_execute(content) == "print('hi')"


def test_extract_code_bare_fence():
    content = "```\nprint('hi')\n```"
    assert _extract_code_to_execute(content) == "print('hi')"


def test_extract_code_no_fence():
    assert _extract_code_to_execute("print('hi')") == "print('hi')"


def test_extract_code_matplotlib_bootstrap_prepended():
    content = "```python\nimport matplotlib.pyplot as plt\nplt.plot([1])\n```"
    extracted = _extract_code_to_execute(content)
    assert extracted is not None
    assert "SimHei" in extracted
    assert "plt.plot([1])" in extracted


def test_truncate_output_short_passthrough():
    assert _truncate_output("abc", 100) == "abc"


def test_truncate_output_caps_long_text():
    text = "x" * 100_000
    truncated = _truncate_output(text, 1024)
    assert len(truncated) < 2048
    assert "output truncated" in truncated


def test_truncate_output_keeps_head_marker():
    # success detection relies on startswith("[Error]"), so the head must survive
    text = "[Error]: boom\n" + "y" * 100_000
    truncated = _truncate_output(text, 2048)
    assert truncated.startswith("[Error]")

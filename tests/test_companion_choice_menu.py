from __future__ import annotations


def test_choice_menu_down_and_enter_immediately_returns_highlighted_value():
    from prompt_toolkit.application.current import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from src.cli_commands.companion_choice_menu import run_choice_menu

    with create_pipe_input() as pipe_input:
        pipe_input.send_text("\x1b[B\r")
        with create_app_session(input=pipe_input, output=DummyOutput()):
            selected = run_choice_menu(
                title="Select Provider",
                text="Choose one",
                choices=[("provider-a", "provider-a"), ("provider-b", "provider-b")],
                default="provider-a",
            )

    assert selected == "provider-b"


def test_choice_menu_escape_cancels_without_selection():
    from prompt_toolkit.application.current import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from src.cli_commands.companion_choice_menu import run_choice_menu

    with create_pipe_input() as pipe_input:
        pipe_input.send_text("\x1b")
        with create_app_session(input=pipe_input, output=DummyOutput()):
            selected = run_choice_menu(
                title="Select Provider",
                text="Choose one",
                choices=[("provider-a", "provider-a")],
                default="provider-a",
            )

    assert selected is None


def test_choice_menu_with_checked_items_still_confirms_highlighted_item_on_enter():
    from prompt_toolkit.application.current import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from src.cli_commands.companion_choice_menu import run_choice_menu

    with create_pipe_input() as pipe_input:
        pipe_input.send_text("\r")
        with create_app_session(input=pipe_input, output=DummyOutput()):
            selected = run_choice_menu(
                title="Toggle Tool",
                text="Choose one",
                choices=[("tool-a", "Tool A"), ("tool-b", "Tool B")],
                default="tool-a",
                checked={"tool-a"},
            )

    assert selected == "tool-a"

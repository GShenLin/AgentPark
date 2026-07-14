from __future__ import annotations


def run_choice_menu(
    *,
    title: str,
    text: str,
    choices: list[tuple[str, str]],
    default: str,
    checked: set[str] | None = None,
) -> str | None:
    if not choices:
        raise ValueError("choice menu requires at least one item")

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    values = [value for value, _label in choices]
    selected_index = values.index(default) if default in values else 0
    checked_values = set(checked or ())

    def render_choices() -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, (_value, label) in enumerate(choices):
            selected = index == selected_index
            style = "class:choice.selected" if selected else "class:choice"
            cursor = ">" if selected else " "
            marker = "[x]" if _value in checked_values else "[ ]"
            if selected:
                fragments.append(("[SetCursorPosition]", ""))
            fragments.append((style, f"{cursor} {marker} {label}" if checked is not None else f"{cursor} {label}"))
            if index < len(choices) - 1:
                fragments.append(("", "\n"))
        return fragments

    key_bindings = KeyBindings()

    @key_bindings.add("up")
    @key_bindings.add("k")
    def move_up(event) -> None:
        nonlocal selected_index
        selected_index = max(0, selected_index - 1)
        event.app.invalidate()

    @key_bindings.add("down")
    @key_bindings.add("j")
    def move_down(event) -> None:
        nonlocal selected_index
        selected_index = min(len(choices) - 1, selected_index + 1)
        event.app.invalidate()

    @key_bindings.add("enter")
    def accept(event) -> None:
        event.app.exit(result=choices[selected_index][0])

    @key_bindings.add("escape")
    @key_bindings.add("c-c")
    def cancel(event) -> None:
        event.app.exit(result=None)

    title_control = FormattedTextControl([("class:title", title), ("", "\n"), ("class:hint", text)])
    choice_control = FormattedTextControl(render_choices, focusable=True)
    root = HSplit(
        [
            Window(title_control, height=2, dont_extend_height=True),
            Window(height=1, char=" "),
            Window(choice_control, always_hide_cursor=True),
            Window(height=1, char=" "),
            Window(FormattedTextControl([("class:hint", "Up/Down select · Enter confirm · Esc cancel")]), height=1),
        ],
        padding=0,
    )
    style = Style.from_dict(
        {
            "title": "bold ansicyan",
            "hint": "ansibrightblack",
            "choice": "",
            "choice.selected": "reverse bold",
        }
    )
    application = Application(
        layout=Layout(root, focused_element=choice_control),
        key_bindings=key_bindings,
        full_screen=True,
        mouse_support=False,
        style=style,
    )
    return application.run()


__all__ = ["run_choice_menu"]

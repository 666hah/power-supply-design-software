"""Keyboard and clipboard validation for numeric desktop fields."""

import math
import re
import tkinter as tk


MAX_MANTISSA_DIGITS = 17
MAX_EXPONENT_DIGITS = 3
_INTEGER = re.compile(r'[+-]?[0-9]*')
_DECIMAL = re.compile(
    rf'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{{0,{MAX_EXPONENT_DIGITS}}})?'
)
_DECIMAL_PREFIXES = {'', '+', '-', '.', '+.', '-.'}


def _can_edit(text, integer, max_digits):
    if integer:
        if len(text) > max_digits + 1 or not _INTEGER.fullmatch(text):
            return False
        return len(text.lstrip('+-')) <= max_digits
    if text in _DECIMAL_PREFIXES:
        return True
    if len(text) > max_digits + MAX_EXPONENT_DIGITS + 4 or not _DECIMAL.fullmatch(text):
        return False
    mantissa, _, exponent = text.lower().partition('e')
    if len(mantissa.lstrip('+-').replace('.', '')) > max_digits:
        return False
    if exponent in ('+', '-') or text.endswith(('e', 'E')):
        return True  # An unfinished exponent can still be edited.
    return math.isfinite(float(text))


def limit_numeric_input(widget, *, integer=False, max_digits=MAX_MANTISSA_DIGITS):
    """Limit user edits while allowing projects to populate the bound variable."""
    def validate(proposed, action):
        return action != '1' or _can_edit(proposed, integer, max_digits)

    def accepts_replacement(value):
        current = widget.get()
        if widget.selection_present():
            start = widget.index('sel.first')
            end = widget.index('sel.last')
        else:
            start = end = widget.index('insert')
        return _can_edit(current[:start] + value + current[end:], integer, max_digits)

    def check_key(event):
        # Tk deletes the selection before validating the inserted character.
        if event.char and event.char.isprintable() and widget.selection_present():
            if not accepts_replacement(event.char):
                return 'break'

    def check_paste(_event):
        try:
            value = widget.clipboard_get()
        except tk.TclError:
            return 'break'
        if not value or not accepts_replacement(value):
            return 'break'

    widget.configure(validate='key', validatecommand=(widget.register(validate), '%P', '%d'))
    widget.bind('<KeyPress>', check_key, add='+')
    widget.bind('<<Paste>>', check_paste, add='+')

"""
edit_void.py — Edit / Void expense entries page
Piranjeri Temples Family Trust Accounting System

Delegates to render_edit_void() in expense_entry.py.
Called from app_accounting.py when page == 'edit_void'.
"""

from expense_entry import render_edit_void


def render(user: str):
    render_edit_void(user)

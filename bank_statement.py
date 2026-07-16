"""
bank_statement.py — Bank Statement page
Piranjeri Temples Family Trust Accounting System

Delegates to render_bank_statement() in expense_entry.py.
Called from app_accounting.py when page == 'bank_statement'.
"""

from expense_entry import render_bank_statement


def render(user: str):
    render_bank_statement(user)

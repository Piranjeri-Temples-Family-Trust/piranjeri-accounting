"""
manage_heads.py
Piranjeri Temples Family Trust — Accounting System
Page: Manage Expense Categories

Allows any logged-in trustee to:
  - Add new major heads  (E-19, E-20, ...)  without needing the developer
  - Edit the name / description of existing heads
  - Deactivate (soft-delete) or Reactivate heads

Uses pg8000.native API (conn.run / conn.run("COMMIT")) — same connection
as the rest of the app (st.session_state.conn).
"""

import streamlit as st
from datetime import datetime


# ---------------------------------------------------------------------------
# Internal helpers — pg8000.native style
# ---------------------------------------------------------------------------

def _get_conn():
    return st.session_state.get("conn")


def _load_all_heads(conn):
    """
    Fetch every major head row in one conn.run() call.
    Returns list of dicts: id, code, name, description, is_active.
    """
    rows = conn.run(
        "SELECT id, code, name, description, is_active "
        "FROM major_heads ORDER BY code"
    )
    return [
        {
            "id":          r[0],
            "code":        r[1],
            "name":        r[2],
            "description": r[3] or "",
            "is_active":   r[4],
        }
        for r in rows
    ]


def _next_code(heads):
    """Suggest next E-xx code beyond the highest existing numeric suffix."""
    max_n = 18
    for h in heads:
        try:
            n = int(h["code"].split("-")[1])
            if n > max_n:
                max_n = n
        except (IndexError, ValueError):
            pass
    return f"E-{max_n + 1:02d}"


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _tab_add(conn, heads):
    st.subheader("Add New Expense Category")
    st.caption(
        "Create a new expense category (e.g. E-19 Generator Fuel). "
        "It will immediately appear in the Journal entry dropdown."
    )

    suggested_code = _next_code(heads)
    existing_codes = {h["code"].upper() for h in heads}

    with st.form("add_head_form", clear_on_submit=True):
        col1, col2 = st.columns([1, 3])
        with col1:
            new_code = st.text_input(
                "Category Code *",
                value=suggested_code,
                max_chars=10,
                help="Format: E-19, E-20 … Must be unique.",
            )
        with col2:
            new_name = st.text_input(
                "Category Name *",
                max_chars=100,
                placeholder="e.g. Generator Fuel",
            )

        new_desc = st.text_input(
            "Description (optional)",
            max_chars=255,
            placeholder="Brief note on what this category covers",
        )

        submitted = st.form_submit_button("Add Category", type="primary")

    if submitted:
        new_code = new_code.strip().upper()
        new_name = new_name.strip()

        errors = []
        if not new_code:
            errors.append("Category Code is required.")
        elif new_code in existing_codes:
            errors.append(f"Code **{new_code}** already exists. Choose a different code.")
        if not new_name:
            errors.append("Category Name is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            try:
                conn.run(
                    "INSERT INTO major_heads (code, name, description, is_active) "
                    "VALUES (:code, :name, :desc, TRUE)",
                    code=new_code,
                    name=new_name,
                    desc=new_desc.strip() or None,
                )
                conn.run("COMMIT")
                st.success(
                    f"Category **{new_code} — {new_name}** added successfully! "
                    "It is now available in the expense entry form."
                )
                st.rerun()
            except Exception as ex:
                try:
                    conn.run("ROLLBACK")
                except Exception:
                    pass
                st.error(f"Database error: {ex}")


def _tab_edit(conn, heads):
    st.subheader("Edit Expense Category")
    st.caption("Update the name or description of an existing category.")

    if not heads:
        st.info("No categories found.")
        return

    options = [f"{h['code']} — {h['name']}" for h in heads]
    choice = st.selectbox("Select Category to Edit", options=options, key="mh_edit_select")
    idx = options.index(choice)
    selected = heads[idx]

    with st.form("edit_head_form"):
        st.write(f"**Code:** {selected['code']}  *(code cannot be changed)*")
        edited_name = st.text_input("Category Name *", value=selected["name"], max_chars=100)
        edited_desc = st.text_input("Description", value=selected["description"], max_chars=255)
        save_btn = st.form_submit_button("Save Changes", type="primary")

    if save_btn:
        edited_name = edited_name.strip()
        if not edited_name:
            st.error("Category Name cannot be empty.")
        else:
            try:
                conn.run(
                    "UPDATE major_heads SET name = :name, description = :desc WHERE id = :id",
                    name=edited_name,
                    desc=edited_desc.strip() or None,
                    id=selected["id"],
                )
                conn.run("COMMIT")
                st.success(f"Category **{selected['code']}** updated to **{edited_name}**.")
                st.rerun()
            except Exception as ex:
                try:
                    conn.run("ROLLBACK")
                except Exception:
                    pass
                st.error(f"Database error: {ex}")


def _tab_deactivate(conn, heads):
    st.subheader("Deactivate / Reactivate Category")
    st.caption(
        "Deactivating hides a category from the expense-entry dropdown. "
        "Past expense records are **not** affected. You can reactivate at any time."
    )

    if not heads:
        st.info("No categories found.")
        return

    active_heads   = [h for h in heads if h["is_active"]]
    inactive_heads = [h for h in heads if not h["is_active"]]

    # ---- Deactivate ----
    st.markdown("##### Deactivate an Active Category")
    if not active_heads:
        st.info("All categories are currently active.")
    else:
        active_opts = [f"{h['code']} — {h['name']}" for h in active_heads]
        deact_choice = st.selectbox("Select category to deactivate", options=active_opts, key="mh_deact_select")
        deact_head = active_heads[active_opts.index(deact_choice)]

        st.warning(
            f"Deactivating **{deact_head['code']} — {deact_head['name']}** will "
            "remove it from the expense-entry dropdown. Existing records using this category are unchanged."
        )

        if st.button("Deactivate Category", key="mh_deact_btn"):
            try:
                conn.run(
                    "UPDATE major_heads SET is_active = FALSE WHERE id = :id",
                    id=deact_head["id"],
                )
                conn.run("COMMIT")
                st.success(f"Category **{deact_head['code']} — {deact_head['name']}** deactivated.")
                st.rerun()
            except Exception as ex:
                try:
                    conn.run("ROLLBACK")
                except Exception:
                    pass
                st.error(f"Database error: {ex}")

    st.divider()

    # ---- Reactivate ----
    st.markdown("##### Reactivate a Deactivated Category")
    if not inactive_heads:
        st.info("No deactivated categories.")
    else:
        inactive_opts = [f"{h['code']} — {h['name']}" for h in inactive_heads]
        react_choice = st.selectbox("Select category to reactivate", options=inactive_opts, key="mh_react_select")
        react_head = inactive_heads[inactive_opts.index(react_choice)]

        if st.button("Reactivate Category", type="primary", key="mh_react_btn"):
            try:
                conn.run(
                    "UPDATE major_heads SET is_active = TRUE WHERE id = :id",
                    id=react_head["id"],
                )
                conn.run("COMMIT")
                st.success(f"Category **{react_head['code']} — {react_head['name']}** reactivated.")
                st.rerun()
            except Exception as ex:
                try:
                    conn.run("ROLLBACK")
                except Exception:
                    pass
                st.error(f"Database error: {ex}")


# ---------------------------------------------------------------------------
# Current heads overview
# ---------------------------------------------------------------------------

def _show_heads_table(heads):
    if not heads:
        return
    with st.expander("All Categories (click to expand)", expanded=False):
        col_h = st.columns([1, 3, 4, 1])
        col_h[0].markdown("**Code**")
        col_h[1].markdown("**Name**")
        col_h[2].markdown("**Description**")
        col_h[3].markdown("**Active**")
        for h in heads:
            cols = st.columns([1, 3, 4, 1])
            cols[0].write(h["code"])
            cols[1].write(h["name"])
            cols[2].write(h["description"] or "—")
            cols[3].write("Yes" if h["is_active"] else "No")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_manage_heads(user):
    st.title("Manage Expense Categories")
    st.caption(f"Logged in as **{user}** — {datetime.now().strftime('%d %b %Y, %H:%M')}")
    st.markdown(
        "Use this page to add new expense categories, rename existing ones, "
        "or deactivate categories that are no longer needed. "
        "Changes take effect immediately — no developer required."
    )

    conn = _get_conn()
    if conn is None:
        st.error("Database connection not available. Please log out and log in again.")
        return

    try:
        heads = _load_all_heads(conn)
    except Exception as ex:
        st.error(f"Failed to load categories: {ex}")
        return

    active_count   = sum(1 for h in heads if h["is_active"])
    inactive_count = len(heads) - active_count
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Categories", len(heads))
    c2.metric("Active", active_count)
    c3.metric("Inactive", inactive_count)

    st.divider()
    _show_heads_table(heads)
    st.divider()

    tab_add, tab_edit, tab_deact = st.tabs(
        ["Add New Category", "Edit Category", "Deactivate / Reactivate"]
    )

    with tab_add:
        _tab_add(conn, heads)

    with tab_edit:
        _tab_edit(conn, heads)

    with tab_deact:
        _tab_deactivate(conn, heads)

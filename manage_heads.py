"""
manage_heads.py
Piranjeri Temples Family Trust — Accounting System
Page: Manage Expense Categories

Allows any logged-in trustee to:
  - Add new major heads  (E-19, E-20, ...)  without needing the developer
  - Edit the name / description of existing heads
  - Deactivate (soft-delete) or Reactivate heads

All changes are stored in the `major_heads` table on Neon PostgreSQL.
The is_active flag controls whether the head appears in the expense-entry
dropdown. Deactivating a head does NOT affect past expense records.

pg8000 note: ALL data for this page is fetched in a SINGLE conn.run()
call to avoid the connection-state / result-buffer bug.
"""

import streamlit as st
from datetime import datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cursor(conn):
    """Return a fresh cursor from the shared pg8000 connection."""
    return conn.cursor()


def _get_conn():
    """Retrieve the pg8000 connection cached in session state."""
    return st.session_state.get("conn")


def _load_all_heads(conn):
    """
    Fetch every major head row in one query.
    Returns list of dicts with keys: id, code, name, description, is_active.
    """
    with _cursor(conn) as cur:
        cur.execute(
            """
            SELECT id, code, name, description, is_active
            FROM   major_heads
            ORDER  BY code
            """
        )
        rows = cur.fetchall()
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
    """
    Suggest the next available E-xx code by finding the highest numeric suffix
    among existing heads.
    """
    max_n = 18   # start after the 18 shipped heads
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
    """Tab 1 — Add a new major head."""
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

        # Validate
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
                with _cursor(conn) as cur:
                    cur.execute(
                        """
                        INSERT INTO major_heads (code, name, description, is_active)
                        VALUES (%s, %s, %s, TRUE)
                        """,
                        (new_code, new_name, new_desc.strip() or None),
                    )
                conn.commit()
                st.success(
                    f"Category **{new_code} — {new_name}** added successfully! "
                    "It is now available in the expense entry form."
                )
                st.rerun()
            except Exception as ex:
                conn.rollback()
                st.error(f"Database error: {ex}")


def _tab_edit(conn, heads):
    """Tab 2 — Edit name / description of an existing head."""
    st.subheader("Edit Expense Category")
    st.caption("Update the name or description of an existing category.")

    if not heads:
        st.info("No categories found.")
        return

    options = [f"{h['code']} — {h['name']}" for h in heads]
    choice = st.selectbox(
        "Select Category to Edit",
        options=options,
        key="mh_edit_select",
    )
    idx = options.index(choice)
    selected = heads[idx]

    with st.form("edit_head_form"):
        st.write(f"**Code:** {selected['code']}  *(code cannot be changed)*")

        edited_name = st.text_input(
            "Category Name *",
            value=selected["name"],
            max_chars=100,
        )
        edited_desc = st.text_input(
            "Description",
            value=selected["description"],
            max_chars=255,
        )

        save_btn = st.form_submit_button("Save Changes", type="primary")

    if save_btn:
        edited_name = edited_name.strip()
        if not edited_name:
            st.error("Category Name cannot be empty.")
        else:
            try:
                with _cursor(conn) as cur:
                    cur.execute(
                        """
                        UPDATE major_heads
                        SET    name        = %s,
                               description = %s
                        WHERE  id          = %s
                        """,
                        (edited_name, edited_desc.strip() or None, selected["id"]),
                    )
                conn.commit()
                st.success(
                    f"Category **{selected['code']}** updated to "
                    f"**{edited_name}**."
                )
                st.rerun()
            except Exception as ex:
                conn.rollback()
                st.error(f"Database error: {ex}")


def _tab_deactivate(conn, heads):
    """Tab 3 — Deactivate or Reactivate a major head (soft toggle)."""
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
        deact_choice = st.selectbox(
            "Select category to deactivate",
            options=active_opts,
            key="mh_deact_select",
        )
        deact_idx = active_opts.index(deact_choice)
        deact_head = active_heads[deact_idx]

        st.warning(
            f"Deactivating **{deact_head['code']} — {deact_head['name']}** will "
            "remove it from the expense-entry dropdown. Existing expense records "
            "using this category are unchanged."
        )

        if st.button("Deactivate Category", key="mh_deact_btn"):
            try:
                with _cursor(conn) as cur:
                    cur.execute(
                        "UPDATE major_heads SET is_active = FALSE WHERE id = %s",
                        (deact_head["id"],),
                    )
                conn.commit()
                st.success(
                    f"Category **{deact_head['code']} — {deact_head['name']}** "
                    "has been deactivated."
                )
                st.rerun()
            except Exception as ex:
                conn.rollback()
                st.error(f"Database error: {ex}")

    st.divider()

    # ---- Reactivate ----
    st.markdown("##### Reactivate a Deactivated Category")
    if not inactive_heads:
        st.info("No deactivated categories.")
    else:
        inactive_opts = [f"{h['code']} — {h['name']}" for h in inactive_heads]
        react_choice = st.selectbox(
            "Select category to reactivate",
            options=inactive_opts,
            key="mh_react_select",
        )
        react_idx = inactive_opts.index(react_choice)
        react_head = inactive_heads[react_idx]

        if st.button("Reactivate Category", type="primary", key="mh_react_btn"):
            try:
                with _cursor(conn) as cur:
                    cur.execute(
                        "UPDATE major_heads SET is_active = TRUE WHERE id = %s",
                        (react_head["id"],),
                    )
                conn.commit()
                st.success(
                    f"Category **{react_head['code']} — {react_head['name']}** "
                    "is now active and will appear in the expense-entry dropdown."
                )
                st.rerun()
            except Exception as ex:
                conn.rollback()
                st.error(f"Database error: {ex}")


# ---------------------------------------------------------------------------
# Current heads overview table
# ---------------------------------------------------------------------------

def _show_heads_table(heads):
    """Render a compact summary table of all heads."""
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
# Main entry point (called from app_accounting.py)
# ---------------------------------------------------------------------------

def render_manage_heads(user):
    """
    Render the Manage Expense Categories page.

    Parameters
    ----------
    user : str
        Username of the currently logged-in trustee.
    """
    st.title("Manage Expense Categories")
    st.caption(
        f"Logged in as **{user}** — "
        + datetime.now().strftime("%d %b %Y, %H:%M")
    )
    st.markdown(
        "Use this page to add new expense categories, rename existing ones, "
        "or deactivate categories that are no longer needed. "
        "Changes take effect immediately — no developer required."
    )

    conn = _get_conn()
    if conn is None:
        st.error("Database connection not available. Please log out and log in again.")
        return

    # Load all heads in one query
    try:
        heads = _load_all_heads(conn)
    except Exception as ex:
        st.error(f"Failed to load categories: {ex}")
        return

    # Summary
    active_count   = sum(1 for h in heads if h["is_active"])
    inactive_count = len(heads) - active_count
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Categories", len(heads))
    c2.metric("Active", active_count)
    c3.metric("Inactive", inactive_count)

    st.divider()

    _show_heads_table(heads)

    st.divider()

    # Action tabs
    tab_add, tab_edit, tab_deact = st.tabs(
        ["Add New Category", "Edit Category", "Deactivate / Reactivate"]
    )

    with tab_add:
        _tab_add(conn, heads)

    with tab_edit:
        _tab_edit(conn, heads)

    with tab_deact:
        _tab_deactivate(conn, heads)

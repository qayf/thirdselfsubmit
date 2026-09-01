"""End-to-end checks for the Streamlit submission flow.

Run with:  .venv/bin/python test_submission_flow.py
Uses Streamlit's AppTest harness, which executes the real script headlessly.
"""

import re
import shutil
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = "streamlit_app.py"
LONG_TEXT = "I stopped counting the hours somewhere around the second winter. " * 12
PASSES = []
FAILS = []


def check(label, condition, detail=""):
    (PASSES if condition else FAILS).append(label)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -> ' + detail if detail and not condition else ''}")


def fresh():
    shutil.rmtree("data", ignore_errors=True)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def fill_common(at, *, name="Mira Osei", email="mira@example.com", title="The Room Where I Kept Scrolling"):
    # Address widgets by key: Streamlit orders column children left-column-first,
    # so positional indexes do not follow visual order.
    at.text_input(key="f_name").set_value(name)
    at.text_input(key="f_email").set_value(email)
    at.text_input(key="f_title").set_value(title)
    at.selectbox(key="f_category").set_value("attention")
    at.selectbox(key="f_form").set_value("essay")
    return at


def submit(at):
    at.button[0].click().run()
    return at


print("\n=== 1. App renders without exception ===")
at = fresh()
check("no uncaught exception on first render", not at.exception, str(at.exception))
check("form is present", len(at.text_input) > 0)
check("mode radio present", len(at.radio) == 1)
check(
    "ephemeral-storage warning shown when SMTP unset",
    any("not configured" in m.value for m in at.markdown),
)

print("\n=== 2. Empty submission is rejected ===")
at = fresh()
submit(at)
check("error shown", len(at.error) > 0)
if at.error:
    msg = at.error[0].value
    check("names the missing name", "your name" in msg, msg)
    check("names the missing email", "valid email" in msg, msg)
    check("names the missing consent", "confirmations" in msg, msg)
    check("no receipt issued", "receipt" not in at.session_state, msg)

print("\n=== 3. Invalid email is rejected ===")
at = fresh()
at.radio[0].set_value("Paste the text").run()
fill_common(at, email="notanemail")
at.text_area(key="f_text").set_value(LONG_TEXT)
at.checkbox(key="f_original").set_value(True)
at.checkbox(key="f_terms").set_value(True)
submit(at)
check("rejected", len(at.error) > 0 and "valid email" in at.error[0].value)

print("\n=== 4. Too-short pasted text is rejected ===")
at = fresh()
at.radio[0].set_value("Paste the text").run()
fill_common(at)
at.text_area(key="f_text").set_value("Too short.")
at.checkbox(key="f_original").set_value(True)
at.checkbox(key="f_terms").set_value(True)
submit(at)
check("rejected", len(at.error) > 0 and "at least 200 characters" in at.error[0].value)

print("\n=== 5. Missing consent is rejected even when everything else is valid ===")
at = fresh()
at.radio[0].set_value("Paste the text").run()
fill_common(at)
at.text_area(key="f_text").set_value(LONG_TEXT)
at.checkbox(key="f_original").set_value(True)   # original only
submit(at)
check("rejected", len(at.error) > 0 and "confirmations" in at.error[0].value)

print("\n=== 6. Valid pasted submission is accepted and stored ===")
at = fresh()
at.radio[0].set_value("Paste the text").run()
fill_common(at)
at.text_area(key="f_text").set_value(LONG_TEXT)
at.checkbox(key="f_original").set_value(True)
at.checkbox(key="f_terms").set_value(True)
submit(at)
check("no error", len(at.error) == 0, at.error[0].value if at.error else "")
reference = at.session_state["receipt"] if "receipt" in at.session_state else None
check("reference issued", bool(reference), str(reference))
if reference:
    check("reference format TSP-YYMMDD-XXXX",
          bool(re.fullmatch(r"TSP-\d{6}-[A-Z0-9]{4}", reference)), reference)

log = Path("data/submissions.jsonl")
check("written to the session cache", log.exists())
if log.exists():
    import json

    entry = json.loads(log.read_text().strip().splitlines()[-1])
    check("title stored", entry["title"] == "The Room Where I Kept Scrolling")
    check("email stored", entry["email"] == "mira@example.com")
    check("word count recorded", entry.get("wordCount", 0) > 100, str(entry.get("wordCount")))
    check("category stored as slug", entry["category"] == "attention")
    manuscript = Path("data/uploads") / entry["storedName"]
    check("manuscript file written", manuscript.exists())
    if manuscript.exists():
        body = manuscript.read_text()
        check("manuscript carries a header", entry["reference"] in body)
        check("manuscript carries the prose", "second winter" in body)

print("\n=== 7. Receipt replaces the form after success ===")
at.run()
check("receipt rendered", any("in our hands" in m.value for m in at.markdown))
check("form no longer rendered", len(at.text_input) == 0)

print("\n=== 7b. 'Send another piece' clears the previous writer's answers ===")
at.button[0].click().run()
check("form is back", len(at.text_input) > 0)
check("name field cleared", at.text_input(key="f_name").value in ("", None),
      repr(at.text_input(key="f_name").value))
check("title field cleared", at.text_input(key="f_title").value in ("", None),
      repr(at.text_input(key="f_title").value))
check("category cleared", at.selectbox(key="f_category").value is None,
      repr(at.selectbox(key="f_category").value))
check("consent unchecked", at.checkbox(key="f_original").value is False,
      repr(at.checkbox(key="f_original").value))

print("\n=== 8. Inbox requires a sign-in ===")
shutil.rmtree("data", ignore_errors=True)
at = AppTest.from_file(APP, default_timeout=30)
at.query_params["admin"] = "1"
at.run()
check("no exception on inbox route", not at.exception, str(at.exception))
check(
    "refuses without configured editors",
    len(at.error) > 0 and "No editors" in at.error[0].value,
    at.error[0].value if at.error else "no error raised",
)

print("\n=== 9. Inbox with editors configured asks for credentials ===")
at = AppTest.from_file(APP, default_timeout=30)
at.secrets["editors"] = {"mira": "correct-horse"}
at.query_params["admin"] = "1"
at.run()
check("sign-in form shown", len(at.text_input) == 2)
at.text_input[0].set_value("mira")
at.text_input[1].set_value("wrong-password")
at.button[0].click().run()
check("wrong password rejected", len(at.error) > 0 and "does not match" in at.error[0].value)
check("not signed in", "editor" not in at.session_state)

at.text_input[0].set_value("mira")
at.text_input[1].set_value("correct-horse")
at.button[0].click().run()
check("correct password accepted", at.session_state["editor"] == "mira")
check(
    "warns the list is not the archive",
    any("not the archive" in m.value for m in at.markdown),
)

shutil.rmtree("data", ignore_errors=True)
print(f"\n{'=' * 46}\n  {len(PASSES)} passed, {len(FAILS)} failed")
if FAILS:
    for f in FAILS:
        print(f"    FAILED: {f}")
    raise SystemExit(1)
print("  All checks passed.\n")

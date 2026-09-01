"""Third Self Project — writer submissions (Streamlit edition).

Deployed on Streamlit Community Cloud, where the container filesystem is
EPHEMERAL. Anything written to disk disappears on restart or redeploy, so
email is the durable archive: every accepted submission is sent to
NOTIFY_TO with the manuscript attached. The local copy under data/ exists
only so the in-app inbox works during a session.

Main file for Streamlit Cloud: streamlit_app.py
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import smtplib
import unicodedata
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DATA_DIR = Path("data")
UPLOAD_DIR = DATA_DIR / "uploads"
LOG_PATH = DATA_DIR / "submissions.jsonl"

MAX_UPLOAD_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXT = ("pdf", "doc", "docx", "txt", "rtf", "md")
MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 120_000

CATEGORIES = {
    "compulsion": "01 — Compulsion",
    "performance": "02 — Performance",
    "belonging": "03 — Belonging",
    "risk": "04 — Risk",
    "attention": "05 — Attention",
    "unsure": "Not sure / something else",
}

FORMS = {
    "essay": "Essay",
    "story": "Short story",
    "field-note": "Field note",
    "reported": "Reported piece",
    "poetry": "Poetry",
    "other": "Other",
}

REF_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no look-alikes
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def secret(key: str, default=None):
    """Read st.secrets without exploding when the key is absent."""
    try:
        return st.secrets[key]
    except Exception:
        return default


# --------------------------------------------------------------------------
# Design — the site's tokens, pushed through Streamlit's DOM
# --------------------------------------------------------------------------

STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&family=Space+Grotesk:wght@400;500;600;700&display=swap');

:root {
  --paper: #f8f6ef;
  --paper-warm: #f2eee1;
  --ink: #15232d;
  --ink-muted: #53616b;
  --ink-faint: #5c666e;
  --charcoal: #202a30;
  --orange: #ec7357;
  --orange-wash: #f9ded6;
  --blue: #b8d8ed;
  --blue-wash: #e3eff7;
  --lavender: #cdbce0;
  --yellow: #f3d56e;
  --font-display: "Space Grotesk", "Helvetica Neue", Arial, sans-serif;
  --font-serif: "Newsreader", Georgia, serif;
  --font-mono: "DM Mono", ui-monospace, Menlo, monospace;
}

/* Ground the whole app in paper, not Streamlit's default white. */
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background: var(--paper);
}
[data-testid="stHeader"] { border-bottom: 1px solid #15232d38; }
.block-container { max-width: 58rem; padding-top: 2.5rem; padding-bottom: 4rem; }

html, body, [data-testid="stAppViewContainer"] * {
  font-family: var(--font-display);
  color: var(--ink);
}

/* Streamlit's own heading rules outrank the wildcard above, so name ours. */
.tsp-title, .tsp-section-head, .tsp-wordmark, .tsp-card h3,
.tsp-entry h4, .tsp-receipt h2, .tsp-lede, .tsp-fact dd {
  font-family: var(--font-display) !important;
}
.tsp-title em, .tsp-section-head em, .tsp-wordmark em, .tsp-receipt h2 em {
  font-family: var(--font-serif) !important;
}
.tsp-label, .tsp-est, .tsp-fieldset-num, .tsp-card-kicker,
.tsp-fact dt, .tsp-tag, .tsp-entry-head, .tsp-receipt-kicker, .tsp-receipt-ref {
  font-family: var(--font-mono) !important;
}

/* --- Masthead --- */
.tsp-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding-bottom: 1rem; margin-bottom: 2.5rem;
  border-bottom: 1px solid #15232d38;
}
.tsp-wordmark { display: flex; align-items: center; gap: .5rem; font-size: 1.3rem; font-weight: 700; }
.tsp-wordmark em { font-family: var(--font-serif); font-style: italic; font-weight: 400; }
.tsp-est {
  font-family: var(--font-mono); font-size: .72rem; letter-spacing: .18em;
  color: var(--ink-faint); text-transform: uppercase;
}

/* --- Hero --- */
.tsp-label {
  display: flex; align-items: center; gap: .75rem;
  font-family: var(--font-mono); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-muted); margin-bottom: 1rem;
}
.tsp-label::before { content: ""; width: 2.75rem; height: 2px; background: var(--orange); }
.tsp-title {
  font-size: clamp(2.25rem, 1.6rem + 3vw, 3.75rem); font-weight: 700;
  line-height: .98; letter-spacing: -.025em; margin: 0 0 1.25rem;
}
.tsp-title em {
  font-family: var(--font-serif); font-style: italic; font-weight: 400;
  background: linear-gradient(var(--yellow), var(--yellow)) no-repeat 0 92%;
  background-size: 100% .3em; padding-inline: .06em;
}
.tsp-lede { font-size: 1.05rem; color: var(--ink-muted); line-height: 1.62; max-width: 46ch; }

.tsp-facts {
  display: flex; flex-wrap: wrap; gap: .75rem 2rem;
  margin: 1.75rem 0 2.5rem; padding-top: 1rem; border-top: 1px solid var(--ink);
}
.tsp-fact dt {
  font-family: var(--font-mono); font-size: .68rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--ink-faint); margin-bottom: 2px;
}
.tsp-fact dd { margin: 0; font-weight: 500; font-size: .9rem; }

/* --- Cards --- */
.tsp-card {
  border: 2px solid var(--ink); background: var(--blue-wash);
  box-shadow: 6px 6px 0 var(--blue); padding: 1.5rem; margin-bottom: 2.5rem;
}
.tsp-card h3 { font-size: 1.35rem; font-weight: 700; letter-spacing: -.015em; margin: .75rem 0 1rem; }
.tsp-card ol { margin: 0; padding-left: 1.1rem; }
.tsp-card li { font-size: .9rem; line-height: 1.5; margin-bottom: .5rem; }
.tsp-card-kicker {
  display: flex; justify-content: space-between; font-family: var(--font-mono);
  font-size: .7rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-muted); padding-bottom: .6rem; border-bottom: 1px solid var(--ink);
}

.tsp-section-head {
  font-size: clamp(1.6rem, 1.3rem + 1.4vw, 2.4rem); font-weight: 700;
  letter-spacing: -.025em; margin: 0 0 .4rem;
}
.tsp-section-head em { font-family: var(--font-serif); font-style: italic; font-weight: 400; }
.tsp-fieldset-num {
  font-family: var(--font-mono); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-faint);
  padding-bottom: .5rem; border-bottom: 1px solid var(--ink);
  margin: 2rem 0 1rem; display: block;
}

/* --- Streamlit widgets, dressed to match --- */
[data-testid="stForm"] {
  border: 2px solid var(--ink); border-radius: 0; background: var(--paper);
  box-shadow: 3px 3px 0 var(--ink); padding: 1.75rem;
}

.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
  border-radius: 0 !important; border: 1px solid var(--ink) !important;
  background: var(--paper) !important; font-size: .92rem !important;
}
.stTextInput input:focus, .stTextArea textarea:focus { box-shadow: none !important; }
.stTextArea textarea { font-family: var(--font-serif) !important; font-size: 1rem !important; line-height: 1.6 !important; }

[data-testid="stWidgetLabel"] p {
  font-family: var(--font-mono) !important; font-size: .72rem !important;
  letter-spacing: .12em !important; text-transform: uppercase;
  color: var(--ink) !important; font-weight: 400 !important;
}

[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed var(--ink) !important; border-radius: 0 !important;
  background: var(--paper-warm) !important;
}

/* Radio row reads as the site's segmented control. */
[role="radiogroup"] { gap: .5rem !important; }

[data-testid="stFormSubmitButton"] button, .stButton button {
  border-radius: 0 !important; border: 2px solid var(--ink) !important;
  background: var(--ink) !important; color: var(--paper) !important;
  font-weight: 700 !important; padding: .7rem 1.5rem !important;
  box-shadow: 6px 6px 0 var(--orange); transition: transform .14s, box-shadow .14s;
}
[data-testid="stFormSubmitButton"] button:hover, .stButton button:hover {
  transform: translate(-2px, -2px); box-shadow: 8px 8px 0 var(--orange);
  background: var(--ink) !important; color: var(--paper) !important;
}

/* --- Receipt --- */
.tsp-receipt {
  border: 3px solid var(--ink); background: var(--charcoal);
  box-shadow: 6px 6px 0 var(--blue); padding: 2rem; color: var(--paper);
}
.tsp-receipt * { color: var(--paper) !important; }
.tsp-receipt-kicker {
  font-family: var(--font-mono); font-size: .72rem; letter-spacing: .16em;
  text-transform: uppercase; color: var(--blue) !important;
  padding-bottom: .75rem; border-bottom: 1px solid #f8f6ef42;
}
.tsp-receipt h2 { font-size: 1.8rem; font-weight: 700; letter-spacing: -.02em; margin: 1rem 0 .5rem; }
.tsp-receipt h2 em { font-family: var(--font-serif); font-style: italic; font-weight: 400; }
.tsp-receipt-ref {
  display: inline-block; margin-top: 1.25rem; border: 1px solid var(--paper);
  padding: .6rem 1.1rem; font-family: var(--font-mono); font-size: .9rem; letter-spacing: .1em;
}

/* --- Inbox --- */
.tsp-entry {
  border: 2px solid var(--ink); background: var(--paper);
  box-shadow: 3px 3px 0 var(--ink); padding: 1.25rem; margin-bottom: 1.25rem;
}
.tsp-entry--flagged { box-shadow: 6px 6px 0 var(--orange); }
.tsp-entry-head {
  display: flex; justify-content: space-between; flex-wrap: wrap; gap: .5rem;
  font-family: var(--font-mono); font-size: .7rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted);
  padding-bottom: .5rem; border-bottom: 1px solid #15232d38;
}
.tsp-entry h4 { font-size: 1.25rem; font-weight: 700; margin: .75rem 0 .25rem; letter-spacing: -.015em; }
.tsp-tag {
  display: inline-block; font-family: var(--font-mono); font-size: .68rem;
  letter-spacing: .06em; text-transform: uppercase; border: 1px solid #15232d38;
  padding: .2rem .45rem; margin: .5rem .3rem 0 0; color: var(--ink-muted);
}
.tsp-tag--flag { background: var(--orange-wash); border-color: var(--orange); color: var(--ink); }

.tsp-warn {
  border: 2px solid var(--orange); background: var(--orange-wash);
  padding: 1rem 1.25rem; margin-bottom: 1.5rem; font-size: .9rem; line-height: 1.55;
}

#MainMenu, footer { visibility: hidden; }
</style>
"""

EYE_SVG = (
    '<svg width="24" height="24" viewBox="0 0 32 32" fill="none">'
    '<path d="M2 16s5.2-8.5 14-8.5S30 16 30 16s-5.2 8.5-14 8.5S2 16 2 16Z" '
    'stroke="#15232D" stroke-width="2" stroke-linejoin="round"/>'
    '<circle cx="16" cy="16" r="4.25" fill="#B8D8ED" stroke="#15232D" stroke-width="2"/></svg>'
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def make_reference() -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d")
    tail = "".join(secrets.choice(REF_ALPHABET) for _ in range(4))
    return f"TSP-{stamp}-{tail}"


def slugify(value: str, fallback: str = "untitled") -> str:
    norm = unicodedata.normalize("NFKD", value)
    cleaned = re.sub(r"[^\w\s-]", "", norm).strip().lower()
    slug = re.sub(r"\s+", "-", cleaned)[:60]
    return slug or fallback


def extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def word_count(text: str) -> int:
    return len(text.split())


def clean(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    stripped = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return stripped.strip()[:limit]


# --------------------------------------------------------------------------
# Storage — email is the archive, disk is only a session cache
# --------------------------------------------------------------------------


def mail_configured() -> bool:
    return bool(secret("SMTP_HOST") and secret("NOTIFY_TO"))


def send_notification(entry: dict, payload: bytes, filename: str) -> tuple[bool, str]:
    """Email the submission with the manuscript attached.

    Returns (ok, detail). A failure here is the difference between keeping and
    losing the submission on an ephemeral host, so it is surfaced, not swallowed.
    """
    if not mail_configured():
        return False, "SMTP is not configured"

    lines = [
        f"Reference:  {entry['reference']}",
        f"From:       {entry['name']} <{entry['email']}>",
    ]
    if entry.get("pronouns"):
        lines.append(f"Pronouns:   {entry['pronouns']}")
    if entry.get("location"):
        lines.append(f"Based in:   {entry['location']}")
    lines += [
        f"Title:      {entry['title']}",
        f"Issue:      {CATEGORIES.get(entry['category'], entry['category'])}",
        f"Form:       {FORMS.get(entry['form'], entry['form'])}",
        f"Delivery:   {entry['mode']} — {entry.get('originalName', '')}",
    ]
    if entry.get("wordCount"):
        lines.append(f"Length:     {entry['wordCount']} words")
    if entry.get("published"):
        lines.append(f"Published:  {entry['published']}")
    if entry.get("sensitive"):
        lines.append("FLAGGED:    contains sensitive material")
    if entry.get("bio"):
        lines += ["", "Bio:", entry["bio"]]
    if entry.get("notes"):
        lines += ["", "Notes:", entry["notes"]]

    message = EmailMessage()
    message["Subject"] = f"[Submission] {entry['title']} — {entry['name']}"
    message["From"] = secret("NOTIFY_FROM", secret("SMTP_USER", "submissions@localhost"))
    message["To"] = secret("NOTIFY_TO")
    message["Reply-To"] = entry["email"]
    message.set_content("\n".join(lines))

    guessed, _ = mimetypes.guess_type(filename)
    maintype, subtype = (guessed or "application/octet-stream").split("/", 1)
    message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)

    host = secret("SMTP_HOST")
    port = int(secret("SMTP_PORT", 587))
    user = secret("SMTP_USER")
    password = secret("SMTP_PASS")

    try:
        if str(secret("SMTP_SECURE", "false")).lower() == "true":
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            if str(secret("SMTP_SECURE", "false")).lower() != "true":
                server.starttls()
            if user:
                server.login(user, password)
            server.send_message(message)
        return True, "sent"
    except Exception as error:  # noqa: BLE001 - surfaced to the caller
        return False, str(error)


def save_locally(entry: dict, payload: bytes, filename: str) -> None:
    """Best-effort cache so the in-app inbox works during this session."""
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOAD_DIR / filename).write_bytes(payload)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001 - never block a submission on the cache
        pass


def load_submissions() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    entries = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(entries))


# --------------------------------------------------------------------------
# The inbox
# --------------------------------------------------------------------------


def editors() -> dict:
    raw = secret("editors", {})
    try:
        return dict(raw)
    except Exception:
        return {}


def render_inbox() -> None:
    st.markdown(
        '<p class="tsp-label">Editorial / Private</p>'
        '<h1 class="tsp-section-head">Submissions <em>inbox</em>.</h1>',
        unsafe_allow_html=True,
    )

    people = editors()
    if not people:
        st.error(
            "No editors are configured. Add an [editors] section to your Streamlit "
            "secrets before using the inbox."
        )
        return

    if not st.session_state.get("editor"):
        with st.form("signin"):
            st.markdown('<span class="tsp-fieldset-num">Sign in</span>', unsafe_allow_html=True)
            who = st.text_input("Editor")
            secret_word = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in"):
                if who in people and secrets.compare_digest(str(secret_word), str(people[who])):
                    st.session_state["editor"] = who
                    st.rerun()
                else:
                    st.error("That does not match an editor account.")
        return

    st.markdown(
        f'<p class="tsp-entry-head" style="border:0">Signed in as {st.session_state["editor"]}</p>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="tsp-warn"><strong>This list is not the archive.</strong> '
        "Streamlit Cloud wipes the container's disk on restart, so entries here vanish "
        "when the app sleeps. The emailed copies are the permanent record.</div>",
        unsafe_allow_html=True,
    )

    entries = load_submissions()
    if not entries:
        st.info("Nothing in this session yet. Check the notification inbox for the full archive.")
        return

    for entry in entries:
        flagged = " tsp-entry--flagged" if entry.get("sensitive") else ""
        tags = [
            CATEGORIES.get(entry.get("category"), entry.get("category", "")),
            FORMS.get(entry.get("form"), entry.get("form", "")),
            f"{entry.get('wordCount', '?')} words" if entry.get("wordCount") else entry.get("mode", ""),
        ]
        if entry.get("sensitive"):
            tags.append("SENSITIVE")
        tag_html = "".join(
            f'<span class="tsp-tag{" tsp-tag--flag" if tag == "SENSITIVE" else ""}">{tag}</span>'
            for tag in tags if tag
        )
        received = entry.get("receivedAt", "")[:16].replace("T", " ")

        st.markdown(
            f'<div class="tsp-entry{flagged}">'
            f'<div class="tsp-entry-head"><span>{entry.get("reference","")}</span>'
            f"<span>{received}</span></div>"
            f'<h4>{entry.get("title","")}</h4>'
            f'<p style="color:var(--ink-muted);font-size:.9rem;margin:0">'
            f'{entry.get("name","")} — {entry.get("email","")}</p>'
            f"<p style='margin:0'>{tag_html}</p></div>",
            unsafe_allow_html=True,
        )

        stored = UPLOAD_DIR / entry.get("storedName", "")
        if entry.get("storedName") and stored.exists():
            st.download_button(
                "Download the work",
                data=stored.read_bytes(),
                file_name=entry.get("originalName", stored.name),
                key=f"dl-{entry['reference']}",
            )


# --------------------------------------------------------------------------
# The form
# --------------------------------------------------------------------------


def render_receipt() -> None:
    reference = st.session_state["receipt"]
    st.markdown(
        '<div class="tsp-receipt">'
        f'<p class="tsp-receipt-kicker">Submission received / '
        f'{datetime.now().strftime("%b %d, %Y").upper()}</p>'
        "<h2>Thank you. It's <em>in our hands</em> now.</h2>"
        "<p>We read every submission ourselves, and we reply to every one — usually "
        "within four to six weeks. Keep the reference below in case you need to write "
        "to us about it.</p>"
        f'<p class="tsp-receipt-ref">REF {reference}</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    if st.button("Send another piece"):
        # Keyed widgets keep their values across reruns, so the next writer
        # would otherwise inherit the previous submission's answers.
        for key in [k for k in st.session_state if str(k).startswith("f_")]:
            st.session_state.pop(key, None)
        for key in ("receipt", "mode"):
            st.session_state.pop(key, None)
        st.rerun()


def render_form() -> None:
    st.markdown(
        '<p class="tsp-label">Submissions / Open call</p>'
        '<h1 class="tsp-title">Someone has to <em>write it down.</em></h1>'
        '<p class="tsp-lede">The Third Self Project publishes essays, stories, and field '
        "notes about how digital environments shape what we desire, how we behave, and who "
        "we become. If you have been paying attention, we want to read it.</p>"
        '<dl class="tsp-facts">'
        '<div class="tsp-fact"><dt>Reading period</dt><dd>Rolling — always open</dd></div>'
        '<div class="tsp-fact"><dt>Response time</dt><dd>4–6 weeks</dd></div>'
        '<div class="tsp-fact"><dt>Length</dt><dd>800–5,000 words</dd></div>'
        '<div class="tsp-fact"><dt>Rights</dt><dd>First publication, then yours</dd></div>'
        "</dl>"
        '<div class="tsp-card">'
        '<div class="tsp-card-kicker"><span>Fig. 02</span><span>Before you send</span></div>'
        "<h3>What we're looking for</h3><ol>"
        "<li>Writing rooted in something you actually observed — in yourself, in a room, in a feed.</li>"
        "<li>A piece that fits one of our five issues, or argues for a sixth.</li>"
        "<li>Finished drafts. We read the work, not the pitch.</li>"
        "<li>Any form: essay, story, reported piece, poem, or a short field note.</li>"
        "</ol></div>",
        unsafe_allow_html=True,
    )

    if not mail_configured():
        st.markdown(
            '<div class="tsp-warn"><strong>Email delivery is not configured.</strong> '
            "Submissions will save to this container's temporary disk and be lost when it "
            "restarts. Add SMTP settings to your Streamlit secrets before sharing this link.</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        '<h2 class="tsp-section-head">Your <em>submission</em>.</h2>',
        unsafe_allow_html=True,
    )

    # Outside the form: changing this must rerun so the right input appears.
    # Streamlit forms do not rerun on widget change, only on submit.
    mode = st.radio(
        "How would you like to send your work?",
        ["Upload a file", "Paste the text"],
        horizontal=True,
        key="mode",
    )

    with st.form("submission", clear_on_submit=False):
        st.markdown('<span class="tsp-fieldset-num">01 / About you</span>', unsafe_allow_html=True)
        left, right = st.columns(2)
        name = left.text_input("Full name *", max_chars=120, key="f_name")
        email = right.text_input("Email *", max_chars=200, key="f_email")
        pronouns = left.text_input("Pronouns (optional)", max_chars=60, placeholder="they/them", key="f_pronouns")
        location = right.text_input("Where you're based (optional)", max_chars=120, key="f_location")
        bio = st.text_area(
            "Short bio (optional)",
            max_chars=800,
            height=90,
            placeholder="A sentence or two we can run alongside the piece.",
            key="f_bio",
        )

        st.markdown('<span class="tsp-fieldset-num">02 / About the piece</span>', unsafe_allow_html=True)
        title = st.text_input("Title *", max_chars=200, key="f_title")
        cat_col, form_col = st.columns(2)
        category = cat_col.selectbox(
            "Closest issue *",
            options=list(CATEGORIES.keys()),
            format_func=lambda key: CATEGORIES[key],
            index=None,
            placeholder="Choose one…",
            key="f_category",
        )
        form_type = form_col.selectbox(
            "Form *",
            options=list(FORMS.keys()),
            format_func=lambda key: FORMS[key],
            index=None,
            placeholder="Choose one…",
            key="f_form",
        )
        published = st.text_input(
            "Has this been published before? (optional)",
            max_chars=300,
            placeholder="No — or paste the link",
            key="f_published",
        )
        notes = st.text_area(
            "Anything we should know (optional)",
            max_chars=1500,
            height=90,
            placeholder="Context, content warnings, simultaneous submissions, a deadline.",
            key="f_notes",
        )
        sensitive = st.checkbox(
            "This piece contains material about self-harm, addiction, or explicit sexual content.",
            key="f_sensitive",
        )

        st.markdown('<span class="tsp-fieldset-num">03 / The work</span>', unsafe_allow_html=True)
        upload = None
        pasted = ""
        if mode == "Upload a file":
            upload = st.file_uploader(
                f"Your manuscript — PDF, DOC, DOCX, TXT, RTF, or MD, up to {MAX_UPLOAD_MB} MB",
                type=list(ALLOWED_EXT),
                key="f_upload",
            )
        else:
            pasted = st.text_area(
                "Paste your piece",
                max_chars=MAX_TEXT_CHARS,
                height=320,
                placeholder="Paste the full text here. We'll keep the line breaks.",
                key="f_text",
            )
            if pasted.strip():
                st.caption(f"{word_count(pasted):,} words · {len(pasted):,} characters")

        st.markdown('<span class="tsp-fieldset-num">04 / Consent</span>', unsafe_allow_html=True)
        original = st.checkbox("This is my own work and I hold the rights to it. *", key="f_original")
        terms = st.checkbox(
            "I understand that sending work is not a guarantee of publication, and that "
            "the project may reply with edits or with a no. *",
            key="f_terms",
        )
        newsletter = st.checkbox(
            "Keep me on the contributor list — occasional calls for work, no more than monthly.",
            key="f_newsletter",
        )

        submitted = st.form_submit_button("Send submission →")

    if not submitted:
        return

    # ---- Validation ----
    name, email = clean(name, 120), clean(email, 200)
    title = clean(title, 200)
    problems = []
    if not name:
        problems.append("your name")
    if not EMAIL_RE.match(email):
        problems.append("a valid email address")
    if not title:
        problems.append("a title")
    if not category:
        problems.append("an issue category")
    if not form_type:
        problems.append("a form")

    payload, filename, original_name, counted = b"", "", "", 0
    if mode == "Upload a file":
        if upload is None:
            problems.append("an attached file")
        else:
            payload = upload.getvalue()
            if len(payload) > MAX_UPLOAD_BYTES:
                problems.append(
                    f"a file under {MAX_UPLOAD_MB} MB (yours is {len(payload) / 1024 / 1024:.1f} MB)"
                )
            elif not payload:
                problems.append("a file that is not empty")
            else:
                original_name = upload.name
                filename = f"{{ref}}__{slugify(Path(upload.name).stem, 'submission')}.{extension_of(upload.name)}"
    else:
        body = clean(pasted, MAX_TEXT_CHARS)
        if len(body) < MIN_TEXT_CHARS:
            problems.append(
                f"at least {MIN_TEXT_CHARS} characters of text (you have {len(body)})"
            )
        else:
            counted = word_count(body)

    if not original or not terms:
        problems.append("both required confirmations")

    if problems:
        st.error("This submission is missing " + ", ".join(problems) + ".")
        return

    # ---- Build and store ----
    reference = make_reference()
    entry = {
        "reference": reference,
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "email": email,
        "pronouns": clean(pronouns, 60),
        "location": clean(location, 120),
        "bio": clean(bio, 800),
        "title": title,
        "category": category,
        "form": form_type,
        "published": clean(published, 300),
        "notes": clean(notes, 1500),
        "sensitive": bool(sensitive),
        "newsletter": bool(newsletter),
        "mode": "file" if mode == "Upload a file" else "text",
    }

    if entry["mode"] == "file":
        filename = filename.replace("{ref}", reference)
        entry["originalName"] = original_name
    else:
        body = clean(pasted, MAX_TEXT_CHARS)
        header = f"{title}\n{name} <{email}>\n{reference} — {entry['receivedAt']}\n\n---\n\n"
        payload = (header + body).encode("utf-8")
        filename = f"{reference}__{slugify(title)}.txt"
        entry["originalName"] = f"{title}.txt"
        entry["wordCount"] = counted

    entry["storedName"] = filename
    entry["bytes"] = len(payload)

    sent, detail = send_notification(entry, payload, entry["originalName"] or filename)
    save_locally(entry, payload, filename)

    if not sent and mail_configured():
        # The disk here is ephemeral, so a failed send means this may be the only
        # copy. Say so rather than showing a clean confirmation.
        st.error(
            "We saved your piece but could not deliver the notification email "
            f"({detail}). Please email submissions@thirdselfproject.org with your "
            f"reference {reference} so we can be sure it reached us."
        )
        return

    st.session_state["receipt"] = reference
    st.rerun()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Submit your writing — Third Self Project",
        page_icon="👁",
        layout="centered",
    )
    st.markdown(STYLES, unsafe_allow_html=True)
    st.markdown(
        '<div class="tsp-header">'
        f'<div class="tsp-wordmark">{EYE_SVG}<span>Third <em>Self</em> Project</span></div>'
        '<span class="tsp-est">Est. 2026</span></div>',
        unsafe_allow_html=True,
    )

    if st.query_params.get("admin") == "1":
        render_inbox()
    elif st.session_state.get("receipt"):
        render_receipt()
    else:
        render_form()


if __name__ == "__main__":
    main()

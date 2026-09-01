# Third Self Project — Submissions

A small, self-contained submission form for writers. Someone fills it in, attaches a PDF
(or pastes their piece directly), and it lands on your server. You read everything at `/admin`.

No database, no third-party form service, no accounts to create. Submissions are plain files
on disk, so they are easy to back up and impossible to get locked out of.

## Running it

```bash
npm install
npm start
```

- Form → <http://localhost:3000/>
- Inbox → <http://localhost:3000/admin>

`npm run dev` does the same thing but restarts when you edit a file.

## Where submissions go

```
data/
  submissions.jsonl     one JSON line per submission, newest appended last
  uploads/              the work itself, named <reference>__<slug>.<ext>
```

Pasted text is written out as a `.txt` file too, with a short header naming the writer and the
reference, so every submission is a file you can open, forward, or drop into an editor.

`data/` is gitignored. It holds people's names, emails, and unpublished writing — keep it out of
version control, and back it up somewhere private.

## The inbox

`/admin` lists every submission newest-first, with the writer's details, their category and form,
whether they flagged sensitive material, and a download link for the work.

Access is deliberately awkward to get wrong:

- **No editors configured** — `/admin` answers only on `localhost`. Fine on your own machine.
- **`ADMIN_USERS` set** — HTTP basic auth, from anywhere.

A server reachable from the internet with no editors configured returns a 503 telling you to set
some, rather than quietly serving people's unpublished writing to anyone who finds the URL.

### Giving several people access

Each editor gets their own login, so you can remove one person without resetting everyone:

```
ADMIN_USERS=mira:xK9-longrandomstring,rob:7Qm-anotherlongone
```

Generate a password per person:

```bash
node -e "console.log(require('crypto').randomBytes(12).toString('base64url'))"
```

The inbox shows who is signed in, downloads are logged as `[download] <file> by <editor>`, and
failed sign-ins are logged with the username tried. To revoke someone, delete their pair and
restart. Send each person their password over something private — not the same email thread as
the link.

## Configuration

Copy `.env.example` to `.env` and edit. Every value is optional; the defaults work for local use.

| Variable | Default | What it does |
| --- | --- | --- |
| `PORT` | `3000` | Port to listen on |
| `ADMIN_USERS` | *(unset)* | `name:password` pairs, comma-separated. Unset = localhost only |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `editor` / *(unset)* | Single-editor shortcut; added to `ADMIN_USERS` if set |
| `DATA_DIR` | `./data` | Absolute path to a persistent disk in production |
| `MAX_UPLOAD_MB` | `10` | Largest accepted file |
| `RATE_LIMIT_PER_HOUR` | `5` | Accepted submissions per IP per hour |
| `TRUST_PROXY` | `0` | Set to `1` behind one reverse proxy, so rate limiting sees real IPs |
| `SMTP_HOST` | *(unset)* | Set this **and** `NOTIFY_TO` to turn on email notifications |
| `SMTP_PORT` / `SMTP_SECURE` | `587` / `false` | |
| `SMTP_USER` / `SMTP_PASS` | *(unset)* | Omit both for an unauthenticated relay |
| `NOTIFY_FROM` / `NOTIFY_TO` | *(unset)* | Sender, and the inbox that gets each submission |

Email is genuinely optional. With `SMTP_HOST` unset nothing is sent and nothing breaks —
submissions still save to disk. If a send fails, the submission is already stored; the error is
logged and the writer still gets their confirmation.

## What the form accepts

- **Upload** — PDF, DOC, DOCX, TXT, RTF, MD, up to 10 MB, drag-and-drop or file picker.
- **Paste** — up to 120,000 characters with a live word count. Minimum 200 characters.

Writers pick one or the other; switching clears the side they left, so a submission is never
ambiguous about which one is the real piece.

Required: name, a valid email, a title, an issue category, a form, the work itself, and the two
consent checkboxes. Everything else — pronouns, location, bio, prior publication, notes — is
optional and passed straight through to the inbox.

Spam handling is a hidden honeypot field plus the per-IP rate limit. Only *accepted* submissions
count against the limit, so someone who fumbles the form five times can still send their piece.

## Design

The page reuses the design tokens from thirdselfproject.org — Space Grotesk, Newsreader italic,
DM Mono, the paper/ink palette, and the hard offset print shadows — so it reads as part of the
same project. They live at the top of `public/styles.css`; change them there and both the form
and the inbox follow.

## Deploying

It is one Node process plus a writable folder, so anywhere that runs Node works — Render,
Railway, Fly.io, or a plain VPS.

**The one thing you cannot skip: a persistent disk.** Most free tiers give a container an
ephemeral filesystem, which is wiped on every redeploy and on some restarts. On one of those,
submissions disappear without an error — you would not find out until a writer asked why they
never heard back. Budget for the paid tier that includes a disk, or use a VPS.

### The steps, on any host

1. Push this folder to a Git repo and connect it. Build: `npm install`. Start: `npm start`.
2. Attach a persistent disk and set `DATA_DIR` to its mount path (e.g. `/data`).
3. Set `ADMIN_USERS` with one `name:password` pair per editor.
4. Set `TRUST_PROXY=1` — these hosts all put a proxy in front, and without this every request
   looks like it comes from the proxy, so one spammer would rate-limit everybody.
5. Confirm HTTPS is on. Basic auth base64-encodes credentials, it does not encrypt them; over
   plain HTTP an editor password is readable in transit.
6. Point a subdomain at it — `submissions.thirdselfproject.org` via a CNAME — and link it from
   the main site.

### Checking it worked

```bash
curl -s https://your-url/healthz                      # {"ok":true}
curl -s -o /dev/null -w "%{http_code}\n" https://your-url/admin   # 401, not 503 or 200
```

A `503` means no editors are configured. A `200` with no password prompt means the inbox is
open to the world — fix that before sharing the link.

Then send yourself a real submission through the form and confirm it appears in `/admin`.
Redeploy once, and confirm it is *still* there — that is the test that catches a disk which
is not actually persistent.

### Backups

Everything lives in `DATA_DIR`. Copy it somewhere else on a schedule:

```bash
rsync -az --delete your-server:/data/ ~/backups/third-self-submissions/
```

Turning on email notifications also gives you an off-server copy of every submission, with the
file attached, in whatever inbox you point `NOTIFY_TO` at.

## Files

```
server.js            Express app: validation, storage, admin inbox, optional email
public/index.html    The form
public/styles.css    Design tokens + all styling, shared with the inbox
public/app.js        Upload/paste toggle, inline validation, receipt
```

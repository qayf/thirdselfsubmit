/* Third Self Project — submission server.
   Saves every submission to data/submissions.jsonl and the work itself to
   data/uploads/. Editors read them at /admin. Email is optional. */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import multer from "multer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/* ---------- Config ---------- */

const PORT = Number(process.env.PORT || 3000);
const MAX_UPLOAD_MB = Number(process.env.MAX_UPLOAD_MB || 10);
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const RATE_LIMIT_PER_HOUR = Number(process.env.RATE_LIMIT_PER_HOUR || 5);
const ADMIN_USER = process.env.ADMIN_USER || "editor";
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "";

// Each editor gets their own login, so you can remove one person's access
// without resetting everyone else's. Format: "mira:pass1,rob:pass2"
function parseEditors(raw) {
  const editors = new Map();
  for (const pair of String(raw || "").split(",")) {
    const entry = pair.trim();
    const split = entry.indexOf(":");
    if (split < 1) continue;
    const user = entry.slice(0, split).trim();
    const pass = entry.slice(split + 1);
    if (user && pass) editors.set(user, pass);
  }
  return editors;
}

const EDITORS = parseEditors(process.env.ADMIN_USERS);
if (ADMIN_PASSWORD) EDITORS.set(ADMIN_USER, ADMIN_PASSWORD);

// Point DATA_DIR at a mounted volume in production; a redeploy wipes
// anything living on the container's own filesystem.
const DATA_DIR = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.join(__dirname, "data");
const UPLOAD_DIR = path.join(DATA_DIR, "uploads");
const LOG_PATH = path.join(DATA_DIR, "submissions.jsonl");

fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const ALLOWED_EXT = new Set(["pdf", "doc", "docx", "txt", "rtf", "md"]);
const MIN_TEXT_CHARS = 200;
const MAX_TEXT_CHARS = 120000;

const CATEGORIES = {
  compulsion: "Compulsion",
  performance: "Performance",
  belonging: "Belonging",
  risk: "Risk",
  attention: "Attention",
  unsure: "Not sure / other",
};

const FORMS = {
  essay: "Essay",
  story: "Short story",
  "field-note": "Field note",
  reported: "Reported piece",
  poetry: "Poetry",
  other: "Other",
};

/* ---------- Helpers ---------- */

const REF_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"; // no look-alikes

function makeReference(date = new Date()) {
  const stamp = date.toISOString().slice(2, 10).replace(/-/g, "");
  const bytes = crypto.randomBytes(4);
  let tail = "";
  for (const byte of bytes) tail += REF_ALPHABET[byte % REF_ALPHABET.length];
  return `TSP-${stamp}-${tail}`;
}

function extensionOf(name) {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function slugify(value, fallback = "untitled") {
  const slug = String(value)
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase()
    .slice(0, 60);
  return slug || fallback;
}

// Strip control characters, then trim and cap length.
function clean(value, max) {
  if (typeof value !== "string") return "";
  // Keeps tab/newline/carriage-return so pasted prose survives intact.
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim().slice(0, max);
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function countWords(text) {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

/* ---------- Rate limiting (in-memory, per IP) ---------- */

const hits = new Map();

function windowStart() {
  return Date.now() - 60 * 60 * 1000;
}

function overLimit(ip) {
  const recent = (hits.get(ip) || []).filter((t) => t > windowStart());
  hits.set(ip, recent);
  return recent.length >= RATE_LIMIT_PER_HOUR;
}

// Only accepted submissions count, so a writer who fumbles the form
// half a dozen times is never locked out of sending the real thing.
function recordSubmission(ip) {
  const recent = (hits.get(ip) || []).filter((t) => t > windowStart());
  recent.push(Date.now());
  hits.set(ip, recent);
  if (hits.size > 5000) {
    const cutoff = windowStart();
    for (const [key, times] of hits) {
      if (!times.some((t) => t > cutoff)) hits.delete(key);
    }
  }
}

/* ---------- Optional email notification ---------- */

let mailer = null;
if (process.env.SMTP_HOST && process.env.NOTIFY_TO) {
  const { default: nodemailer } = await import("nodemailer");
  mailer = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE) === "true",
    auth: process.env.SMTP_USER
      ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
      : undefined,
  });
  console.log(`[mail] notifications enabled -> ${process.env.NOTIFY_TO}`);
}

async function notify(entry) {
  if (!mailer) return;
  const lines = [
    `Reference:  ${entry.reference}`,
    `From:       ${entry.name} <${entry.email}>`,
    entry.pronouns ? `Pronouns:   ${entry.pronouns}` : null,
    entry.location ? `Based in:   ${entry.location}` : null,
    `Title:      ${entry.title}`,
    `Issue:      ${CATEGORIES[entry.category] || entry.category}`,
    `Form:       ${FORMS[entry.form] || entry.form}`,
    `Delivery:   ${entry.mode === "file" ? `file — ${entry.originalName}` : `pasted text — ${entry.wordCount} words`}`,
    entry.published ? `Published:  ${entry.published}` : null,
    entry.sensitive ? "FLAGGED:    contains sensitive material" : null,
    "",
    entry.bio ? `Bio:\n${entry.bio}\n` : null,
    entry.notes ? `Notes:\n${entry.notes}\n` : null,
  ].filter(Boolean);

  try {
    await mailer.sendMail({
      from: process.env.NOTIFY_FROM || "submissions@localhost",
      to: process.env.NOTIFY_TO,
      replyTo: entry.email,
      subject: `[Submission] ${entry.title} — ${entry.name}`,
      text: lines.join("\n"),
      attachments: entry.storedName
        ? [
            {
              filename: entry.originalName || entry.storedName,
              path: path.join(UPLOAD_DIR, entry.storedName),
            },
          ]
        : [],
    });
  } catch (error) {
    // A mail failure must never lose a submission — it is already on disk.
    console.error("[mail] notification failed:", error.message);
  }
}

/* ---------- Upload handling ---------- */

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOAD_DIR),
  filename: (req, file, cb) => {
    const ext = extensionOf(file.originalname);
    const base = slugify(path.basename(file.originalname, `.${ext}`), "submission");
    cb(null, `${req.reference}__${base}.${ext}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1, fields: 25 },
  fileFilter: (_req, file, cb) => {
    if (ALLOWED_EXT.has(extensionOf(file.originalname))) return cb(null, true);
    cb(new Error("UNSUPPORTED_TYPE"));
  },
}).single("file");

/* ---------- App ---------- */

const app = express();
app.disable("x-powered-by");
app.set("trust proxy", Number(process.env.TRUST_PROXY || 0));

app.use(
  express.static(path.join(__dirname, "public"), {
    extensions: ["html"],
    maxAge: process.env.NODE_ENV === "production" ? "1h" : 0,
  })
);

app.get("/healthz", (_req, res) => res.json({ ok: true }));

app.post("/api/submissions", (req, res) => {
  if (overLimit(req.ip)) {
    return res.status(429).json({
      error:
        "That's several submissions from this connection in the last hour. Please try again later, or email us directly.",
    });
  }

  req.reference = makeReference();

  upload(req, res, async (uploadError) => {
    const discard = () => {
      if (req.file) fs.promises.unlink(req.file.path).catch(() => {});
    };

    if (uploadError) {
      discard();
      if (uploadError.code === "LIMIT_FILE_SIZE") {
        return res.status(413).json({
          error: `That file is over the ${MAX_UPLOAD_MB} MB limit. Try a PDF export, or paste the text instead.`,
        });
      }
      if (uploadError.message === "UNSUPPORTED_TYPE") {
        return res.status(415).json({
          error: "We can only read PDF, DOC, DOCX, TXT, RTF, and MD files.",
        });
      }
      console.error("[upload]", uploadError);
      return res.status(400).json({ error: "That upload didn't come through. Please try again." });
    }

    const body = req.body || {};

    // Honeypot: bots fill every field they find.
    if (clean(body.website, 200)) {
      discard();
      return res.status(200).json({ ok: true, reference: req.reference });
    }

    const entry = {
      reference: req.reference,
      receivedAt: new Date().toISOString(),
      name: clean(body.name, 120),
      email: clean(body.email, 200),
      pronouns: clean(body.pronouns, 60),
      location: clean(body.location, 120),
      bio: clean(body.bio, 800),
      title: clean(body.title, 200),
      category: clean(body.category, 40),
      form: clean(body.form, 40),
      published: clean(body.published, 300),
      notes: clean(body.notes, 1500),
      sensitive: body.sensitive === "yes",
      newsletter: body.newsletter === "yes",
      mode: body.mode === "text" ? "text" : "file",
      ip: req.ip,
      userAgent: clean(req.get("user-agent"), 300),
    };

    const errors = [];
    if (!entry.name) errors.push("a name");
    if (!EMAIL_RE.test(entry.email)) errors.push("a valid email address");
    if (!entry.title) errors.push("a title");
    if (!CATEGORIES[entry.category]) errors.push("an issue category");
    if (!FORMS[entry.form]) errors.push("a form");
    if (body.original !== "yes" || body.terms !== "yes") errors.push("both required confirmations");

    const text = clean(body.text, MAX_TEXT_CHARS);
    if (entry.mode === "file") {
      if (!req.file) errors.push("an attached file");
    } else if (text.length < MIN_TEXT_CHARS) {
      errors.push(`at least ${MIN_TEXT_CHARS} characters of text`);
    }

    if (errors.length) {
      discard();
      return res.status(400).json({ error: `This submission is missing ${errors.join(", ")}.` });
    }

    try {
      if (entry.mode === "file") {
        entry.storedName = req.file.filename;
        entry.originalName = req.file.originalname;
        entry.bytes = req.file.size;
      } else {
        entry.storedName = `${entry.reference}__${slugify(entry.title)}.txt`;
        entry.originalName = `${entry.title}.txt`;
        const header = `${entry.title}\n${entry.name} <${entry.email}>\n${entry.reference} — ${entry.receivedAt}\n\n---\n\n`;
        await fs.promises.writeFile(path.join(UPLOAD_DIR, entry.storedName), header + text, "utf8");
        entry.bytes = Buffer.byteLength(header + text, "utf8");
        entry.wordCount = countWords(text);
      }

      await fs.promises.appendFile(LOG_PATH, JSON.stringify(entry) + "\n", "utf8");
    } catch (error) {
      discard();
      console.error("[store]", error);
      return res.status(500).json({
        error:
          "We couldn't save that on our end. Please try again, or email submissions@thirdselfproject.org.",
      });
    }

    recordSubmission(req.ip);
    console.log(`[submission] ${entry.reference} "${entry.title}" from ${entry.email} (${entry.mode})`);
    notify(entry); // fire and forget; the submission is already safe on disk

    res.status(201).json({ ok: true, reference: entry.reference });
  });
});

/* ---------- Admin ---------- */

function safeEqual(a, b) {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

function isLoopback(req) {
  const ip = req.ip || "";
  return ip === "::1" || ip === "127.0.0.1" || ip === "::ffff:127.0.0.1";
}

function requireAdmin(req, res, next) {
  if (EDITORS.size === 0) {
    // Unconfigured: usable on your own machine, never over the network.
    if (isLoopback(req)) {
      req.editor = "localhost";
      return next();
    }
    return res
      .status(503)
      .type("text/plain")
      .send("Set ADMIN_USERS (or ADMIN_PASSWORD) before exposing /admin to the network.");
  }

  const header = req.get("authorization") || "";
  const [scheme, encoded] = header.split(" ");
  if (scheme === "Basic" && encoded) {
    const [user, ...rest] = Buffer.from(encoded, "base64").toString("utf8").split(":");
    const pass = rest.join(":");
    const stored = EDITORS.get(user);
    if (stored && safeEqual(pass, stored)) {
      req.editor = user;
      return next();
    }
    console.warn(`[admin] failed sign-in as "${user}" from ${req.ip}`);
  }

  res.set("WWW-Authenticate", 'Basic realm="Third Self submissions", charset="UTF-8"');
  res.status(401).type("text/plain").send("Authentication required.");
}

async function readEntries() {
  let raw;
  try {
    raw = await fs.promises.readFile(LOG_PATH, "utf8");
  } catch {
    return [];
  }
  return raw
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .reverse();
}

function renderEntry(entry) {
  const size = entry.bytes ? `${(entry.bytes / 1024).toFixed(0)} KB` : "&mdash;";
  const delivery =
    entry.mode === "text"
      ? `Pasted text${entry.wordCount ? ` &middot; ${entry.wordCount.toLocaleString()} words` : ""}`
      : `File &middot; ${escapeHtml(entry.originalName || "")}`;

  return `<article class="entry${entry.sensitive ? " entry--flagged" : ""}">
    <header class="entry__head">
      <span>${escapeHtml(entry.reference)}</span>
      <span>${escapeHtml(new Date(entry.receivedAt).toLocaleString())}</span>
    </header>
    <h2 class="entry__title">${escapeHtml(entry.title)}</h2>
    <p class="entry__by">${escapeHtml(entry.name)}${entry.pronouns ? ` (${escapeHtml(entry.pronouns)})` : ""} &mdash; <a href="mailto:${escapeHtml(entry.email)}">${escapeHtml(entry.email)}</a>${entry.location ? ` &middot; ${escapeHtml(entry.location)}` : ""}</p>
    <p class="entry__tags">
      <span class="tag">${escapeHtml(CATEGORIES[entry.category] || entry.category)}</span>
      <span class="tag">${escapeHtml(FORMS[entry.form] || entry.form)}</span>
      <span class="tag">${delivery}</span>
      <span class="tag">${size}</span>
      ${entry.sensitive ? '<span class="tag tag--flag">Sensitive material</span>' : ""}
      ${entry.newsletter ? '<span class="tag">Wants the list</span>' : ""}
    </p>
    ${entry.bio ? `<p class="entry__block"><strong>Bio:</strong> ${escapeHtml(entry.bio)}</p>` : ""}
    ${entry.notes ? `<p class="entry__block"><strong>Notes:</strong> ${escapeHtml(entry.notes)}</p>` : ""}
    ${entry.published ? `<p class="entry__block"><strong>Previously published:</strong> ${escapeHtml(entry.published)}</p>` : ""}
    ${entry.storedName ? `<p class="entry__actions"><a class="entry__download" href="/admin/file/${encodeURIComponent(entry.storedName)}">Download the work &rarr;</a></p>` : ""}
  </article>`;
}

const ADMIN_STYLES = `
  .inbox { padding-block: var(--space-2xl); }
  .inbox__head { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:var(--space-m);
    padding-bottom:var(--space-m); border-bottom:var(--rule-strong); margin-bottom:var(--space-xl); }
  .inbox__title { font-size:var(--text-4xl); font-weight:700; letter-spacing:-.025em; }
  .inbox__title em { font-family:var(--font-serif); font-style:italic; font-weight:400; }
  .entry { border:var(--frame); background:var(--paper); box-shadow:var(--shadow-print-xs);
    padding:var(--space-l); margin-bottom:var(--space-l); }
  .entry--flagged { box-shadow:var(--shadow-print-orange); }
  .entry__head { display:flex; flex-wrap:wrap; justify-content:space-between; gap:var(--space-s);
    font-family:var(--font-mono); font-size:var(--text-2xs); letter-spacing:.1em; text-transform:uppercase;
    color:var(--ink-muted); padding-bottom:var(--space-xs); border-bottom:var(--rule); }
  .entry__title { font-size:var(--text-2xl); font-weight:700; letter-spacing:-.015em; margin-top:var(--space-m); }
  .entry__by { color:var(--ink-muted); font-size:var(--text-s); margin-top:var(--space-3xs); }
  .entry__tags { display:flex; flex-wrap:wrap; gap:var(--space-2xs); margin-top:var(--space-m); }
  .tag { font-family:var(--font-mono); font-size:var(--text-2xs); letter-spacing:.06em; text-transform:uppercase;
    border:var(--border-hair) solid var(--rule-color); padding:.25rem .5rem; color:var(--ink-muted); }
  .tag--flag { background:var(--orange-wash); border-color:var(--orange); color:var(--ink); }
  .entry__block { font-size:var(--text-s); margin-top:var(--space-s); max-width:70ch; }
  .entry__actions { margin-top:var(--space-m); padding-top:var(--space-s); border-top:var(--rule); }
  .entry__download { font-family:var(--font-mono); font-size:var(--text-2xs); letter-spacing:.1em;
    text-transform:uppercase; text-decoration:none; border-bottom:var(--border-bold) solid var(--orange); padding-bottom:3px; }
  .empty { border:var(--border-bold) dashed var(--ink); padding:var(--space-2xl); text-align:center;
    font-family:var(--font-mono); font-size:var(--text-2xs); letter-spacing:.1em; text-transform:uppercase; color:var(--ink-faint); }
`;

app.get("/admin", requireAdmin, async (req, res) => {
  const entries = await readEntries();
  const rows = entries.map(renderEntry).join("\n");

  res.type("html").send(`<!doctype html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Submissions inbox — Third Self Project</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/styles.css">
<style>${ADMIN_STYLES}</style>
</head><body>
<header class="site-header"><div class="shell site-header__inner">
  <a class="wordmark" href="/"><svg class="wordmark__eye" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M2 16s5.2-8.5 14-8.5S30 16 30 16s-5.2 8.5-14 8.5S2 16 2 16Z" stroke="#15232D" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="16" cy="16" r="4.25" fill="#B8D8ED" stroke="#15232D" stroke-width="2"/></svg>
    <span>Third <em>Self</em> Project</span></a>
  <span class="site-header__est">Inbox</span>
</div></header>
<main class="shell inbox">
  <div class="inbox__head">
    <div>
      <p class="section-label">Editorial / Private</p>
      <h1 class="inbox__title">Submissions <em>inbox</em>.</h1>
    </div>
    <p class="mono">${entries.length} received &middot; signed in as ${escapeHtml(req.editor)}</p>
  </div>
  ${rows || '<p class="empty">No submissions yet.</p>'}
</main>
</body></html>`);
});

app.get("/admin/file/:name", requireAdmin, (req, res) => {
  // Resolve inside UPLOAD_DIR only — never trust the path from the URL.
  const resolved = path.resolve(UPLOAD_DIR, path.basename(req.params.name));
  if (!resolved.startsWith(UPLOAD_DIR + path.sep)) return res.status(400).send("Bad request.");
  console.log(`[download] ${path.basename(resolved)} by ${req.editor}`);
  res.download(resolved, (error) => {
    if (error && !res.headersSent) res.status(404).send("That file is no longer on disk.");
  });
});

app.use((_req, res) => res.status(404).type("text/plain").send("Not found."));

app.listen(PORT, () => {
  console.log("\n  Third Self Project — submissions");
  console.log(`  Form   -> http://localhost:${PORT}/`);
  console.log(`  Inbox  -> http://localhost:${PORT}/admin`);
  const shown = path.relative(process.cwd(), DATA_DIR);
  console.log(`  Saving to ${shown.startsWith("..") ? DATA_DIR : shown}/`);
  console.log(
    EDITORS.size
      ? `  Inbox access: ${[...EDITORS.keys()].join(", ")}\n`
      : "  Note: no editors configured, so /admin only answers on localhost.\n"
  );
});

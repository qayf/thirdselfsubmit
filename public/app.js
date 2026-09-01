/* Third Self Project — submission form behaviour.
   Progressive: the form still posts without JS, this layer adds the
   upload/paste toggle, inline validation, and the in-place receipt. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const form = $("form");
  if (!form) return;

  const MAX_BYTES = 10 * 1024 * 1024;
  const ALLOWED_EXT = ["pdf", "doc", "docx", "txt", "rtf", "md"];
  const MIN_TEXT_CHARS = 200;

  /* ---------- Upload / paste toggle ---------- */

  const tabs = { file: $("tab-file"), text: $("tab-text") };
  const panels = { file: $("panel-file"), text: $("panel-text") };
  const modeInput = $("mode");

  function setMode(mode) {
    modeInput.value = mode;
    for (const key of ["file", "text"]) {
      const active = key === mode;
      tabs[key].setAttribute("aria-selected", String(active));
      panels[key].hidden = !active;
    }
    // Clearing the other side keeps the payload unambiguous.
    if (mode === "file") clearText();
    else clearFile();
    clearError(mode === "file" ? "text" : "file");
  }

  tabs.file.addEventListener("click", () => setMode("file"));
  tabs.text.addEventListener("click", () => setMode("text"));

  for (const key of ["file", "text"]) {
    tabs[key].addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next = key === "file" ? "text" : "file";
      setMode(next);
      tabs[next].focus();
    });
  }

  /* ---------- File field ---------- */

  const dropzone = $("dropzone");
  const fileInput = $("file");
  const chip = $("file-chip");
  const chipName = $("file-name");
  const chipMeta = $("file-meta");

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function extensionOf(name) {
    const dot = name.lastIndexOf(".");
    return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
  }

  function showFile(file) {
    chipName.textContent = file.name;
    chipMeta.textContent = `${formatBytes(file.size)} · ${extensionOf(file.name).toUpperCase() || "FILE"}`;
    chip.classList.add("is-visible");
  }

  function clearFile() {
    fileInput.value = "";
    chip.classList.remove("is-visible");
  }

  function validateFile(file) {
    if (!ALLOWED_EXT.includes(extensionOf(file.name))) {
      return `We can't read .${extensionOf(file.name) || "that"} files. Try PDF, DOC, DOCX, TXT, RTF, or MD.`;
    }
    if (file.size > MAX_BYTES) {
      return `That file is ${formatBytes(file.size)}. The limit is 10 MB — try a PDF export, or paste the text instead.`;
    }
    if (file.size === 0) return "That file appears to be empty.";
    return null;
  }

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (!file) return clearFile();
    const problem = validateFile(file);
    if (problem) {
      clearFile();
      setError("file", problem);
      return;
    }
    clearError("file");
    showFile(file);
  });

  $("file-remove").addEventListener("click", () => {
    clearFile();
    fileInput.focus();
  });

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-dragging");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-dragging");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });

  /* ---------- Pasted text ---------- */

  const textArea = $("text");
  const wordCount = $("word-count");
  const charCount = $("char-count");

  function countWords(value) {
    const trimmed = value.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  function updateCounts() {
    const words = countWords(textArea.value);
    wordCount.textContent = `${words.toLocaleString()} word${words === 1 ? "" : "s"}`;
    charCount.textContent = `${textArea.value.length.toLocaleString()} / 120,000 characters`;
  }

  function clearText() {
    textArea.value = "";
    updateCounts();
  }

  textArea.addEventListener("input", () => {
    updateCounts();
    if (textArea.value.trim().length >= MIN_TEXT_CHARS) clearError("text");
  });
  updateCounts();

  /* ---------- Validation ---------- */

  function fieldEl(name) {
    return form.querySelector(`[data-field="${name}"]`);
  }

  function setError(name, message) {
    const el = fieldEl(name);
    if (!el) return;
    el.classList.add(el.classList.contains("check") ? "check--invalid" : "field--invalid");
    const error = el.querySelector(".field__error");
    if (error && message) error.textContent = message;
    const control = el.querySelector("input, select, textarea");
    if (control) control.setAttribute("aria-invalid", "true");
  }

  function clearError(name) {
    const el = fieldEl(name);
    if (!el) return;
    el.classList.remove("field--invalid", "check--invalid");
    const control = el.querySelector("input, select, textarea");
    if (control) control.removeAttribute("aria-invalid");
  }

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function validate() {
    const problems = [];

    const required = [
      ["name", $("name").value.trim()],
      ["title", $("title").value.trim()],
      ["category", $("category").value],
      ["form", $("form-type").value],
    ];
    for (const [name, value] of required) {
      if (value) clearError(name);
      else problems.push(name);
    }

    const email = $("email").value.trim();
    if (EMAIL_RE.test(email)) clearError("email");
    else problems.push("email");

    if (modeInput.value === "file") {
      const file = fileInput.files[0];
      if (!file) {
        setError("file", "Please attach a file, or switch to pasting the text.");
        problems.push("file");
      } else {
        const problem = validateFile(file);
        if (problem) {
          setError("file", problem);
          problems.push("file");
        } else clearError("file");
      }
    } else {
      const value = textArea.value.trim();
      if (value.length < MIN_TEXT_CHARS) {
        setError("text", `That's ${value.length} characters — we need at least ${MIN_TEXT_CHARS} to read it as a piece.`);
        problems.push("text");
      } else clearError("text");
    }

    for (const name of ["original", "terms"]) {
      if ($(name).checked) clearError(name);
      else problems.push(name);
    }

    for (const name of problems) setError(name);
    return problems;
  }

  // Clear a field's error as soon as the writer fixes it.
  form.addEventListener("input", (e) => {
    const holder = e.target.closest("[data-field]");
    if (holder && e.target.value.trim()) clearError(holder.dataset.field);
  });
  form.addEventListener("change", (e) => {
    const holder = e.target.closest("[data-field]");
    if (!holder) return;
    if (e.target.type === "checkbox" ? e.target.checked : e.target.value) {
      clearError(holder.dataset.field);
    }
  });

  /* ---------- Submit ---------- */

  const submitBtn = $("submit");
  const status = $("status");
  const receipt = $("receipt");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    status.textContent = "";

    const problems = validate();
    if (problems.length) {
      status.textContent = `${problems.length} field${problems.length === 1 ? "" : "s"} still need${problems.length === 1 ? "s" : ""} attention.`;
      const first = fieldEl(problems[0]);
      const control = first?.querySelector("input, select, textarea");
      (control || first)?.focus({ preventScroll: true });
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    submitBtn.disabled = true;
    const originalLabel = submitBtn.innerHTML;
    submitBtn.textContent = "Sending…";

    try {
      const response = await fetch("/api/submissions", {
        method: "POST",
        body: new FormData(form),
      });
      const result = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(result.error || `The server replied ${response.status}. Please try again.`);
      }

      form.hidden = true;
      $("receipt-ref").textContent = `REF ${result.reference}`;
      $("receipt-date").textContent = new Date().toLocaleDateString("en-US", {
        year: "numeric", month: "short", day: "2-digit",
      }).toUpperCase();
      receipt.hidden = false;
      receipt.focus();
      receipt.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      status.textContent =
        error.message || "Something went wrong sending that. Please try again, or email us directly.";
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalLabel;
    }
  });

  $("another").addEventListener("click", () => {
    form.reset();
    clearFile();
    updateCounts();
    setMode("file");
    for (const el of form.querySelectorAll(".field--invalid, .check--invalid")) {
      el.classList.remove("field--invalid", "check--invalid");
    }
    status.textContent = "";
    submitBtn.disabled = false;
    submitBtn.innerHTML = 'Send submission <span aria-hidden="true">→</span>';
    receipt.hidden = true;
    form.hidden = false;
    $("name").focus();
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();

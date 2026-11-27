// Expense form helpers: the converted amount, the per-person split and the "Everyone" chip.
// The form works without this file; the server checks every value again.
(function () {
  const form = document.getElementById("expense-form");
  if (!form || form.dataset.ready) return;
  form.dataset.ready = "1";

  const WHOLE = new Set(["VND", "KHR", "JPY", "KRW", "IDR", "LAK"]);
  const base = form.dataset.base;
  const ratesEl = document.getElementById("trip-rates");
  const rates = ratesEl ? JSON.parse(ratesEl.textContent) : {};
  const amountInput = form.querySelector("[name=amount]");
  const preview = form.querySelector("[data-preview]");
  const split = form.querySelector("[data-split]");
  const people = [...form.querySelectorAll("[name=beneficiaries]")];
  const everyoneLabel = form.querySelector("[data-everyone]");
  const everyone = everyoneLabel && everyoneLabel.querySelector("input");

  function fmt(value, currency) {
    const digits = WHOLE.has(currency) && Number.isInteger(value) ? 0 : 2;
    return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + " " + currency;
  }
  function currency() {
    const chosen = form.querySelector("[name=currency]:checked") || form.querySelector("input[type=hidden][name=currency]");
    return chosen ? chosen.value : base;
  }
  function amount() {
    const value = parseFloat((amountInput.value || "").replace(/[,\s ]/g, ""));
    return value > 0 ? value : 0;
  }
  function update() {
    const cur = currency();
    const value = amount();
    const rate = parseFloat(rates[cur]);
    preview.textContent = value && cur !== base && rate > 0 ? "≈ " + fmt(Math.round((value / rate) * 100) / 100, base) : "";
    const n = people.filter((p) => p.checked).length;
    if (everyone) everyone.checked = n === people.length;
    if (!n) {
      split.textContent = "Pick at least one traveler.";
    } else {
      const each = value ? " · " + fmt(Math.round((value / n) * 100) / 100, cur) + " each" : "";
      split.textContent = n + (n === 1 ? " traveler" : " travelers") + each;
    }
  }

  if (everyone) {
    everyoneLabel.hidden = false;
    // "input", not "change": a checkbox fires "input" first, and the form's own "input"
    // listener would otherwise recount the people and undo this tap before we see it.
    everyone.addEventListener("input", () => {
      people.forEach((p) => (p.checked = everyone.checked));
    });
  }
  // The description box grows with its text (browsers without CSS field-sizing need this),
  // and Enter saves the form, as it did when the box was a one-line field.
  const description = form.querySelector("textarea[name=description]");
  if (description) {
    const grow = () => {
      description.style.height = "auto";
      description.style.height = description.scrollHeight + 2 + "px";
    };
    if (!CSS.supports("field-sizing", "content")) {
      description.addEventListener("input", grow);
      grow();
    }
    description.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
  }

  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
})();

// Expense types: "Add type" opens a small dialog (name and icon). A long press on a type shows a
// minus badge on every type; tapping a type then edits it, and the minus removes it after a
// confirmation. Every change is saved at once with fetch, so the expense being typed is kept.
(function () {
  const box = document.querySelector("[data-types]");
  const dialog = document.querySelector("[data-type-dialog]");
  if (!box || !dialog || box.dataset.ready) return;
  box.dataset.ready = "1";

  const chips = box.querySelector(".type-chips");
  const addButton = box.querySelector("[data-add-type]");
  const doneButton = box.querySelector("[data-types-done]");
  const form = dialog.querySelector("form");
  const nameInput = form.querySelector("[name=name]");
  const emojiButton = form.querySelector("[data-emoji-btn]");
  const grid = form.querySelector("[data-emoji-grid]");
  const error = form.querySelector("[data-error]");
  const title = form.querySelector("[data-title]");
  let editing = null; // The chip being edited, or null when adding.
  let longPressed = false;
  let ignoreClicksUntil = 0; // The tap that ends a long press must not choose the type.

  const headers = () => JSON.parse(document.body.getAttribute("hx-headers") || "{}");
  const busy = (promise) => (window.seBusy ? window.seBusy(promise) : promise);
  const urlFor = (template, id) => template.replace(/\/0\/(delete\/)?$/, `/${id}/$1`);
  async function post(url, data) {
    const response = await fetch(url, { method: "POST", headers: headers(), body: data, credentials: "same-origin" });
    const json = response.status === 204 ? {} : await response.json().catch(() => ({}));
    return { ok: response.ok, json };
  }

  function setEditMode(on) {
    box.classList.toggle("editing", on);
    doneButton.hidden = !on;
  }

  function makeChip(type) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "category";
    input.value = type.id;
    const emoji = document.createElement("span");
    emoji.className = "type-emoji";
    emoji.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.className = "type-name";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "type-remove";
    remove.dataset.remove = "";
    remove.textContent = "−";
    label.append(input, emoji, name, remove);
    fillChip(label, type);
    return label;
  }
  function fillChip(label, type) {
    label.dataset.type = type.id;
    label.dataset.name = type.name;
    label.dataset.emoji = type.emoji;
    label.querySelector(".type-emoji").textContent = type.emoji;
    label.querySelector(".type-name").textContent = type.name;
    label.querySelector("[data-remove]").setAttribute("aria-label", "Remove " + type.name);
  }

  function open(label) {
    editing = label;
    title.textContent = label ? title.dataset.editTitle : title.dataset.addTitle;
    nameInput.value = label ? label.dataset.name : "";
    emojiButton.textContent = label ? label.dataset.emoji : emojiButton.dataset.default;
    grid.hidden = true;
    emojiButton.setAttribute("aria-expanded", "false");
    error.hidden = true;
    dialog.showModal();
    nameInput.focus();
  }
  emojiButton.dataset.default = emojiButton.textContent;

  addButton.addEventListener("click", () => open(null));
  doneButton.addEventListener("click", () => setEditMode(false));
  form.querySelector("[data-cancel]").addEventListener("click", () => dialog.close());
  emojiButton.addEventListener("click", () => {
    grid.hidden = !grid.hidden;
    emojiButton.setAttribute("aria-expanded", String(!grid.hidden));
  });
  grid.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-emoji]");
    if (!choice) return;
    emojiButton.textContent = choice.dataset.emoji;
    grid.hidden = true;
    emojiButton.setAttribute("aria-expanded", "false");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new URLSearchParams({ name: nameInput.value, emoji: emojiButton.textContent.trim() });
    const url = editing ? urlFor(box.dataset.edit, editing.dataset.type) : box.dataset.create;
    const save = form.querySelector("[data-save]");
    save.classList.add("is-loading");
    const { ok, json } = await busy(post(url, data)).catch(() => ({ ok: false, json: {} }));
    save.classList.remove("is-loading");
    if (!ok) {
      error.textContent = json.error || "The type could not be saved.";
      error.hidden = false;
      return;
    }
    if (editing) {
      fillChip(editing, json);
    } else {
      const chip = makeChip(json);
      chips.insertBefore(chip, addButton);
      chip.querySelector("input").checked = true;
    }
    dialog.close();
  });

  // A long press (500 ms) on a type turns on edit mode instead of choosing the type.
  let timer = null;
  chips.addEventListener("pointerdown", (event) => {
    const label = event.target.closest("label[data-type]");
    if (!label || box.classList.contains("editing")) return;
    timer = setTimeout(() => {
      timer = null;
      longPressed = true;
      setEditMode(true);
      if (navigator.vibrate) navigator.vibrate(20);
    }, 500);
  });
  const cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (longPressed) ignoreClicksUntil = Date.now() + 400;
    longPressed = false;
  };
  ["pointerup", "pointerleave", "pointercancel", "pointermove"].forEach((name) =>
    chips.addEventListener(name, (event) => {
      if (name !== "pointermove" || Math.abs(event.movementX) + Math.abs(event.movementY) > 6) cancel();
    }),
  );
  chips.addEventListener("contextmenu", (event) => {
    if (event.target.closest("label[data-type]")) event.preventDefault();
  });

  chips.addEventListener("click", async (event) => {
    const label = event.target.closest("label[data-type]");
    if (!label) return;
    if (Date.now() < ignoreClicksUntil) {
      event.preventDefault();
      return;
    }
    if (!box.classList.contains("editing")) return; // A normal tap chooses the type.
    event.preventDefault();
    if (!event.target.closest("[data-remove]")) return open(label);
    const name = label.dataset.name;
    if (!confirm(`Remove the type “${name}”? This cannot be undone.`)) return;
    label.classList.add("is-removing");
    const { ok, json } = await busy(post(urlFor(box.dataset.delete, label.dataset.type), new URLSearchParams()))
      .catch(() => ({ ok: false, json: {} }));
    label.classList.remove("is-removing");
    if (!ok) return alert(json.error || "The type could not be removed.");
    const wasChecked = label.querySelector("input").checked;
    label.remove();
    if (wasChecked) {
      const first = chips.querySelector("input[name=category]");
      if (first) first.checked = true;
    }
  });
})();

// Writing suggestion: the ✨ button in the description box (shown once there is text) asks the
// server for a better wording and shows it under the field; "Accept" puts it in the field.
// Nothing is sent until the button is tapped.
(function () {
  const wrap = document.querySelector("[data-suggest]");
  if (!wrap || wrap.dataset.ready) return;
  wrap.dataset.ready = "1";
  const field = wrap.querySelector("[name=description]");
  const button = wrap.querySelector("[data-suggest-btn]");
  const box = wrap.querySelector("[data-suggestion]");
  const text = box.querySelector("[data-suggestion-text]");
  const accept = box.querySelector("[data-accept]");
  const headers = () => JSON.parse(document.body.getAttribute("hx-headers") || "{}");
  let asked = null;

  function refresh() {
    const value = field.value.trim();
    button.hidden = value.length < 3 || value === asked;
  }
  async function ask() {
    const value = field.value.trim();
    asked = value;
    button.classList.add("is-loading");
    let suggestion = "";
    try {
      const response = await fetch(wrap.dataset.suggest, {
        method: "POST", headers: headers(), credentials: "same-origin",
        body: new URLSearchParams({ text: value }),
      });
      suggestion = response.ok ? (await response.json()).suggestion : "";
    } catch (error) {
      suggestion = "";
    }
    button.classList.remove("is-loading");
    if (field.value.trim() !== value) return refresh(); // The text changed meanwhile.
    text.textContent = suggestion || box.dataset.fine;
    accept.hidden = !suggestion;
    box.hidden = false;
    refresh();
  }
  box.dataset.fine = box.dataset.fine || "No better wording found.";
  field.addEventListener("input", () => {
    box.hidden = true;
    refresh();
  });
  button.addEventListener("click", ask);
  accept.addEventListener("click", () => {
    field.value = text.textContent;
    asked = field.value.trim();
    box.hidden = true;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.focus();
  });
  refresh();
})();

// Add with AI: a short sentence fills the form with what it states for certain; a list shows
// what is still missing. Nothing is saved until Save is pressed.
(function () {
  const dialog = document.querySelector("[data-ai-dialog]");
  const form = document.getElementById("expense-form");
  if (!dialog || !form || dialog.dataset.ready) return;
  dialog.dataset.ready = "1";
  const ask = dialog.querySelector("[data-ai-ask]");
  const prompt = ask.querySelector("[name=prompt]");
  const count = ask.querySelector("[data-ai-count]");
  const error = ask.querySelector("[data-ai-error]");
  const go = ask.querySelector("[data-ai-go]");
  const result = dialog.querySelector("[data-ai-result]");
  const headers = () => JSON.parse(document.body.getAttribute("hx-headers") || "{}");

  function open() {
    ask.hidden = false;
    result.hidden = true;
    error.hidden = true;
    dialog.showModal();
    prompt.focus();
  }
  function set(name, value) {
    const inputs = [...form.querySelectorAll(`[name="${name}"]`)];
    for (const input of inputs) {
      if (input.type === "radio" || input.type === "checkbox") {
        input.checked = Array.isArray(value) ? value.includes(input.value) : input.value === value;
      } else {
        input.value = value;
      }
    }
  }
  function setDate(iso) {
    const chip = form.querySelector(`input[name=date][value="${iso}"]`);
    if (chip) return (chip.checked = true);
    const other = form.querySelector("input[name=date][value=other]");
    if (other) {
      other.checked = true;
      form.querySelector("[name=date_other]").value = iso;
    } else {
      set("date", iso);
    }
  }
  function fill(fields) {
    // What the sentence does not state stays empty, even where the form had a default.
    set("amount", fields.amount || "");
    if (form.querySelectorAll("input[type=radio][name=currency]").length) set("currency", fields.currency || "");
    set("payer", fields.payer || "");
    set("beneficiaries", fields.beneficiaries || []);
    set("category", fields.category || "");
    set("description", fields.description || "");
    if (fields.date) setDate(fields.date);
    form.dispatchEvent(new Event("input", { bubbles: true })); // Updates the split and preview.
  }

  document.querySelectorAll("[data-ai-open]").forEach((b) => b.addEventListener("click", open));
  dialog.querySelector("[data-ai-cancel]").addEventListener("click", () => dialog.close());
  dialog.querySelector("[data-ai-ok]").addEventListener("click", () => dialog.close());
  prompt.addEventListener("input", () => (count.textContent = `${prompt.value.length} / 300`));
  ask.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    go.classList.add("is-loading");
    let data = {};
    try {
      const work = fetch(dialog.dataset.url, {
        method: "POST", headers: headers(), credentials: "same-origin",
        body: new URLSearchParams({ text: prompt.value }),
      }).then((r) => r.json());
      data = await (window.seBusy ? window.seBusy(work) : work);
    } catch (e) {
      data = { error: "The text could not be read. Try again." };
    }
    go.classList.remove("is-loading");
    if (data.error) {
      error.textContent = data.error;
      error.hidden = false;
      return;
    }
    fill(data.fields || {});
    const missing = data.missing || [];
    const list = result.querySelector("[data-ai-missing]");
    list.replaceChildren(...missing.map((m) => Object.assign(document.createElement("li"), { textContent: m })));
    result.querySelector("[data-ai-result-title]").textContent = missing.length
      ? "Filled in. Still missing:"
      : "All details filled in.";
    ask.hidden = true;
    result.hidden = false;
  });
  if (new URLSearchParams(location.search).get("ai")) open();
})();

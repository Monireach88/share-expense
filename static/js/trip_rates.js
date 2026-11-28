// Exchange rates on the New trip and Trip settings pages: rows that can be added and removed, and
// the suggested currency and market rate (asked from this server, which asks ExchangeRate-API).
// The pages work without this file: the New trip page then has one empty rate row.
// Removed rows leave a gap in the row numbers; the server skips the missing numbers.
(function () {
  const note = document.querySelector("[data-rate-note-template]");

  async function ask(url, params) {
    try {
      const response = await fetch(url + "?" + new URLSearchParams(params), {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }

  // The note under a market rate: "Market rate on 28 Nov 2026 · Rates by ExchangeRate-API".
  function showNote(el, day) {
    if (!el || !note) return;
    el.replaceChildren(note.content.cloneNode(true));
    el.querySelector("[data-day]").textContent = day;
    el.hidden = false;
  }
  function hideNote(el) {
    if (!el) return;
    el.hidden = true;
    el.replaceChildren();
  }

  // Trip settings: choosing a currency in "Add rate" fills an empty rate box with the market rate.
  const single = document.querySelector("form[data-rate-suggest][data-base]");
  if (single && !single.dataset.ready) {
    single.dataset.ready = "1";
    const select = single.querySelector("select[name=currency]");
    const input = single.querySelector("input[name=rate]");
    const noteEl = single.querySelector("[data-rate-note]");
    let filled = ""; // The value this script put in the box; anything else is the user's.
    input.addEventListener("input", () => hideNote(noteEl));
    select.addEventListener("change", async () => {
      if (input.value && input.value !== filled) return;
      input.value = filled = "";
      hideNote(noteEl);
      if (!select.value) return;
      const asked = select.value;
      const answer = await ask(single.dataset.rateSuggest, { base: single.dataset.base, currency: asked });
      if (!answer || !answer.rate || select.value !== asked || input.value) return;
      input.value = filled = answer.rate;
      showNote(noteEl, answer.day);
    });
  }

  // New trip: rate rows, and a row for the chosen country's currency.
  const card = document.querySelector("[data-rates]");
  const form = card && card.closest("form[data-rate-suggest]");
  if (!form || form.dataset.ready) return;
  form.dataset.ready = "1";
  const rows = card.querySelector("[data-rate-rows]");
  const template = card.querySelector("[data-rate-row-template]");
  const total = form.querySelector("[name=rates-TOTAL_FORMS]");
  const addButton = card.querySelector("[data-add-rate]");
  const country = form.querySelector("[name=country]");
  const baseSelect = form.querySelector("[name=base_currency]");
  const url = form.dataset.rateSuggest;
  const dismissed = new Set(); // Suggested currencies the user removed: never added again.
  let asking = 0; // Only the newest country answer counts.

  const base = () => baseSelect.value;
  const allRows = () => [...rows.querySelectorAll("[data-rate-row]")];
  const parts = (row) => ({
    currency: row.querySelector("select"),
    rate: row.querySelector("input[name$=-rate]"),
    note: row.querySelector("[data-rate-note]"),
  });
  const isEmpty = (row) => !parts(row).currency.value && !parts(row).rate.value;
  const rowFor = (code) => allRows().find((row) => parts(row).currency.value === code);

  function addRow() {
    const index = Number(total.value);
    const fragment = template.content.cloneNode(true);
    for (const el of fragment.querySelectorAll("[id], [for], [name]")) {
      for (const attr of ["id", "for", "name"]) {
        if (el.hasAttribute(attr)) el.setAttribute(attr, el.getAttribute(attr).replace("__prefix__", index));
      }
    }
    const row = fragment.querySelector("[data-rate-row]");
    rows.append(fragment);
    total.value = index + 1;
    prepare(row);
    return row;
  }
  function removeRow(row) {
    // The server skips the missing row number, so the other rows keep their numbers.
    if (row.dataset.suggested) dismissed.add(row.dataset.suggested);
    row.remove();
  }
  function prepare(row) {
    const p = parts(row);
    row.querySelector("[data-base-label]").textContent = "1 " + base() + " =";
    row.querySelector("[data-remove-rate]").hidden = false;
    p.rate.addEventListener("input", () => {
      row.dataset.edited = "1";
      delete row.dataset.market;
      hideNote(p.note);
    });
    p.currency.addEventListener("change", () => {
      row.dataset.edited = "1";
      fillRate(row);
    });
  }
  // A row whose rate box is empty (or still holds a market rate) gets the market rate.
  async function fillRate(row, force) {
    const p = parts(row);
    if (p.rate.value && !row.dataset.market && !force) return;
    if (row.dataset.market) p.rate.value = "";
    delete row.dataset.market;
    hideNote(p.note);
    const code = p.currency.value;
    if (!code || code === base()) return;
    const answer = await ask(url, { base: base(), currency: code });
    if (!answer || !answer.rate || p.currency.value !== code || p.rate.value) return;
    p.rate.value = row.dataset.market = answer.rate;
    showNote(p.note, answer.day);
  }

  async function suggest() {
    const ticket = ++asking;
    const code = country.value;
    // An untouched suggestion for the previous country goes away.
    for (const row of allRows()) {
      if (row.dataset.suggested && !row.dataset.edited) row.remove();
    }
    if (!code) return;
    const answer = await ask(url, { base: base(), country: code });
    if (ticket !== asking || !answer || !answer.currency) return;
    if (answer.currency === base() || rowFor(answer.currency) || dismissed.has(answer.currency)) return;
    const row = allRows().find(isEmpty) || addRow();
    const p = parts(row);
    row.dataset.suggested = answer.currency;
    p.currency.value = answer.currency;
    if (answer.rate) {
      p.rate.value = row.dataset.market = answer.rate;
      showNote(p.note, answer.day);
    }
  }
  // The card starts with only "Add currency": the server's empty row is for pages without
  // this script. A row with an error message stays, so the message stays visible.
  for (const row of allRows()) {
    if (isEmpty(row) && !row.querySelector(".field-error")) row.remove();
  }
  allRows().forEach(prepare);
  addButton.hidden = false;
  addButton.addEventListener("click", () => {
    const row = allRows().find(isEmpty) || addRow();
    parts(row).currency.focus();
  });
  rows.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-rate]");
    if (button) removeRow(button.closest("[data-rate-row]"));
  });
  country.addEventListener("change", suggest);
  baseSelect.addEventListener("change", () => {
    for (const row of allRows()) {
      row.querySelector("[data-base-label]").textContent = "1 " + base() + " =";
      // A market rate for the old base is wrong now; a rate the user typed stays.
      if (row.dataset.market) fillRate(row, true);
    }
    // The base currency may now be the country's currency, or no longer be.
    const suggested = allRows().find((row) => row.dataset.suggested && !row.dataset.edited);
    if (!suggested || parts(suggested).currency.value === base()) suggest();
  });
})();

// Trip dates: the start and end date fields open ONE calendar, where the first tap picks the first
// day and the second tap the last day. Without this file the two fields are normal date boxes.
//
// Each visible field becomes a read-only text box ("1 Jun 2026"), and a hidden input with the
// field's name carries the date to the server as YYYY-MM-DD. A read-only text box never opens the
// phone's own date picker or keyboard, on iPhone Safari as on Android Chrome, so the calendar is
// the only picker. The server still checks that the end is on or after the start.
(function () {
  const DAY = 86400000;
  const LANG = document.documentElement.lang || "en";
  const utc = { timeZone: "UTC" };
  const parse = (s) => (/^\d{4}-\d{2}-\d{2}$/.test(s || "") ? new Date(s + "T00:00:00Z") : null);
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (s, n) => iso(new Date(parse(s).getTime() + n * DAY));
  const monthStart = (s) => s.slice(0, 8) + "01";
  const addMonths = (s, n) => {
    const d = parse(s);
    return iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1)));
  };
  const today = () => {
    const now = new Date();
    return iso(new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())));
  };
  const shortParts = new Intl.DateTimeFormat(LANG, { day: "numeric", month: "short", year: "numeric", ...utc });
  // "1 Jun 2026", as the rest of the app writes dates.
  function show(s) {
    const d = parse(s);
    if (!d) return "";
    const part = (type) => shortParts.formatToParts(d).find((p) => p.type === type).value;
    return `${part("day")} ${part("month")} ${part("year")}`;
  }
  const longDay = new Intl.DateTimeFormat(LANG, { weekday: "long", day: "numeric", month: "long", year: "numeric", ...utc });
  const monthName = new Intl.DateTimeFormat(LANG, { month: "long", year: "numeric", ...utc });
  const weekday = new Intl.DateTimeFormat(LANG, { weekday: "narrow", ...utc });
  const weekdayLong = new Intl.DateTimeFormat(LANG, { weekday: "long", ...utc });
  let count = 0;

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setup(box) {
    const fields = ["start_date", "end_date"].map((name) => box.querySelector(`input[name=${name}]`));
    if (fields.some((field) => !field)) return;
    box.dataset.ready = "1";
    const text = box.dataset;
    const id = "date-range-" + ++count;

    const hidden = fields.map((field) => {
      const input = el("input", { type: "hidden", name: field.name });
      input.value = parse(field.value) ? field.value : "";
      field.after(input);
      field.removeAttribute("name");
      field.type = "text";
      field.readOnly = true;
      field.value = show(input.value);
      field.placeholder = text.textEmpty || "";
      field.classList.add("date-pick");
      field.setAttribute("inputmode", "none");
      field.setAttribute("autocomplete", "off");
      field.setAttribute("aria-haspopup", "dialog");
      field.setAttribute("aria-expanded", "false");
      field.setAttribute("aria-controls", id);
      return input;
    });

    // The calendar panel.
    const dialog = el("dialog", { class: "sheet date-range", id, "aria-labelledby": id + "-title" });
    const title = el("h2", { class: "section-title", id: id + "-title" }, text.textTitle);
    const hint = el("p", { class: "dr-hint", "aria-live": "polite" });
    const head = el("div", { class: "dr-head" });
    const prev = el("button", { type: "button", "aria-label": text.textPrev }, "‹");
    const next = el("button", { type: "button", "aria-label": text.textNext }, "›");
    const month = el("h3", { class: "dr-month", id: id + "-month", "aria-live": "polite" });
    head.append(prev, month, next);
    const grid = el("table", { class: "dr-grid", role: "grid", "aria-labelledby": id + "-month" });
    const headRow = el("tr");
    for (let i = 0; i < 7; i++) {
      const day = new Date(Date.UTC(2026, 5, 1 + i)); // 1 June 2026 is a Monday.
      headRow.append(el("th", { scope: "col", abbr: weekdayLong.format(day) }, weekday.format(day)));
    }
    const thead = el("thead");
    thead.append(headRow);
    const body = el("tbody");
    grid.append(thead, body);
    const actions = el("div", { class: "dialog-actions" });
    const clear = el("button", { type: "button", class: "btn btn-secondary" }, text.textClear);
    const done = el("button", { type: "button", class: "btn" }, text.textDone);
    actions.append(clear, done);
    dialog.append(title, hint, head, grid, actions);
    box.after(dialog);

    // start, end: YYYY-MM-DD or "". phase: what the next tap picks ("start", "end"), or "again"
    // once both are picked (the next tap starts a new range).
    let start = hidden[0].value;
    let end = hidden[1].value;
    let phase = "start";
    let view = monthStart(start || today());
    let focus = start || today();

    function write() {
      hidden[0].value = start;
      hidden[1].value = end;
      fields[0].value = show(start);
      fields[1].value = show(end);
      for (const input of hidden) input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function render() {
      month.textContent = monthName.format(parse(view));
      if (phase === "end") hint.textContent = text.textLast;
      else if (start && end) hint.textContent = `${show(start)} – ${show(end)}`;
      else hint.textContent = text.textFirst;
      body.replaceChildren();
      const first = parse(view);
      const lead = (first.getUTCDay() + 6) % 7; // Monday first.
      let day = addDays(view, -lead);
      const now = today();
      for (let week = 0; week < 6; week++) {
        if (week && day.slice(0, 7) !== view.slice(0, 7)) break;
        const row = el("tr");
        for (let i = 0; i < 7; i++, day = addDays(day, 1)) {
          const cell = el("td", { role: "gridcell" });
          if (day.slice(0, 7) === view.slice(0, 7)) {
            const chosen = day === start || day === end;
            const button = el("button", {
              type: "button",
              "data-day": day,
              tabindex: day === focus ? "0" : "-1",
              "aria-label": longDay.format(parse(day)),
            }, String(Number(day.slice(8))));
            if (day === now) button.setAttribute("aria-current", "date");
            cell.setAttribute("aria-selected", String(chosen || (start && end && start < day && day < end)));
            if (day === start) cell.classList.add("is-start");
            if (day === end) cell.classList.add("is-end");
            if (start && end && start < day && day < end) cell.classList.add("in-range");
            if (start && end && start !== end) cell.classList.add("has-range");
            cell.append(button);
          }
          row.append(cell);
        }
        body.append(row);
      }
      // The focused day must be in this month, so Tab reaches the grid.
      if (!body.querySelector('[tabindex="0"]')) {
        const firstDay = body.querySelector("[data-day]");
        firstDay.tabIndex = 0;
        focus = firstDay.dataset.day;
      }
    }

    function pick(day) {
      if (phase === "end" && day >= start) {
        end = day;
        phase = "again";
      } else if (phase === "start" && start && end && day <= end) {
        start = day; // A new first day inside the old range keeps the last day.
        phase = "end";
      } else {
        // The first tap, a new range, or a day before the first day: start again from it.
        start = day;
        end = "";
        phase = "end";
      }
      focus = day;
      write();
      render();
      body.querySelector(`[data-day="${day}"]`).focus();
    }

    function moveFocus(day) {
      focus = day;
      if (monthStart(day) !== view) {
        view = monthStart(day);
        render();
      } else {
        for (const b of body.querySelectorAll("[data-day]")) b.tabIndex = b.dataset.day === day ? 0 : -1;
      }
      body.querySelector(`[data-day="${day}"]`).focus();
    }

    function open(which) {
      phase = which === 1 && start ? "end" : "start";
      focus = (which === 1 ? end : start) || start || today();
      view = monthStart(focus);
      render();
      fields.forEach((f) => f.setAttribute("aria-expanded", "true"));
      dialog.showModal();
      body.querySelector(`[data-day="${focus}"]`).focus();
    }
    function close() {
      if (dialog.open) dialog.close();
    }

    fields.forEach((field, which) => {
      field.addEventListener("click", () => open(which));
      field.addEventListener("keydown", (event) => {
        if (["Enter", " ", "ArrowDown"].includes(event.key)) {
          event.preventDefault();
          open(which);
        }
      });
    });
    dialog.addEventListener("close", () => fields.forEach((f) => f.setAttribute("aria-expanded", "false")));
    // A tap on the dark area around the panel closes it.
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const r = dialog.getBoundingClientRect();
      const inside = event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom;
      if (!inside) close();
    });
    prev.addEventListener("click", () => {
      view = addMonths(view, -1);
      render();
    });
    next.addEventListener("click", () => {
      view = addMonths(view, 1);
      render();
    });
    body.addEventListener("click", (event) => {
      const button = event.target.closest("[data-day]");
      if (button) pick(button.dataset.day);
    });
    body.addEventListener("keydown", (event) => {
      const moves = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      const day = event.target.dataset && event.target.dataset.day;
      if (!day) return;
      let target = null;
      if (event.key in moves) target = addDays(day, moves[event.key]);
      else if (event.key === "PageUp" || event.key === "PageDown") {
        const shifted = addMonths(day, event.key === "PageUp" ? -1 : 1);
        const last = addDays(addMonths(shifted, 1), -1);
        target = shifted.slice(0, 8) + day.slice(8) > last ? last : shifted.slice(0, 8) + day.slice(8);
      } else if (event.key === "Home") target = addDays(day, -((parse(day).getUTCDay() + 6) % 7));
      else if (event.key === "End") target = addDays(day, 6 - ((parse(day).getUTCDay() + 6) % 7));
      if (!target) return;
      event.preventDefault();
      moveFocus(target);
    });
    clear.addEventListener("click", () => {
      start = end = "";
      phase = "start";
      write();
      render();
      body.querySelector('[tabindex="0"]').focus();
    });
    done.addEventListener("click", close);
  }

  document.querySelectorAll("[data-date-range]:not([data-ready])").forEach(setup);
})();

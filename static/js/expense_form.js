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
      split.textContent = "Pick at least one person.";
    } else {
      const each = value ? " · " + fmt(Math.round((value / n) * 100) / 100, cur) + " each" : "";
      split.textContent = "Split between " + n + (n === 1 ? " person" : " people") + each;
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
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
})();

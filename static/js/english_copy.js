// English copies of text (docs/spec_languages.md section 3). A box with data-english holds a text
// field and a row [data-english-row] with the "<name>_en" field. The row shows as soon as the text
// has Khmer or Chinese letters, and the server is asked for an English suggestion, unless the person
// has already edited the English box. The pages work without this file: the server makes the copy
// when the box is empty, and shows the row with an error when it cannot.
(function () {
  // Keep this pattern in step with NEEDS_COPY in apps/trips/english.py.
  const NEEDS_COPY = /[ក-៿᧠-᧿㐀-䶿一-鿿]/;
  const headers = () => JSON.parse(document.body.getAttribute("hx-headers") || "{}");

  function setup(box) {
    const row = box.querySelector("[data-english-row]");
    const english = row && row.querySelector("input[name$='_en'], textarea[name$='_en']");
    if (!english) return;
    const source = box.querySelector(`[name="${english.name.replace(/_en$/, "")}"]`);
    if (!source) return;
    box.dataset.englishReady = "1";
    let edited = false; // True once the person typed in the English box.
    let asked = source.value.trim();
    let turn = 0;
    let timer = null;

    english.addEventListener("input", () => (edited = true));

    async function refresh() {
      const text = source.value.trim();
      if (!NEEDS_COPY.test(text)) {
        row.hidden = true;
        if (!edited) english.value = "";
        asked = text;
        return;
      }
      row.hidden = false;
      if (edited || text === asked) return;
      asked = text;
      const mine = ++turn;
      english.setAttribute("aria-busy", "true");
      let suggestion = "";
      try {
        const work = fetch(box.dataset.english, {
          method: "POST", headers: headers(), credentials: "same-origin",
          body: new URLSearchParams({ text }),
        }).then((r) => (r.ok ? r.json() : { english: "" }));
        suggestion = (await (window.seBusy ? window.seBusy(work) : work)).english || "";
      } catch (error) {
        suggestion = "";
      }
      english.removeAttribute("aria-busy");
      if (mine !== turn || edited) return;
      if (suggestion) english.value = suggestion;
    }

    box.addEventListener("input", (event) => {
      if (event.target !== source) return;
      clearTimeout(timer);
      timer = setTimeout(refresh, 700);
    });
    // The type dialog and other scripts read this to leave a box alone after a manual edit.
    box._englishRefresh = refresh;
  }

  function init() {
    document.querySelectorAll("[data-english]:not([data-english-ready])").forEach(setup);
  }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})();

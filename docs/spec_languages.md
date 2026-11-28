# Spec: Khmer, Chinese and English

Status: approved by the owner on 2026-11-28; built on branch `feat/languages`.

## 1. Decisions

| # | Decision |
|---|---|
| L1 | Languages: Khmer (`km`, default), Simplified Chinese (`zh-hans`), English (`en`). More languages later must need only a new `.po` file and one line in `LANGUAGES`. |
| L2 | Every visitor sees Khmer until they choose another language. The browser's `Accept-Language` header is ignored. A choice is kept in the `django_language` cookie, and for a signed-in person also in `User.language`, which wins after sign-in on any device. |
| L3 | Digits are Western (1,250.00) in every language; dates use the language's month names. |
| L4 | Interface text uses Django's gettext: whole sentences, never words glued together, with `pgettext` context wherever one English word has two meanings (for example "Settle" the button vs "Settled" the state). Plurals use `ngettext`/`blocktranslate count`. |
| L5 | Text a person writes gets a stored English copy when it contains Khmer or Chinese letters (§3). People's names and usernames are never translated. |
| L6 | The machine translator for §3 is DeepSeek, which the app already calls for AI fill; it shares the existing daily limit. |
| L7 | Emails are written in the sender's active language. |

## 2. Interface

1. A language button (globe icon plus the current language's short name) sits in the header on every page, signed in or not, including the sign-in page. It opens a small menu: ខ្មែរ, 中文, English, each written in its own language. Choosing posts to a view that sets the cookie, saves `User.language` when signed in, and returns to the same page.
2. Khmer text uses a self-hosted Noto Sans Khmer (`static/fonts/`, SIL Open Font License file included) loaded with `unicode-range`, so other languages never download it. Chinese uses system fonts. Khmer needs a taller line height; check that no button or label clips Khmer marks above or below the line.
3. JavaScript text: month and weekday names come from `Intl.DateTimeFormat(document.documentElement.lang)`; any other text comes from `data-` attributes rendered by the template. No inline scripts (the Content-Security-Policy allows only `script-src 'self'`).
4. `<html lang>` is the active language.
5. Default categories and any other seeded text are translated with gettext, not stored per language.

## 3. English copies of user text

Fields: `Trip.name`, `Expense.description`, `Category.name` (custom ones), `Dispute.reason`, `Dispute.close_reason`, `DisputeMessage.text`. Each gets a sibling `<field>_en` (same type, blank allowed).

1. Detection: the text needs a copy when it contains a Khmer letter (U+1780–U+17FF, U+19E0–U+19FF) or a Han character (CJK Unified Ideographs and Extension A). Otherwise `<field>_en` stays empty and the original is the English.
2. Form: an "English" field appears under the original as soon as the original contains such letters. The browser asks a suggestion endpoint (same pattern as the market-rate suggestion) and fills it, unless the person already edited it. The person can correct it.
3. Server, on save: if a copy is needed and the English field is empty, the server asks DeepSeek. If DeepSeek fails or the daily limit is reached, the form returns with the error "Write the English version." and the field visible. When the original changes and the person did not change the English, the server makes a new copy.
4. Display: in English, show `<field>_en` when it is filled, else the original. In Khmer and Chinese, show the original.
5. History search text and exports (CSV, Excel) include the English copy.
6. The DeepSeek prompt asks for a short, natural English translation of a travel-expense text, keeping names, numbers and currency codes unchanged, and returning only the translation.

## 4. Translation files and review

1. `locale/km/LC_MESSAGES/django.po` and `locale/zh_Hans/LC_MESSAGES/django.po` are in git. Each entry keeps its `#:` file references, and a `#.` translator note where the meaning is not obvious from the sentence.
2. `.mo` files are compiled, never committed: in the Docker build, in CI, and by the test setup.
3. `docs/translation_glossary.md`: every domain term (owes, is owed, settle up, traveler, Owner, Editor, Member, Viewer, dispute, base currency, …) with its one chosen translation per language. Translators and checkers follow it.
4. The owner reviews in a plain shared document with one table per page (English, Khmer, Chinese, checker note) and edits the translations there; Claude writes the edits back into the `.po` files.
5. Check order before the owner sees it: Claude drafts both languages; GPT-6 Astra checks every Khmer entry; DeepSeek checks every Chinese entry; each check returns a verdict per entry (keep / change with the new text and the reason). Accepted changes go into the `.po` files; every "change" is listed in the check-note column so the owner sees what moved.

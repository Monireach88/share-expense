# Spec: Trip roles, History, disputes and accounts

Status: §1–§6.1 are built (PRs #29–#33, in `develop`). §6.2–§6.6 (personal invites, Google-only new accounts, closing an account, invite email) were agreed with the owner on 2026-11-27, reviewed by two independent reviewers, and are built in PR 5.

This spec is for the people who build the feature. It says what each person in a trip may do, what the History page records, how a dispute works, and how accounts join a trip. Every rule ends in acceptance criteria (Gherkin scenarios), so a reviewer can check the build against this file.

Example people used below (fake names): Ann owns the trip; Ben is an Editor; Cara and Dan are Members; Eve is an account with no traveler (a parent at home).

## 1. Words

- **Traveler:** a person who shares costs (`Participant`). Needs no account.
- **Account:** a user who can sign in (`User`). An account opens a trip through a **membership** (`TripMember`).
- **Linked traveler:** the one traveler of a trip that an account is linked to (`Participant.user`). An account has at most one linked traveler per trip; the database enforces it.
- **Own expense:** an expense whose payer is the account's linked traveler. Who created the record does not matter.
- **Open dispute:** a dispute that is neither resolved nor closed.
- **Expense page:** the page an expense card opens. It shows the edit form to people who may edit the expense, and the same values read-only to everyone else, and to everyone on a settled trip.

## 2. Roles

A membership has one of three roles. "Viewer" is not a role: it is the label shown for a Member with no linked traveler.

| Action | Owner | Editor | Member | Member with no traveler ("Viewer") |
|---|---|---|---|---|
| View expenses (expense page read-only), Balances, Stats, History, exports | yes | yes | yes | yes |
| Add an expense with any payer | yes | yes | no | no |
| Add an expense paid by their own traveler (any "For") | yes | yes | yes | no |
| Edit, delete or restore any expense | yes | yes | no | no |
| Edit, delete or restore their own expense | yes | yes | yes | no |
| Add a type; choose a type on an expense they may edit | yes | yes | yes | no |
| Rename or remove a type; reorder expenses | yes | yes | no | no |
| Add with AI, ✨ description suggestion | yes | yes | yes | no |
| Open a dispute; write in a dispute | see §5 | see §5 | see §5 | see §5 |
| Settle or reopen the trip | yes | yes | no | no |
| Travelers, accounts, roles, invite link, rates, trip settings, delete trip | yes | no | no | no |
| Transfer ownership | yes | no | no | no |
| Close an open dispute (§5.3) | yes | no | no | no |

Rules:

- A new membership is a **Member**. Only the Owner changes roles, on the Travelers page (Accounts section).
- There is exactly one Owner per trip; the database enforces it. The Owner cannot remove themselves or change their own role; they transfer ownership first.
- **Transfer ownership:** the Owner picks another approved account on the trip and confirms. The new owner becomes Owner; the old owner becomes Editor. Recorded in History.
- The Django admin refuses to delete an account that owns a trip, so a trip never loses its Owner.
- A Member's expense form shows the payer fixed to their own traveler. The server checks it too: a Member's request with another payer is refused (403), never silently changed.
- A Member who edits their own expense cannot change its payer to someone else.
- **Add with AI** for a Member: the payer is always their traveler. If the sentence names another payer, "who paid" stays empty and appears in the missing list.
- **Removing an account** from the trip: it loses access at once, its traveler is unlinked (History: "unlinked"), and it cannot rejoin by invite link until the Owner adds it again (§6.3). Its History entries and dispute messages stay, with its name.
- If the Owner unlinks a Member's traveler, that Member becomes a "Viewer" at once. Editors and the Owner keep their rights without a traveler.

### 2.1 Settled trip

Settling needs: no open dispute, and Balances without an error. A settled trip is read-only for every change that touches the numbers or the disputes, for everyone, the Owner included:

- **Locked:** add, edit, delete or restore an expense; types; reorder; travelers and who covers whom; rates; base currency; opening a dispute or writing in one.
- **Still allowed** (they change no number): trip name, roles, ownership transfer, adding or removing accounts, linking a traveler to an account, the invite link and joining by it.

Settling and reopening each notify every account on the trip (§4), so a reopen-change-settle round cannot pass unseen. Settling, and every change to expenses, lock the trip row in the database while they run, so an edit sent at the same moment as Settle cannot slip in.

### Acceptance criteria

```gherkin
Scenario: A Member adds an expense paid by herself for others
  Given Cara is a Member linked to traveler Cara
  When Cara adds "Drinks 10 USD, paid by Cara, for everyone"
  Then the expense is saved
  And History shows "Cara added Drinks"

Scenario: A Member cannot record another traveler as payer
  Given Cara is a Member
  When Cara sends an expense with payer Dan
  Then the server answers 403 and nothing is saved

Scenario: A Member sees someone else's expense read-only
  Given Ben recorded "Taxi, paid by Dan"
  When Cara opens that expense
  Then she sees its values read-only, with no Save or Delete

Scenario: A Member edits an expense someone else recorded with her as payer
  Given Ben recorded "Lunch, paid by Cara"
  When Cara changes the amount
  Then the change is saved, because Cara is the payer

Scenario: A Viewer cannot add expenses
  Given Eve is a Member with no linked traveler
  Then the Expenses page shows no add button
  And a request to the add-expense address answers 403

Scenario: An Editor settles the trip
  Given Ben is an Editor and no dispute is open
  When Ben taps Settle
  Then the trip is settled and History shows "Ben settled the trip"
  And every account on the trip gets a notification

Scenario: A Member cannot settle
  Given Cara is a Member
  Then the Balances page shows no Settle button
  And a request to the settle address answers 403

Scenario: Ownership transfer
  Given Ann is the Owner and Ben is an Editor
  When Ann transfers ownership to Ben and confirms
  Then Ben is the Owner and Ann is an Editor
  And History shows "Ann made Ben the owner"

Scenario: Removing an account unlinks its traveler
  Given Cara's account is linked to traveler Cara
  When Ann removes Cara's account
  Then Cara's account gets 404 on the trip
  And traveler Cara has no account
  And History shows "Ann removed Cara's account" and "unlinked"

Scenario: One account cannot be linked to two travelers
  Given Cara's account is linked to traveler Cara
  When Ann tries to link Cara's account to traveler Dan
  Then the form says the account is already linked to Cara

Scenario: A settled trip still allows account changes
  Given the trip is settled
  When Ann changes Cara's role to Editor
  Then the change is saved
  But a request to add an expense answers with "This trip is settled"
```

## 3. History

Every change to a trip writes one History entry, in the same database transaction as the change. Entries are never edited or deleted by anyone, including the Owner; the Django admin shows them read-only. Deleting the whole trip (Owner only) deletes its History with it.

An entry stores: when, which account did it (its name is kept even if the account is later deleted), the action, the object (expense, traveler, account, rate, type, trip, dispute), and the values before and after for every field that changed. Values are stored as names and text, plus IDs, so an entry still reads correctly after a traveler is renamed or removed. An expense's values are: date, payer, "For" list, type, description, amount and currency.

Actions recorded:

| Object | Actions |
|---|---|
| Expense | added, changed (with old → new per field), deleted, restored |
| Traveler | added, renamed, covered-by changed, linked or unlinked to an account, removed |
| Account | joined (by link or by the Owner), role changed, removed, became owner |
| Rate | added, changed, removed |
| Type | added, renamed, removed |
| Trip | settled, reopened, renamed, invite link turned on, off or renewed |
| Dispute | opened, message written, resolved, closed by the Owner |

Reordering expenses is **not** recorded: it changes no number and would fill History with noise.

### Page

- **Where:** a History icon (a clock) in the trip header, next to the bell (§4), on every trip page, for everyone. The Owner's settings icon stays.
- Newest first, grouped by day, 10 days per page with "Show older" (same pattern as Expenses).
- One line per entry, for example: "21:14 · Cara changed Dinner: amount 40 USD → 4 USD".
- Tapping an expense entry opens the expense page (read-only when needed, §1). A deleted expense shows its last values and, for people allowed to restore it, a Restore button.
- **Search:** one box above the list. It matches, ignoring letter case, against: the account name, the action word, the expense description, its type, its payer and "For" names, and the old and new values. Results update while typing, like the Expenses search. Each entry stores its searchable text in one column, so the search runs in the database.

### Restore

- Whoever may edit an expense may restore it: Owner and Editors any expense, a Member their own.
- A restored expense comes back with exactly the last values that History shows. Restore is refused, with a message that names what is missing, when the payer or a "For" traveler was removed, the type was removed, or the currency has no rate any more ("Add the VND rate first"). The person fixes that, then restores.
- An expense whose payer was removed is erased with that traveler (as today). Its History entries stay readable but show "This expense can no longer be restored".
- Removing a traveler, a type or a rate is refused while a dispute exists on an expense that uses it.
- Restore is refused on a settled trip. Tapping Restore twice restores once.
- There is no "undo a change" button: a wrong change is fixed by a normal edit, and History shows the old values to copy from.

### Acceptance criteria

```gherkin
Scenario: Every expense change is recorded with old and new values
  Given an expense "Dinner 40 USD"
  When Ben changes the amount to 4
  Then History shows "Ben changed Dinner: amount 40 USD → 4 USD"

Scenario: History cannot be changed
  Then no page, form, or admin action edits or deletes a History entry

Scenario: A Member restores her own deleted expense
  Given Cara deleted her own expense "Taxi"
  When Cara opens the History entry and taps Restore
  Then "Taxi" is back on the Expenses page with its last values
  And History shows "Cara restored Taxi"

Scenario: A Member cannot restore someone else's expense
  Given Ben deleted "Hotel, paid by Dan"
  Then Cara sees the entry without a Restore button
  And a request to restore it answers 403

Scenario: Restore is refused when a rate is missing
  Given a deleted expense in VND
  And the VND rate was removed afterwards
  When Ben taps Restore
  Then nothing is restored and the message says to add the VND rate first

Scenario: Search finds entries by type
  Given History has entries for a "Transport" expense and a "Food" expense
  When I type "transport" in the History search
  Then only the Transport entries remain

Scenario: Entries survive a renamed traveler
  Given "Dinner, paid by Dan" was added
  When the Owner renames Dan to "Daniel"
  Then the old entry still reads "paid by Dan"
  And a new entry reads "Ann renamed traveler Dan → Daniel"

Scenario: History opens an expense on a settled trip
  Given the trip is settled
  When Cara taps an expense entry in History
  Then the expense page opens read-only
```

## 4. Notifications

The app sends no email or push message. A notification is an item in the account's in-app list:

- A bell icon in the trip header and on the trips list, for every account, with a red count of unread items. Tapping it opens the list; opening the list marks the items as read.
- Each item names the trip and links to what it is about (an expense page with a dispute, or the History entry of a settle or reopen).
- What creates a notification: the dispute events in §5.2; settling or reopening a trip (every account on the trip except the one who did it); being added to a trip by the Owner (§6.2, the added account); an invite being accepted (§6.3, the Owner); an accepted invite that could not link its traveler (§6.3, the Owner). Nothing else.
- An account removed from a trip gets no new notifications from it, and its old items from that trip are hidden.

## 5. Disputes

A dispute is a complaint about one expense, written by a traveler who disagrees with it.

### 5.1 Who opens one

An account may open a dispute on an expense when its linked traveler is, or **was at any time**, the payer or in "For" of that expense (History shows the earlier versions). So a traveler whose payment was moved to someone else can still dispute it. A dispute can be opened on a deleted expense, from its History entry. At most one open dispute per expense per account. Not on a settled trip.

### 5.2 Who is notified and who fixes

- **Opened:** the account that created the expense and the payer's account (if different), never the opener.
- **Message written:** everyone in the dispute — the opener, the creator, the payer's account, and the Owner or any Editor who has written in it — except the writer.
- **Resolved or closed:** the same people, except the one who did it.
- An account that is no longer on the trip is skipped. If nobody but the opener would be notified, the Owner is notified instead, so every dispute reaches someone.
- Anyone who may edit the expense may fix it (§2). The fix is a normal edit (recorded in History).
- The opener, the creator, the payer's account, the Owner and the Editors may write messages. Editors may fix any expense, so they can write "Fixed". The opener keeps these rights even after becoming a Viewer.

### 5.3 States

```
open ──(opener taps Mark as resolved)───────▶ resolved
open ──(Owner closes, with a written reason)─▶ closed
```

- Only the opener can tap **Mark as resolved**.
- The Owner can **close** any open dispute, with a required written reason. Reason: one absent person must not block settling forever, and only the Owner can always act. When the Owner closes a dispute about an expense the Owner paid, every account on the trip is notified, so the decision is in the open.
- If the opener's account is removed, their open disputes stay open until the Owner closes them.
- If the disputed expense is deleted, the dispute stays open until the opener resolves it (the deletion may be the fix).
- Resolved and closed disputes accept no new messages and cannot be reopened; a new dispute can be opened instead.

### 5.4 Screen

There is no separate dispute page. The dispute is a section at the bottom of the expense page:

- A "Dispute this expense" button for people allowed to open one (§5.1). It opens a box for the reason.
- When disputes exist: each dispute shows its state, its messages (name, time, text), a box to write, and the **Mark as resolved** (opener) or **Close dispute** (Owner, asks for the reason) button.
- Saving a fix on the expense page returns to the same expense page, so the fixer sees the dispute and can write "Fixed".
- An expense with an open dispute shows a small "Disputed" mark on its card in Expenses.

### 5.5 Settling

The trip cannot be settled while any dispute is open. On Balances, the Settle button is replaced by "1 open dispute blocks settling" (or "N open disputes block settling"), which opens the Expenses list filtered to disputed expenses.

### Acceptance criteria

```gherkin
Scenario: The full dispute flow
  Given Dan recorded "Dinner 60 USD, paid by Dan, for Dan, Cara and Ben"
  When Cara opens a dispute "I did not eat dinner"
  Then Dan gets a notification
  When Dan removes Cara from "For", saves, and writes "Sorry, fixed"
  Then Cara gets a notification
  When Cara taps Mark as resolved
  Then the dispute is resolved and Dan gets a notification
  And History shows opened, the change, the message and resolved

Scenario: Only the opener can resolve
  Given Cara opened a dispute
  Then Dan sees no Mark as resolved button
  And a request to resolve it from Dan answers 403

Scenario: A traveler disputes a payment moved away from him
  Given "Hotel, paid by Dan"
  When Ben changes the payer to Ben
  Then Dan can still open a dispute on "Hotel"

Scenario: An open dispute blocks settling
  Given one dispute is open
  Then Balances shows "1 open dispute blocks settling" instead of Settle
  And a request to settle answers 400 with that reason

Scenario: The Owner closes a stuck dispute
  Given Cara's dispute on Dan's expense is open
  When Ann closes it with the reason "Photo shows Cara at dinner"
  Then the dispute is closed and Cara gets a notification
  And History shows the reason

Scenario: The Owner closes a dispute about her own expense in the open
  Given Cara disputes "Hotel, paid by Ann"
  When Ann closes it with a reason
  Then every account on the trip gets a notification

Scenario: A Viewer cannot open a dispute
  Given Eve has no linked traveler
  Then Eve sees no "Dispute this expense" button on any expense
```

## 6. Accounts

### 6.1 Usernames

- Allowed: a–z, 0–9 and `_`; 3 to 30 characters; stored in lowercase. Sign-in accepts any letter case. Error for bad characters or length: "Use only the characters listed above." (the field help lists them); a clash: "This username is taken."
- Unique across the whole app, enforced by the database (unique index on the lowercase name).
- Accounts created by Google sign-in get a username built from the email name that follows these rules (plus a number when taken).
- Before the migration: list production usernames that break the rules or clash in lowercase; the owner decides each rename. The migration must not fail on existing data.

### 6.2 Inviting a person (Owner)

Decided by the owner on 2026-11-27; replaces the shared invite link and the public "Request an account" page.

On the Travelers page the Owner taps **Invite** and fills one form:

- **Traveler:** required. An existing traveler with no account and no pending invite, or "A new traveler" with a name typed by the Owner, or "No traveler (view only)".
- **Username or email:** one field.
  - **A username of an approved account**, or **an email address that an approved account signs in with through Google:** the account joins the trip at once as a Member, linked to the chosen traveler. History: "Ann added Cara's account". The account sees the trip on its trips list and gets a notification (§4).
  - **Any other email address:** the app creates a **personal invite**. A personal invite belongs to one email address and one trip and one traveler choice, works once, and expires 7 days after it was made. Before creating it, the form shows the address back: "Invite dan@example.com?" with a second line "As Dan" (or "As Viewer"), and Confirm. After creating it, the page shows the link with a **Copy link** button (browsers allow copying only right after a tap, so there is no automatic copy) and sends the invite email (§6.6). History: "Ann invited c***@example.com as Cara" (the address partly hidden, see below).
  - Any other text (not an existing username and not an email address): "No account has this username. To invite someone new, type their email address."
- An address that already has a pending invite to this trip: the form offers "Send again" instead of a second invite (the database allows one pending invite per trip and address, letter case ignored).
- An address or username of an account already on the trip: "This person is already on the trip."
- Adding an existing account at once also shows a confirmation first: "Add Gina (gina) to this trip now?" with a second line "As Gina" (or "As Viewer").
- On a settled trip, "A new traveler" is not offered (travelers are locked); an existing traveler or view only is allowed.
- **Tokens:** the link holds a long random token (32 random bytes, URL-safe). Only its hash is stored. **Copy link** and **Send again** therefore make a new token, which ends the old link, and restart the 7 days. Send again also works on an expired invite.
- **Pending invites** are listed in the Accounts section for the Owner: address, traveler ("As Dan" or "As Viewer"), "expires on 4 Dec 2026 at 19:27" (or "Expired"), with **Copy link**, **Send again** and **Cancel**. History records invited, sent again, cancelled, accepted, expired (expiry is recorded when someone opens an expired link, not by a timer). History is visible to every member, so it shows the address partly hidden ("d***@example.com"); the Owner's pending list shows it in full.
- Pending invites stay with the trip when ownership is transferred; the new Owner manages them. Deleting a trip deletes its invites. An Owner who closes their account (§6.5) cancels their trips' pending invites.

### 6.3 Accepting a personal invite

- The invite link opens a page with the trip name, who invited them, the address the invite is for, and one button: **Continue with Google**. It never shows the trip's expenses or travelers before acceptance.
- Google signs the person in. The invite is accepted only when the Google account's verified email equals the invited address (letter case ignored). Then:
  - no account uses this Google account yet: a new **approved** account is created (username from the email name, §6.1), it joins the trip as a Member linked to the invited traveler, and lands on the trip;
  - an account already uses this Google account: that account joins the trip the same way.
- **Wrong Google account** (another address): nothing is created or joined. The page says "This invite is for c***@example.com, but you used another Google account. Sign out of Google, then open the invite link again and choose the invited address." The page shows the invited address partly hidden.
- **Used, expired or cancelled invite:** "This invite no longer works" with "Ask the Owner of the trip for a new one." An account already on the trip is simply taken to the trip.
- **The invited traveler got an account, or was removed, in the meantime:** the account joins as "No traveler (view only)" and the Owner is notified to link the right traveler.
- **Signed in already:** if the signed-in account uses the invited Google address, the invite is accepted at once. If it is another account, the page says "You are logged in as Cara. Log out first, then open this link again."
- **A closed account** (§6.5) cannot accept an invite: "This account is closed. Ask the admin to restore it."
- Addresses are compared exactly, ignoring letter case only (no Gmail dot or plus rules); Google returns the address the person signs in with.
- An accepted invite notifies the Owner: "Dan accepted your invite" (the list shows the trip name under each item).
- **A removed account** (the Owner removed it from this trip) can be invited again; an invite is the Owner's explicit decision.

### 6.4 Signing in and creating accounts

- **New accounts are created only by accepting a personal invite with Google**, or by the admin in the Django admin. The public "Request an account" page and link are removed; its address shows the sign-in page.
- **Google sign-in with no matching account and no invite** is refused; nothing is created. Message: "No account uses this Google account. If you have a username and password, sign in with them and link Google from the account menu. To join a trip, ask its Owner for an invite."
- Existing username-and-password accounts keep working. They can link Google from the account menu (§6.5).
- **A Google sign-in is matched only by the Google account itself** (its stable Google ID, stored when Google is linked), never by an email address typed into an account. Settings: `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and `..._AUTO_CONNECT` are turned off. Reason: with them on, anyone whose Google address equals an account's stored email takes over that account and its password is disabled. An account that signed in with Google before this change by email match only must link Google once from the menu (production: no account has done so; checked 2026-11-27).
- New accounts from Google are created only inside the invite flow: allauth's sign-up is open only while the session holds a live invite whose address equals Google's verified address.
- The old shared invite link is removed: its fields are cleared and dropped by a migration, and every old `/join/…` address shows "This invite no longer works". The old `/accounts/signup/` address goes to the sign-in page. Accounts already waiting for the admin's approval stay; the admin can still approve them.
- A Member who was added by mistake can **leave the trip** from the Travelers page ("Leave this trip", with a confirmation); an Owner cannot leave (transfer first). History: "Gina left the trip". Their traveler is unlinked, like a removal.
- Google accounts with any address are accepted (Gmail or a work or school address); the proof is Google's verified email, not the domain.
- **Forgotten password:** the admin sets a new one in the Django admin. People who sign in with Google have no password to forget.

### 6.5 Account menu

- The menu row "Google sign-in" becomes **"Google account"**, with a second line: "Linked: you@gmail.com" or "Not linked". It opens the page to link or unlink Google (unlinking is refused when the account has no password, as today).
- A new row **"Close account"** opens a page:
  - Text: "Your account will be closed. You will be logged out and cannot log in until the admin restores the account. Your name stays in the records of your trips (expenses, balances and History), because they are shared money records."
  - The person types their username to confirm ("Type “gina” to confirm."), then taps "Close my account".
  - An Owner of a trip with other accounts is refused, and the page shows only this text (every such trip named) instead of the form: "You are the Owner of Phnom Penh. Make someone else the Owner first." An Owner who is the only account of a trip may close their account; the trip stays (the admin can restore it).
  - Closing makes the account inactive and records the time in a new `closed_at` field (this is what tells a closed account apart from one waiting for approval); it ends all its sessions; it keeps its memberships and traveler links unchanged so the admin can restore it fully. History of each of its trips: "Cara closed their account".
  - A closed account that tries to sign in (password or Google) sees "This account is closed. Ask the admin to restore it." It never sees the "waiting for approval" page, and the attempt does not count as a wrong password.
  - In the Django admin, the existing "approve" action skips closed accounts; a separate "restore closed account" action clears `closed_at` and makes the account active. The user list shows a "closed" column.
  - Other members still see the closed account in Accounts, labelled "Closed".

### 6.6 Email

- The app sends one kind of email: the personal invite. Subject: "Ann invited you to Phnom Penh on Share Expense". Body: who invited them, the trip name, the invite link, "Use the Google account of dan@example.com", "This link works once and expires on 4 Dec 2026 at 19:27 (Phnom Penh time)" (the city is the app's time zone), and "If you do not know Ann, ignore this email." Plain text plus a simple HTML version.
- Sending uses Django's email system with SMTP. Every setting comes from environment variables, nothing is hard-coded: sender address (`DEFAULT_FROM_EMAIL`, for example `Share Expense <invites@monireach.com>`), SMTP host, port, user, password, SSL/TLS and timeout. Any SMTP provider works; production uses Zoho Mail (`smtp.zoho.com`, port 465 with implicit TLS, an application-specific password; decided 2026-11-28 instead of Cloudflare Email Service, which needs a paid plan to send to any address).
- The email is built from Django templates, so the trip name and the Owner's name are escaped in the HTML version.
- When email is not configured (empty host), the invite is still created, the link is copied, and the Owner sees "Email sending is not set up. Copy the link and send it yourself." Tests and development use Django's console or in-memory backend.
- A failed send never loses the invite: the Owner sees "The email could not be sent. Copy the link and send it yourself." and can use "Send again" later.
- An account can send at most 20 invite emails per hour (all trips together; counted from sent and attempted emails, not copies), so a stolen Owner account cannot be used to send spam. Over the limit: "You have sent many invites in the last hour. Copy the link instead, or try again later."

### Acceptance criteria

```gherkin
Scenario: Username case does not create a second account
  Given an account "maly" exists
  When the admin creates the account "Maly"
  Then the form says the username is taken

Scenario: Inviting an existing account by username
  Given an approved account "cara" exists
  When Ann invites "cara" as traveler Cara
  Then cara is a Member linked to Cara at once
  And cara gets a notification

Scenario: Inviting a new person by email
  When Ann invites "dan@example.com" as traveler Dan
  Then the invite link is copied to Ann's clipboard
  And one invite email is sent to dan@example.com
  And Accounts lists the pending invite with its expiry date and time, 7 days from now

Scenario: Accepting with the invited Google account
  Given a pending invite for dan@example.com as Dan
  When someone opens the link and continues with the Google account dan@example.com
  Then a new approved account exists, linked to traveler Dan, Member of the trip
  And the invite cannot be used again

Scenario: A leaked link is useless to a stranger
  Given a pending invite for dan@example.com
  When someone opens the link and continues with the Google account eve@example.com
  Then no account is created and nobody joins
  And the page says the invite is for another address

Scenario: Google sign-in without an invite is refused
  Given no account uses the Google account x@example.com
  When someone continues with Google as x@example.com from the sign-in page
  Then no account is created
  And the page says to ask a trip Owner for an invite

Scenario: An expired invite
  Given an invite made 8 days ago
  When it is opened
  Then the page says the invite no longer works

Scenario: Closing an account
  Given Cara is a Member of one trip
  When Cara deletes her account and types her username
  Then Cara is signed out and cannot sign in again
  And Cara still appears in the trip's expenses and balances
  And History shows "Cara closed their account"

Scenario: An Owner cannot close an account while others are in the trip
  Given Ann owns a trip with other accounts
  When Ann tries to delete her account
  Then she is told to make someone else the Owner first

Scenario: Copy link ends the old link
  Given a pending invite whose link was sent
  When the Owner taps Copy link
  Then the old link shows that the invite no longer works
  And the new link works

Scenario: A typed email cannot take over an account
  Given the admin stored "cara@example.com" as the email of account cara, which has no linked Google account
  When someone continues with the Google account cara@example.com from the sign-in page
  Then they are not signed in as cara
  And cara's password still works

Scenario: A closed account sees the closed message
  Given Cara closed her account
  When Cara signs in with her password
  Then she sees "This account is closed"
  And the attempt is not counted as a wrong password

Scenario: Old shared links are dead
  When someone opens an old /join/ address
  Then the page says the invite no longer works

Scenario: Email not configured
  Given no SMTP host is set
  When Ann invites dan@example.com
  Then the invite is created and the link is copied
  And Ann sees that she must send the link herself
```

## 7. Out of scope

- Email, Telegram or push notifications, except the invite email (§6.6).
- More than one Owner.
- Roles for travelers without accounts (they never sign in).
- History for reordering.
- An "undo this change" button (fix with a normal edit).
- Protecting a trip from its own Owner: the Owner can remove accounts and delete the trip.

## 8. Delivery

Update 2026-11-27: PRs 1–4 are merged into `develop`. §6.2–§6.6 (personal invites, Google-only new accounts, account menu, closing an account, invite email) replace the shared invite link and the "Request an account" page; they ship as one PR 5 against `develop`. The email code is included and is switched on only by the SMTP environment variables, so the PR works before the email provider is set up.


Four pull requests into `develop`, in this order (each builds on the one before):

1. Roles (§2): Editor role, the permission check on every existing view and template, the read-only expense page, the two database rules (one Owner, one traveler per account), removing an account unlinks it, ownership transfer, the settled-trip rules.
2. History, search and restore (§3), including the History icon in the trip header.
3. Notifications and disputes (§4, §5).
4. Accounts (§6): usernames, the add-account choice, the invite link.

Before PR 1 and PR 4 migrate: check production for data the new database rules would reject (two owners, one account on two travelers, usernames that clash), and get the owner's decision on each.

Each PR: tests for every scenario above that it covers, `ruff check`, `ruff format --check`, the full test suite, and /ui-review screenshots of every new or changed page before it is shown to the owner.

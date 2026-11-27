# Spec: Trip roles, History, disputes and accounts

Status: draft 2, 2026-11-27. Agreed with the owner in chat, then reviewed by four independent reviewers (cheating paths, builder gaps, edge cases, phone journeys); their findings are folded in. Nothing in this file is built yet.

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
- What creates a notification: the dispute events in §5.2, and settling or reopening a trip (every account on the trip except the one who did it). Nothing else.
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

### 6.2 Adding an account by username (Owner)

The "Add account" form has the username and a required choice "Traveler for this account":

- an existing traveler with no account yet (the one whose name matches the account's name is pre-selected);
- a new traveler with the account's name (a form error if that name is taken);
- no traveler ("Viewer"; the form says "No traveler (view only)").

The new membership is a Member. History: "Ann added Cara's account". Adding a previously removed account clears its block on the invite link.

### 6.3 Invite link (Owner)

- On the Travelers page, Accounts section: the Owner turns the link on, copies it, renews it (the old link stops working) or turns it off. Off by default.
- A signed-in approved account opening a working link sees the trip name and the question "Which traveler are you?", listing the travelers with no account, plus "None of them (view only)".
- After the choice, the account joins as a Member, linked to the chosen traveler. History: one line, "Cara joined by link as Cara" (or "Cara joined by link (view only)"); no separate "linked" line.
- **Without an account:** the link sends the visitor to sign in, or to request an account. The request form keeps the link: after the admin approves the account, its first sign-in lands on "Which traveler are you?". A link that was renewed or turned off in between shows "This link no longer works".
- An account already on the trip is taken straight to the trip.
- An account the Owner removed sees "You were removed from this trip. Ask the Owner to add you again."
- Two people choosing the same traveler at the same moment: the second gets "Another account has just chosen this traveler. Choose again.".
- Risk accepted: someone could choose another person's name. History shows it, and the Owner can unlink or remove the account.

### Acceptance criteria

```gherkin
Scenario: Username case does not create a second account
  Given an account "maly" exists
  When someone requests the account "Maly"
  Then the form says the username is taken

Scenario: Invalid username characters are refused
  When someone requests the username "ma.ly"
  Then the form says only a–z, 0–9 and _ are allowed

Scenario: Join by invite link
  Given the invite link is on
  And traveler "Cara" has no account
  When the account cara opens the link and picks "Cara"
  Then cara is a Member linked to Cara
  And History shows "Cara joined by link as Cara"

Scenario: The invite survives an account request
  Given the invite link is on
  When a visitor opens it and requests the account "cara"
  And the admin approves cara
  And cara signs in for the first time
  Then cara sees "Which traveler are you?" for that trip

Scenario: A renewed link stops the old one
  When the Owner renews the invite link
  Then the old link shows "This link no longer works"

Scenario: A removed account cannot rejoin by link
  Given Ann removed Dan's account
  When Dan opens the invite link
  Then Dan sees "You were removed from this trip"

Scenario: Add account creates the traveler
  When Ann adds the account "eve" and picks "A new traveler"
  Then "Eve" appears in All travelers, linked to eve
```

## 7. Out of scope

- Email, Telegram or push notifications.
- More than one Owner.
- Roles for travelers without accounts (they never sign in).
- History for reordering.
- An "undo this change" button (fix with a normal edit).
- Protecting a trip from its own Owner: the Owner can remove accounts and delete the trip.

## 8. Delivery

Four pull requests into `develop`, in this order (each builds on the one before):

1. Roles (§2): Editor role, the permission check on every existing view and template, the read-only expense page, the two database rules (one Owner, one traveler per account), removing an account unlinks it, ownership transfer, the settled-trip rules.
2. History, search and restore (§3), including the History icon in the trip header.
3. Notifications and disputes (§4, §5).
4. Accounts (§6): usernames, the add-account choice, the invite link.

Before PR 1 and PR 4 migrate: check production for data the new database rules would reject (two owners, one account on two travelers, usernames that clash), and get the owner's decision on each.

Each PR: tests for every scenario above that it covers, `ruff check`, `ruff format --check`, the full test suite, and /ui-review screenshots of every new or changed page before it is shown to the owner.

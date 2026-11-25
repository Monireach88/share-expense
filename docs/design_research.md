# Design Research: Wording, Navigation and Layout for Share Expense

## Contents
1. How similar apps word things (Splitwise, Tricount, Settle Up, Splid)
2. Mobile navigation standards (bottom tab bar, touch size, add button)
3. UI/UX rules for this app, each with a do and a don't
4. Decisions for this app
5. Sources that could not be checked

Research date: 2026-11-25.
Method: web search results and the pages that could be fetched.
Many app help pages are only partly public, so each claim says how sure it is.
"Verified" means I read the words on the linked page.
"Unverified" means the claim comes from a user review, a third-party page, or my own knowledge, and someone should check it in the real app.

## 1. How similar apps word things

### 1.1 Balance labels (what one person owes or is owed)

- Tricount defines a balance as "Your net position: how much you owe or are owed after all expenses." Verified: https://tricount.com/glossary/balance
- Tricount defines settle up as "The process of balancing accounts by paying or collecting what you owe." Verified: https://tricount.com/glossary/settle-up
- Splitwise shows a big green checkmark with the text "You are all settled up" on a friend or group screen when nothing is owed. Verified (official Splitwise reply, 2015): http://feedback.splitwise.com/forums/162446-general/suggestions/11020530-1-after-you-settle-up-show-history-somewhere
- Splitwise describes its job as showing "who owes who". Verified: https://apps.apple.com/us/app/splitwise/id458023433
- Splid describes its job as showing "who owes how much to whom". Verified: https://apps.apple.com/gb/app/splid-split-group-bills/id991473495
- Splitwise shows "you owe" and "you are owed" on its home screen, next to a "total balance". Partly verified: a Pratt Institute review confirms "total balance" and money "owed to and from the user", but not the exact label words: https://ixd.prattsi.org/?p=3982
- Splitwise expense rows show "you lent" or "you borrowed" on the right side. Unverified: only an App Store review mentions these labels: https://apps.apple.com/us/app/splitwise/id458023433
- Settle Up shows balances as circles, and "The bigger the circle, the bigger the debt." Verified: https://settleup.io/tips

Pattern: every app uses the same three standard terms, "owes", "is owed" and "settled up".
No app found uses invented phrases like "gets back" or "will pay you".

### 1.2 The action that records a repayment

- Splitwise: a "Settle up" button in the group, which records a cash payment or opens PayPal or Venmo. Verified: https://kb.splitwise.com/getting-started/how-do-i-use-splitwise and https://www.tapsmart.com/tips-and-tricks/splitwise-guide/
- Splitwise App Store text: "settle up by recording cash payments". Verified: https://apps.apple.com/us/app/splitwise/id458023433
- Tricount: you add "a reimbursement like a new expense, but you have to switch it to a 'transfer'". Verified: https://help.tricount.com/d/61447
- Tricount: you can mark a reimbursement that the app suggests as paid "directly in the Balances screen" with the "Mark as paid" option. Verified: https://help.tricount.com/d/61447
- Tricount: reimbursements are not counted in the expense totals. Verified: https://help.tricount.com/articles/tricount-faqs
- Settle Up: "calculates the fewest possible transfers to settle all debts", and it notifies you "the second someone adds an expense or settles up". Verified: https://apps.apple.com/app/id737534985
- Splid: "Splid always finds the easiest way to settle up", so the group makes "as few payments as possible". Verified: https://apps.apple.com/gb/app/splid-split-group-bills/id991473495

Pattern: the button is called "Settle up".
The thing it creates is called a payment, a transfer, or a reimbursement.
A suggested transfer can be confirmed with one tap ("Mark as paid").
Repayments are kept apart from spending, so they never change the "total spent" number.

### 1.3 Trip or group list rows (which number is highlighted)

- Splitwise's home screen highlights the user's total balance in a banner near the top. Partly verified: https://ixd.prattsi.org/?p=3982
- Splitwise's total balance on the home screen also includes non-group expenses. Verified (search snippet of Splitwise help): https://splitwise.uservoice.com/knowledgebase/articles/425486-help-my-balances-are-wrong
- Tricount shows "My Total" (expenses that affect you) and "Expenses total" (the whole group). Verified: https://help.tricount.com/articles/tricount-faqs
- Splid: "Find out how much your group has spent in total." Verified: https://apps.apple.com/gb/app/splid-split-group-bills/id991473495
- Tricount sorts its list of groups by date of creation. Verified (developer reply): https://apps.apple.com/kr/app/tricount-%EA%B7%B8%EB%A3%B9-%EC%B2%AD%EA%B5%AC%EC%84%9C-%EB%B6%84%ED%95%A0/id349866256

Pattern: Splitwise leads with your balance, because it also tracks friends with no group.
Trip-based apps (Tricount, Splid) give the group total its own named number.

### 1.4 Tab names

- Splitwise: "Friends", "Groups", "Activity" and "Me". Partly verified (design review): https://ixd.prattsi.org/?p=3982
- An older third-party note names the last Splitwise tab "Account" instead of "Me". Unverified: https://hackmd.io/@IPQx_t9VQ0eW-6o_04mrpg/HJ2MnZ6vc
- Tricount: an "Expenses (or Balance)" view and a "Profile" tab. Verified: https://help.tricount.com/articles/tricount-faqs
- Tricount also names a "Balances screen". Verified: https://help.tricount.com/d/61447
- Settle Up and Splid tab names: unverified, no public page found.

### 1.5 Analysis and export

- Splitwise: "spending by category" charts and "Export to CSV". Verified: https://apps.apple.com/us/app/splitwise/id458023433
- Settle Up: "View charts on spend by categories and members", "Export your data to CSV", and "Export group history as an Excel file (.xlsx)". Verified: https://apps.apple.com/app/id737534985
- Splid: "Download summaries as PDF or Excel files". Verified: https://apps.apple.com/gb/app/splid-split-group-bills/id991473495
- Tricount: a feature called "Spending insights". Verified: https://tricount.com/en-in/expense-tracker-features
- A Tricount user review says "not having an export or big picture view of the expenses is becoming a dealbreaker". Verified: https://apps.apple.com/kr/app/tricount-%EA%B7%B8%EB%A3%B9-%EC%B2%AD%EA%B5%AC%EC%84%9C-%EB%B6%84%ED%95%A0/id349866256

### 1.6 How a settled group is shown

- Splitwise: a green checkmark with "You are all settled up"; older expenses are hidden, not deleted, and one tap shows them again. Verified: http://feedback.splitwise.com/forums/162446-general/suggestions/11020530-1-after-you-settle-up-show-history-somewhere
- Settle Up: "Debts are settled, now archive the group". Verified: https://settleup.io/tips
- Settle Up has an "archived groups list". Verified (release notes): https://apps.apple.com/app/id737534985
- Tricount: after a balance is marked as paid, everyone's balance returns to zero. Unverified (search snippet only, page now returns 404): https://tricount.com/en-nl/couples

## 2. Mobile navigation standards

### 2.1 Bottom tab bar

- Material (Android): "The navigation bar can hold three to five navigation destinations across the same hierarchy level." Verified: https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns
- Material (older spec): "Three to five top-level destinations of similar importance". Verified: https://m1.material.io/components/bottom-navigation.html
- Material (older spec): "Each icon must lead to a destination, and may not open menus or dialogs." Verified: https://m1.material.io/components/bottom-navigation.html
- Material (older spec): with three tabs, show icons and text labels at all times; tint the current tab with the app's main colour. Verified: https://m1.material.io/components/bottom-navigation.html
- Material (older spec): tapping the current tab again scrolls to the top of that view. Verified: https://m1.material.io/components/bottom-navigation.html
- Apple: "Use a tab bar to support navigation, not to provide actions." Verified: https://developer.apple.com/design/human-interface-guidelines/tab-bars
- Apple: keep the tab bar visible in every section, because without it "people can forget which area of the app they're in". Verified: same page.
- Apple: "Include tab labels" and "Use single words whenever possible." Verified: same page.
- Apple: "Don't disable or hide tab bar buttons, even when their content is unavailable"; explain why a section is empty instead. Verified: same page.
- Apple: use a badge only for critical information. Verified: same page.
- Apple: aim for five tabs or fewer. Verified: same page.
- The current Material 3 page (https://m3.material.io/components/navigation-bar/guidelines) needs JavaScript, so I could not read it; the Android page above quotes the same 3–5 rule.

### 2.2 Minimum touch size

- Apple: "a button needs a hit region of at least 44x44 pt". Verified: https://developer.apple.com/design/human-interface-guidelines/buttons
- Android: touch targets of at least 48 × 48 dp, with 8 dp or more between them. Verified (search snippet of Google's page): https://support.google.com/accessibility/android/answer/7101858
- NN/g: a minimum of about 1 cm × 1 cm for touch targets. Verified (search snippet): https://www.nngroup.com/articles/touch-target-size/
- For CSS this means a minimum height of 48px for each tab, button and tappable list row.

### 2.3 Floating action button or header action

- Android: a floating action button (FAB, a large round button that floats above the content) is "for actions of the highest importance"; "Provide only one action at a time at this level." Verified: https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns
- Android: put secondary actions in the top bar, or inside the page near the content they act on; put rare actions in an overflow menu. Verified: same page.
- Apple: keep the number of prominent buttons "to one or two per view". Verified: https://developer.apple.com/design/human-interface-guidelines/buttons
- For this app: "Add expense" is the one highest-importance action, so it is the FAB; "Export" and "Edit trip" are header or in-page actions.

## 3. UI/UX rules for this app

Each rule has one line, then a Do and a Don't for this app.

### 3.1 Match the real world (Nielsen heuristic 2)
Rule: use the words people already use for this task, in a natural order. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: use "owes", "is owed", "settled up", "Settle up", "payment", the words every similar app uses (section 1).
Don't: replace a standard term with an invented plain phrase such as "gets back" or "will pay you".

### 3.2 Use the reader's vocabulary, even if it is technical
Rule: a domain term that the audience knows is clearer than a plain rewrite; explain only terms most readers will not know. Source: https://www.nngroup.com/articles/specialized-words-specialized-audience/ and https://www.nngroup.com/articles/plain-language-experts/
Do: keep "balance", "settle up", "exchange rate" and "split" as they are.
Don't: explain on screen what a balance is; people who use a money-sharing app already know it.

### 3.3 Consistency and standards (Nielsen heuristic 4)
Rule: behave like the apps people already use, and use one name for one thing everywhere. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: call the same screen "Balances" in the tab, the page title and every link.
Don't: say "Balances" in one place, "Who owes whom" in another and "Summary" in a third.

### 3.4 Visibility of system status (Nielsen heuristic 1)
Rule: always show where the user is and what state things are in. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: show the trip state ("Active" or "Settled") on the trip list row and at the top of the trip.
Don't: leave a fully repaid trip looking the same as a trip with open debts.

### 3.5 Aesthetic and minimalist design (Nielsen heuristic 8)
Rule: every extra line on a screen competes with the line that matters. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: show each balance once, as "Person B owes $25.00".
Don't: repeat "X will pay you Y" under every person, or add hint text that the layout already makes clear.

### 3.6 Recognition rather than recall (Nielsen heuristic 6)
Rule: show options instead of making people remember them. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: list the suggested payments ("Person B pays Person A $25.00") with a "Mark as paid" button on each.
Don't: make the user type the amount and the two names from memory.

### 3.7 Error prevention (Nielsen heuristic 5)
Rule: remove error-prone conditions, or ask for confirmation before an action that is hard to undo. Source: https://www.nngroup.com/articles/ten-usability-heuristics/
Do: pre-fill the settle-up form with the suggested payer, receiver and amount.
Don't: let a payment be deleted with one tap and no confirmation.

### 3.8 Visual hierarchy: one primary number per screen
Rule: use size, colour and contrast so the most important item is seen first. Source: https://www.nngroup.com/articles/visual-hierarchy-ux-definition/
Do: trip list shows the total spent large; the trip's Balances page shows "You are owed $40.00" large; the Spending page shows the filtered total large.
Don't: give three numbers the same size and weight on one card.

### 3.9 Fitts's law and the thumb zone
Rule: big targets that are close to the thumb are faster and cause fewer mistakes. Source: https://www.nngroup.com/articles/fitts-law/
Evidence: in 780 observed phone users, 49% used one hand, 36% cradled the phone and 15% used two hands. Source: https://uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php
Do: put the tab bar and the "Add expense" button at the bottom of the screen, each at least 48px high.
Don't: put the main action as a small link in the top corner.

### 3.10 Progressive disclosure
Rule: show the few most important options first, and move rare ones to a second level. Source: https://www.nngroup.com/articles/progressive-disclosure/
Do: the expense list shows title, payer, amount and date; split details open when the row is tapped.
Don't: show category, currency, rate and the full split list on every row.

### 3.11 Analysis has its own page
Rule: a tab bar holds destinations of similar importance; analysis is a destination, not a block inside a list. Source: https://m1.material.io/components/bottom-navigation.html
Do: a "Spending" tab with filters (person, category, date range) and buttons for CSV and XLSX export.
Don't: put the "where the money went" breakdown at the top of the expense list.

### 3.12 Long lists on mobile: "Load more" or pagination
Rule: a "Load more" button keeps most benefits of endless scrolling but lets people reach the page end and keeps their place. Source: https://nngroup.com/articles/infinite-scrolling-tips and https://www.nngroup.com/articles/alternatives-pagination-listing-pages/
Do: show 25 expenses, then a "Load more" button (one HTMX request that adds the next 25 rows below).
Don't: load 500 rows at once, or use endless scrolling that hides the footer.
Do: the export always contains all rows that match the filters, not only the rows shown on screen.

### 3.13 Tables on a phone
Rule: on a small screen, let people pick a subset of data instead of showing every column. Source: https://www.nngroup.com/articles/mobile-tables/
Do: on the Spending page, show a two-column list (category, amount) and let filters reduce the rows.
Don't: show a wide table that scrolls sideways with no sign that more columns exist.

### 3.14 Number formatting
Rule: right-align numbers in lists and tables so digits line up. Source: https://m1.material.io/components/data-tables.html
Do: always two decimals, a thousands separator, the currency symbol or code, and CSS `font-variant-numeric: tabular-nums` (every digit has the same width) so amounts line up.
Don't: mix "$25", "25.0" and "USD 25.00" on one screen.

### 3.15 Colour for gain and loss, plus a non-colour cue
Rule: colour must never be the only way to show meaning. Source: https://www.w3.org/WAI/WCAG21/Understanding/use-of-color and https://developer.apple.com/design/human-interface-guidelines/accessibility
Do: green with the words "is owed", red with the word "owes", grey with a check mark and "Settled up".
Don't: show a red or green number with no word or sign, because people with red-green colour blindness see the same colour.

## 4. Decisions for this app

One recommendation each, with the reason and the source.

| Item | Recommended term | Reason | Source |
|---|---|---|---|
| Balance, positive | "is owed $X" ("You are owed $40.00" for the viewer; "Person A is owed $40.00" for others) | The standard term in every similar app; Tricount's own definition uses it. | https://tricount.com/glossary/balance |
| Balance, negative | "owes $X" ("You owe $25.00"; "Person B owes $25.00") | Same standard pair; Splitwise and Splid describe their job as "who owes". | https://apps.apple.com/us/app/splitwise/id458023433 |
| Balance, zero | "Settled up", with a check mark | Splitwise's exact words for a zero balance. | http://feedback.splitwise.com/forums/162446-general/suggestions/11020530-1-after-you-settle-up-show-history-somewhere |
| Repayment action | Button "Settle up" on the Balances page; each suggested payment row has "Mark as paid"; the saved record is called a "Payment" | Splitwise names the button "Settle up"; Tricount confirms a suggested transfer with "Mark as paid". Payments do not change "Total spent", as in Tricount. | https://kb.splitwise.com/getting-started/how-do-i-use-splitwise and https://help.tricount.com/d/61447 |
| Analysis tab | "Spending" | Apple asks for single-word tab labels; Tricount calls the feature "Spending insights" and Splitwise "spending by category". | https://developer.apple.com/design/human-interface-guidelines/tab-bars and https://tricount.com/en-in/expense-tracker-features |
| Trip status labels | "Active" and "Settled" (later "Archived" if archiving is built) | "Settled" matches "settled up"; Settle Up uses "Debts are settled" and archived groups. | https://settleup.io/tips |
| Home list primary number | "Total spent" for the trip, large; the viewer's balance on a second, smaller line | Trip-based apps give the group total its own named number; the owner asked for total spent. Splitwise leads with balance, but it also tracks friends outside groups, which this app does not. | https://apps.apple.com/gb/app/splid-split-group-bills/id991473495 and https://help.tricount.com/articles/tricount-faqs |
| Tab bar inside a trip | 4 tabs, each icon plus a one-word label: "Expenses", "Balances", "Spending", "Trip" (people and settings) | 3–5 destinations of the same level; labels always shown; tabs never open actions. | https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns |
| Add expense | One floating "+ Add expense" button above the tab bar, on the Expenses tab | The FAB is for the single most important action; Apple says a tab must not be an action. | https://developer.apple.com/design/human-interface-guidelines/tab-bars |
| Long lists | 25 rows, then a "Load more" button | Keeps the user's place and the page end reachable. | https://nngroup.com/articles/infinite-scrolling-tips |

## 5. Sources that could not be checked

- The Material 3 navigation bar page needs JavaScript, so its exact wording was not read: https://m3.material.io/components/navigation-bar/guidelines
- Splitwise's exact "you owe" / "you are owed" home labels and "you lent" / "you borrowed" row labels: only reviews mention them; check in the app.
- Settle Up and Splid tab names: no public page lists them; check in the apps.
- Tricount's current tab bar: a release note mentions a "Requests tab", so the tabs may have changed: https://apps.apple.com/kr/app/tricount-%EA%B7%B8%EB%A3%B9-%EC%B2%AD%EA%B5%AC%EC%84%9C-%EB%B6%84%ED%95%A0/id349866256

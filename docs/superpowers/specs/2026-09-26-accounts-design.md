# Accounts, approval, workspaces and credits — design

**Status:** approved 2026-09-26. Decisions: users are **both** team members and outside customers; login is
**email and password**; the admin approves every new account; runs are paid with **credits the admin grants**;
a CFD run costs **one credit per simulated minute**; accounts are built **into the app** (a browser refresh asks
for the login again); four phases in the order below, one build plan each.

## Why

The simulator is moving from one engineer's private tool to something other people use: colleagues and
partners on the project, and outside customers testing their own designs. That needs three things the app does
not have: to know who is using it, to keep each customer's work private, and to account for the server hours a
CFD run costs.

## Roles and account states

| Role | Sees | Pays for CFD |
|---|---|---|
| **admin** | everything, plus the Admin screen | no (tracked) |
| **team** | the shared project workspace: `designs/`, all runs, the CFD runs manager | no (tracked) |
| **customer** | only their own workspace: their designs, their runs, their history, plus `examples/` | yes |

An account is **pending** after sign-up, then **approved** (as team or customer) or **rejected** by an admin; an
approved account can later be **disabled**. Only approved accounts get past the login.

## Phase 1 — accounts and approval

**Sign-up:** name, organisation, email, password (twice). The account is created pending and the screen says it is
waiting for approval. **Login:** email and password. A pending account sees "waiting for approval"; a rejected or
disabled one sees that it has no access. **Logout** from the header.

**Admin screen** (a fourth nav entry, admins only):
- pending sign-ups — approve as team or customer, or reject;
- all accounts — role, state, created, last login; disable / re-enable; issue a temporary password;
- every admin action lands in an audit table (who, what, whom, when).

**Password reset** is done by an admin, with no email service: the admin issues a **temporary password**, shown
once on the admin's screen to pass on; the account must set a new password at its next login. No reset token ever
travels in a URL.

**The first admin** is created from the command line on the server: `solit2 accounts create-admin --email …`,
which asks for the password twice (never an argument, never a default).

**Security requirements (not negotiable):**
- passwords hashed with **argon2id** (`argon2-cffi`, the one new dependency; its default parameters exceed the OWASP
  minimum), verified with the library's constant-time check, re-hashed when the parameters change;
- passwords at least 12 characters; the same "email or password is wrong" message for an unknown email and a wrong
  password, and on sign-up a neutral message for an email already registered;
- **lockout:** 5 failed logins lock the account for 15 minutes (counted in the database, per account);
- a session is the Streamlit session: the user id lives in `st.session_state`, never in a URL or a cookie; an idle
  session expires after 8 hours; a refresh asks for the login again (the stated trade-off — the upgrade path is a small
  login gateway in front of the app);
- the login gate runs at the top of `app/streamlit_app.py`, before anything else renders; nothing below it runs for a
  visitor who is not an approved user;
- the server keeps its current Caddy IP allowlist until a security review of this phase has passed; only then is the
  app opened to the public internet.

**Storage:** SQLite (stdlib `sqlite3`) at `$SOLIT2_DATA_DIR/accounts.db` (default `data/accounts.db`, git-ignored),
WAL mode, one short connection per operation. Tables: `users` (id, email unique case-insensitively, name,
organisation, password_hash, must_change_password, role, state, failed_logins, locked_until, created_at,
approved_at, approved_by, last_login_at, session_epoch), `admin_actions` (id, admin_id, action, target_user_id,
detail, at).

**Code layout:** pure logic with no Streamlit import in `app/accounts/` (`passwords.py`, `store.py`,
`service.py`: sign-up, login, approve, reject, disable, temporary password), screens in `app/views/login.py` and
`app/views/admin.py`, the CLI command in `solit2/cli.py`.

## Phase 2 — workspaces

A **workspace** is where a user's files live: team members and admins share the project workspace (today's
`designs/`, `runs/`, `runs/history.jsonl`); each customer has `workspaces/<user_id>/` with its own `designs/`,
`runs/` and `history.jsonl`. Everything that lists or writes files takes the current user's workspace: the
simulator's presets (plus `examples/designs/`), the Design step's file picker, the compliance specs, the CFD run
directories (`cfd.RUNS_DIR`), the history, the reports. The CFD runs manager is admin and team only; a customer's
CFD panel and CFD step show only their own runs. A customer brings designs in by **saving** one built in the app
("Save to my workspace") or **uploading** a design JSON, validated with the schema before it is stored.

Isolation is tested directly: a customer's session never lists, loads or runs a file outside its workspace and
`examples/`.

## Phase 3 — usage and credits

**Usage:** every Tier 1 run, CFD launch, CFD resume and report is an event (user, kind, design SHA, run directory,
simulated minutes, credits, time) in a `usage_events` table.

**Credits:** a `credit_ledger` table (user, change, balance after, reason, reference, admin, time); the balance is
the ledger's running sum, never a separately edited number. Tier 1 runs and reports are free. A **CFD launch costs
one credit per simulated minute** of the deck's `T_END`, rounded up, charged when the run is launched; a resume of a
paid run costs nothing more. A launch without enough credits is refused, saying how many it needs and the balance.
Team and admin runs are tracked at the same price but not charged. The admin grants and refunds credits with a
reason, and sees usage per user with a CSV export.

## Phase 4 — online payment (later)

Buying credits by card sits on top of the ledger (a payment is one more ledger line). Out of scope here; its own
spec when wanted.

## Errors

| Condition | Behaviour |
|---|---|
| wrong password or unknown email | the same message; the failure counts toward lockout |
| locked account | "try again after HH:MM" |
| database unreadable | the login screen says the account store is unavailable; nothing else renders |
| not enough credits | the CFD launch is refused with the needed and current balance |
| upload that is not a valid design | refused with the schema's own message |

## Testing

Unit tests for hashing, lockout, the state machine (pending → approved/rejected → disabled), temporary passwords,
the ledger's running balance and the CFD price; AppTests for the gate (a visitor sees only login/sign-up; a pending
account sees only the wait screen; a customer never sees the Admin nav or another workspace's files); a test that no
password or hash is ever written to a log or shown on screen; the independence scan.

## Out of scope

Email sending (verification, reset links), single sign-on, online payment (Phase 4), per-organisation billing.

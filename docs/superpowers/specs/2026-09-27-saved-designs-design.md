# Saved designs — design

**Status:** approved in chat 2026-09-27. Decisions:

- Saved designs live in **local SQLite**, next to the account store.
- Every save **keeps a version**: one design ID, versions v1, v2, … that are never overwritten.
- **Visibility is owner plus team and admin.**
- The feature is **team and admin only for now**. Customers stay locked out until the rest of Phase 2, the workspaces in `2026-09-26-accounts-design.md`.

## Why

Anyone building a design in the app today loses it when the session ends. The Design step can seed its form
from a file in `designs/`, but it writes nothing back. Engineers iterating on a design need to keep what they
built, find it again, and know which exact inputs produced which result. So a saved design needs an owner, a
stable ID, and an unchangeable history of versions, each carrying the same design SHA that a result's
`meta.design_sha` carries.

This replaces the file-per-customer idea for designs in the accounts spec's Phase 2 (`workspaces/<user_id>/
designs/*.json`). IDs and version history fit a table, not a folder. Runs, history, CFD and reports are still
Phase 2's to isolate.

## Storage

The store is `$SOLIT2_DATA_DIR/designs.db` (default `data/designs.db`, git-ignored), a separate file beside
`accounts.db`. Being separate, it has its own schema version and leaves the account store untouched. It uses
the same conventions as `app/accounts/store.py`:

- Python's standard-library `sqlite3`, one short connection per operation.
- WAL mode.
- The file is owner read/write (`0600`), and a data directory it creates is owner-only (`0700`).
- A store at a newer schema version than the code knows is refused outright.

```sql
CREATE TABLE designs (
    id          INTEGER PRIMARY KEY,
    owner_id    INTEGER NOT NULL,          -- accounts users.id; checked by the service, other file
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE design_versions (
    design_id   INTEGER NOT NULL REFERENCES designs (id),
    version     INTEGER NOT NULL,          -- 1, 2, 3 ... per design
    payload     TEXT NOT NULL,             -- the full design JSON, as `Design.from_dict` accepts it
    sha         TEXT NOT NULL,             -- envelope.design_sha of that design
    saved_by    INTEGER NOT NULL,          -- accounts users.id
    saved_at    TEXT NOT NULL,
    PRIMARY KEY (design_id, version)
);
```

Versions are append-only: nothing updates or deletes a row in `design_versions`. `designs.name` is the name
given at the latest save. Each version's own name is inside its payload, at `meta.name`.

**Durability.** Streamlit Community Cloud wipes the disk on every reboot and redeploy, so `designs.db` does not
survive there. The accounts come back from Secrets; saved designs do not. The Design step therefore also offers
**Download JSON** and says so in plain words. The store is durable on any host with a persistent disk (local,
or the Hetzner server).

## Rules — `app/designs/service.py`

Pure logic, with no Streamlit import. It follows the same split as `app/accounts/`: `store.py` holds the
plain SQL, and `service.py` decides who may do what.

- **Save a new design:** validates the payload with `Design.from_dict` (the same check as **Build &
  continue**), writes the given name into the payload's `meta.name`, and creates the design and its v1.
- **Save a new version:** only the design's owner may do this. The payload is validated the same way. It is
  refused with "no changes since vN" when its SHA equals the latest version's SHA.
- **List:** team and admin see every saved design, each labelled with its owner's email. Any other role sees
  only its own designs. The customer filter is built and tested now, so Phase 2 only has to open the screens.
- **Load:** returns one version's payload, the latest by default, to anyone who may list that design.
- **The SHA** is `solit2.engines.reduced.envelope.design_sha`. Today's private `_design_sha` is made public, so
  a saved design's SHA is by construction the one its results will carry.

Refusals raise typed errors, which the screen shows as messages:

| Error | Raised when |
|---|---|
| `NotAllowed` | a version save by someone other than the owner, or a load of a design the user may not list |
| `NoChanges` | the payload's SHA equals the latest version's |
| `InvalidDesign` | `Design.from_dict` refuses the payload, carrying its message |
| `DesignNotFound` | an unknown design ID or version |

## Screens

**The picker.** The Design step's "Start from" list shows saved designs first, then the `designs/` files as
today. A saved entry reads **Saved · <name> · #<id> v<latest> · <owner email>**. Choosing one shows a
**Version** box, defaulting to the latest, and seeds every field from that version. This uses the view's
existing `_apply_to_widgets`, the same path the file picker takes. The session remembers which saved design
and version it was seeded from.

**The save panel** is a new component, `app/components/save_design.py`, so `app/views/design.py` does not grow.
It sits below the "This system" summary and has:

- A **Name** field, defaulting to the current design's name.
- **Save as v<n+1> of #<id>**, shown only when the form was seeded from a saved design the current user owns.
- **Save as new design**, always shown.
- Both buttons are disabled while nozzle data is missing, with the same reason the Build button gives.
- **Download JSON** of the design as it now stands, with the caption: "Saved designs are kept on this server.
  On Streamlit Community Cloud a reboot erases them; download a copy to keep one."
- After a successful save: **Saved #<id> v<n> · sha <first 12>**. The picker then points at that version.
- Any refusal or database error is shown inline in the panel, and the app does not crash.

## Out of scope

- The Simulator screen's preset list.
- Deleting or renaming saved designs.
- Saving incomplete drafts.
- Any customer access.

Each is its own change later.

## Testing

**Service**, against a temporary data directory (`tests/test_designs_service.py`, `tests/test_designs_store.py`):

- A new design saves as v1; the next save becomes v2; saving an identical payload raises `NoChanges`.
- A version save by someone other than the owner raises `NotAllowed`.
- Team and admin list every design; a customer lists only its own.
- The payload round-trips unchanged, apart from `meta.name` being set to the saved name.
- The stored SHA equals `meta.design_sha` of `envelope.run` on the same design.
- An invalid payload raises `InvalidDesign`.
- `designs.db` is created `0600`, and a store at a newer schema version is refused.

**Screen**, with Streamlit AppTest, signed in as a team account (`tests/test_app_saved_designs.py`):

- Build a design from an example and save it; it appears in the picker.
- Load it; the fields are seeded from it.
- Edit a field and save again; it becomes v2.
- Save is disabled while nozzle data is missing.
- Download JSON is offered.
- A team account loading another user's design sees only **Save as new design**.

"""The print history is paged, and paging must not lose anything.

This is the bug it exists for: the page asked for the 60 newest prints and
nothing else, so a print older than that was simply not on the History tab -
and because a group is a NAME ON EACH PRINT rather than a table of its own, a
group whose members had all scrolled past 60 vanished with them. The prints were
in the database the whole time; only the page had stopped asking.

So the rules here are:
  * `total` counts every print, not the ones in the answer - it is how the page
    knows there is an older page at all;
  * walking the offsets covers the whole table exactly once, no gap and no
    repeat, because a gap is a print the user cannot reach;
  * `offset` reaches past the per-request ceiling - the ceiling guards one
    request, it is not a limit on how far back the history goes;
  * a group older than the first page comes back complete once its page is in.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import os as _os
SRC_DIR = (_os.environ.get("BAMBU_SRC")
           or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import app, storage

c = app.app.test_client()
store = app.store

for r in store.all_prints():          # a clean table: this test counts rows
    store.delete_print(r["job_id"])

N = 145                                # more than two pages of 60
GROUP = "Flughafen Tower"
now = time.time()
for i in range(N):                     # i == 0 is the OLDEST
    job = f"hp-{i:03d}"
    store.upsert_print(job_id=job, name=job, started_at=now - (N - i) * 3600,
                       ended_at=now - (N - i) * 3600 + 1800, final_state="FINISH",
                       total_layers=10, energy_wh=100.0, cost=0.03, peak_w=120.0)
# a three-print group right at the bottom of the history - the case that was
# invisible: every member is older than the first page
OLDEST_GROUP = ["hp-000", "hp-001", "hp-002"]
store.set_print_group(OLDEST_GROUP, GROUP)

# --- the first page says how much it is NOT showing -------------------------
d = c.get("/api/prints?limit=60&offset=0").get_json()
assert len(d["prints"]) == 60, f"first page returned {len(d['prints'])} rows"
assert d["total"] == N, f"total said {d['total']}, the table holds {N}"
assert d["offset"] == 0
assert not any(r["pgroup"] == GROUP for r in d["prints"]), (
    "the oldest group turned up on the first page - this fixture is not "
    "reproducing the bug it is meant to guard")
print(f"page 1: {len(d['prints'])} rows, and it admits to {d['total']} prints")

# --- walking the offsets covers the table exactly once ----------------------
seen, offset = [], 0
while offset < d["total"]:
    page = c.get(f"/api/prints?limit=60&offset={offset}").get_json()
    got = page["prints"]
    assert got, f"offset {offset} came back empty while total says {page['total']}"
    seen += [r["job_id"] for r in got]
    offset += len(got)
assert len(seen) == N, f"paging returned {len(seen)} rows for a table of {N}"
assert len(set(seen)) == N, "a print came back on two pages - offsets overlap"
assert set(seen) == {f"hp-{i:03d}" for i in range(N)}, "paging skipped prints"
print(f"walking the offsets reached all {N} prints, none twice")

# newest-first, across page boundaries and not just inside one page
starts = {r["job_id"]: r for p in
          [c.get(f"/api/prints?limit=60&offset={o}").get_json()["prints"]
           for o in (0, 60, 120)] for r in p}
assert seen == sorted(seen, key=lambda j: -starts[j]["started_at"]), \
    "the pages are each sorted but do not join up in order"
print("the pages join up newest-first")

# --- the group at the bottom comes back whole -------------------------------
last = c.get(f"/api/prints?limit=60&offset=120").get_json()["prints"]
found = [r["job_id"] for r in last if r["pgroup"] == GROUP]
assert sorted(found) == sorted(OLDEST_GROUP), (
    f"the {GROUP!r} group did not come back complete on its page: {found} - "
    "a half-loaded group prices and counts a model wrong")
print(f"{GROUP!r} is reachable in full, {len(found)} prints, on the last page")

# --- offset reaches past the single-request ceiling -------------------------
assert storage.PRINT_PAGE_MAX >= 60
over = store.recent_prints(limit=storage.PRINT_PAGE_MAX + 5000)
assert len(over) == N, "the ceiling should clamp the read, not fail it"
beyond = store.recent_prints(limit=10, offset=N - 3)
assert len(beyond) == 3, f"offset near the end returned {len(beyond)} rows"
assert store.recent_prints(limit=10, offset=N + 10) == [], \
    "an offset past the end must be empty, not the first page again"
assert store.count_prints() == N
print(f"the ceiling clamps one request ({storage.PRINT_PAGE_MAX}); offset walks past it")

# --- a hand-typed query string must not 500 ---------------------------------
for q in ("?limit=abc", "?offset=abc", "?limit=-5", "?offset=-5", "?limit=0",
          "?limit=99999999&offset=99999999"):
    r = c.get("/api/prints" + q)
    assert r.status_code == 200, f"/api/prints{q} answered {r.status_code}"
    assert isinstance(r.get_json().get("prints"), list), f"/api/prints{q} shape"
print("garbage in the query string is clamped, not a 500")

for i in range(N):
    store.delete_print(f"hp-{i:03d}")
print("ok")

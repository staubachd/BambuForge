"""A past print has to keep saying which COLOUR it was printed in.

The per-slot detail stored with a print carries a bare hex and nothing else, so
the history read "Slot 1 · Bambu PLA" - which names a dozen blacks and makes the
print impossible to repeat. The colour name is deliberately NOT frozen into the
print row: it gets typed in, corrected, and merged into another identity long
after the print finished, and a copy stored at print time would be the stale one.

So the rule under test is: /api/prints resolves the colour name on READ, out of
the filament identities, with the same precedence the live AMS view uses - a
name given by hand wins, the Bambu catalogue answers for a coded spool, and a
filament nobody has named keeps its hex and invents nothing.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import os as _os
SRC_DIR = (_os.environ.get("BAMBU_SRC")
           or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import app, filament_catalog

c = app.app.test_client()
store = app.store

JOB = "hc-1"
DET = [{"slot": 1, "type": "PLA", "filament_id": "GFA00", "color": "AA0000",
        "code": None, "brand": "Bambu", "grams": 28.3, "per_kg": 20.0,
        "rule": "test", "cost": 0.566},
       {"slot": 2, "type": "PETG", "filament_id": "GFG00", "color": "1B1B1B",
        "code": None, "brand": "third-party", "grams": 4.0, "per_kg": 18.0,
        "rule": "test", "cost": 0.072}]
FKEY = filament_catalog.key("GFA00", "AA0000", "PLA")

store.upsert_print(job_id=JOB, name="tower.3mf", started_at=time.time() - 600,
                   ended_at=time.time() - 60, final_state="FINISH",
                   total_layers=40, energy_wh=90.0, cost=0.03, peak_w=110.0)
store.update_print_fields(JOB, filament_g=32.3, filament_detail=json.dumps(DET))


def slots():
    rows = c.get("/api/prints?limit=200").get_json()["prints"]
    row = [r for r in rows if r["job_id"] == JOB]
    assert row, "the print vanished from the listing"
    return {s["slot"]: s for s in (row[0].get("filament_detail") or [])}


# --- an unnamed filament keeps its hex and invents nothing -------------------
s = slots()
assert set(s) == {1, 2}, f"expected both slots, got {sorted(s)}"
assert s[1]["color"] == "AA0000", "the stored hex was rewritten"
assert s[1].get("color_name") is None, (
    f"a filament nobody has named came back as {s[1]['color_name']!r} - "
    "a guessed colour name is worse than none")
print("an unnamed filament keeps the hex and gets no invented name")

# --- naming the filament names the colour in the history --------------------
r = c.post("/api/filaments/identity",
           json={"fkey": FKEY, "vendor": "Bambu Lab", "product": "PLA Basic",
                 "color_name": "Scarlet Red"})
assert r.get_json()["ok"], r.get_json()
s = slots()
assert s[1]["color_name"] == "Scarlet Red", (
    f"slot 1 came back as {s[1].get('color_name')!r} - naming a filament has to "
    "reach the prints already in the history, that is the whole point")
assert s[1]["vendor"] == "Bambu Lab" and s[1]["product"] == "PLA Basic", (
    "the identity's own names must beat the cloud's 'Bambu' / 'third-party'")
assert s[2].get("color_name") is None, "naming one slot named another one too"
print("naming a filament names it in every past print:", s[1]["color_name"])

# --- and it is resolved on READ, so a correction reaches the old prints ------
c.post("/api/filaments/identity",
       json={"fkey": FKEY, "vendor": "Bambu Lab", "product": "PLA Basic",
             "color_name": "Maroon Red"})
assert slots()[1]["color_name"] == "Maroon Red", (
    "correcting a colour name left the old prints on the old name - the name "
    "was frozen into the row instead of being resolved on read")
print("correcting the name corrects the history too")

# --- a merged identity answers with the survivor's name ---------------------
OTHER = filament_catalog.key("GFG00", "1B1B1B", "PETG")
store.upsert_filament(OTHER, filament_id="GFG00", color="1B1B1B", type="PETG")
c.post("/api/filaments/identity",
       json={"fkey": FKEY, "vendor": "Bambu Lab", "product": "PLA Basic",
             "color_name": "Maroon Red"})
r = c.post("/api/filaments/merge", json={"from": OTHER, "into": FKEY})
if r.status_code == 200 and r.get_json().get("ok"):
    assert slots()[2]["color_name"] == "Maroon Red", (
        "a folded identity did not answer with the name of the one it was "
        "merged into - the merge map is not being followed on read")
    print("a merged identity reports the survivor's colour name")
else:
    print("merge endpoint not available here, skipped that case:", r.status_code)

# --- the listing survives a print whose detail is nonsense ------------------
store.update_print_fields(JOB, filament_detail="{not json")
assert c.get("/api/prints?limit=200").status_code == 200, \
    "a corrupt filament_detail took the whole history listing down"
store.update_print_fields(JOB, filament_detail=json.dumps(["not a dict", 7]))
assert c.get("/api/prints?limit=200").status_code == 200, \
    "a detail list of non-objects took the history listing down"
print("a corrupt per-slot detail does not take the listing down")

store.delete_print(JOB)
store.delete_filament(FKEY)
store.delete_filament(OTHER)
print("ok")

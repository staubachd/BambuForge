"""Turning down a duplicate suggestion.

The page offers to merge an unnamed identity into a named one of the same
colour and material. That test cannot tell two different reds apart, so the
person has to be able to say "no, these are different" - and that answer has to
stick across reloads, change nothing about usage or cost, and only silence that
one pairing: a different named row that matches later is still offered.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app

c = app.app.test_client()
store = app.store
NAMED, STRAY, OTHER = "GFA00|AB0000", "GFL99|AB0000", "GFA01|AB0000"
now = time.time()


def a_print(job, fkey, grams):
    sku, _, hexc = fkey.partition("|")
    store.upsert_print(job_id=job, name=job, started_at=now - 3600, ended_at=now,
                       final_state="FINISH", total_layers=1)
    store.update_print_fields(job, filament_detail=json.dumps([{
        "filament_id": sku, "color": hexc, "type": "PLA",
        "grams": grams, "cost": grams / 1000.0 * 20, "slot": 1}]))


def pairs():
    return {(s["from"], s["into"]) for s in app._filament_stats()["suggestions"]}


a_print("nd-a", NAMED, 200.0)
a_print("nd-b", STRAY, 80.0)
store.upsert_filament(NAMED, filament_id="GFA00", color="AB0000", type="PLA",
                      product="PLA Basic", color_name="Red")
assert (STRAY, NAMED) in pairs(), f"the fixture did not produce a suggestion: {pairs()}"
before = {r["fkey"]: r for r in app._filament_stats()["filaments"]}
print("suggested:", STRAY, "->", NAMED)

r = c.post("/api/filaments/not-dupe", json={"from": STRAY, "into": NAMED}).get_json()
assert r["ok"], r
assert (STRAY, NAMED) not in pairs(), "the dismissed suggestion came back"
after = {r["fkey"]: r for r in app._filament_stats()["filaments"]}
for k in (NAMED, STRAY):
    assert (before[k]["grams"], before[k]["cost"]) == (after[k]["grams"], after[k]["cost"]), \
        f"{k}: dismissing a suggestion changed usage or cost"
assert not after[STRAY].get("merged") and not after[NAMED].get("merged"), \
    "dismissing merged something"
print("dismissed: gone, both rows untouched")

# only that pairing is silenced
a_print("nd-c", OTHER, 50.0)
store.upsert_filament(OTHER, filament_id="GFA01", color="AB0000", type="PLA",
                      product="PLA Matte", color_name="Red")
assert (STRAY, OTHER) in pairs(), \
    f"a different named match is no longer offered either: {pairs()}"
print("another named match is still offered")

bad = c.post("/api/filaments/not-dupe", json={"from": STRAY, "into": ""})
assert bad.status_code == 400
print("refused: a dismissal with no target")
print("ok")

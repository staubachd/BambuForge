"""The cloud's slot number is wrong, so the AMS snapshot is found by colour.

Taken from real data: across 258 prints, every one of 348 filament lines in the
cloud's amsDetailMapping said slot 1, wherever the spool actually sat. The
snapshot of the AMS - the thing that corrects the slicer PROFILE to the spool's
real SKU - was looked up by that slot, disagreed on colour, and was thrown away.
So a PLA Matte spool in tray 3, printed with a PLA Basic profile, was recorded
as GFA00 and turned up as a "possible duplicate" of itself. 18 lines did that.

The colour is the reliable half, so the tray is found by it. When two trays of
that colour hold different spools there is no telling which one ran, and the
profile is kept rather than guessed.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app

for p in app.store.all_prints():
    app.store.delete_print(p["job_id"])

PINK, WHITE, BONE = "E8AFCF", "FFFFFF", "CBC6B8"
AMS = {
    "1": {"sku": "GFA00", "color": WHITE, "type": "PLA", "code": "A00-W1", "bambu": True},
    "2": {"sku": "GFA01", "color": BONE,  "type": "PLA", "code": "A01-W3", "bambu": True},
    "3": {"sku": "GFA01", "color": PINK,  "type": "PLA", "code": "A01-P3", "bambu": True},
    "4": {"sku": "GFA01", "color": BONE,  "type": "PLA", "code": "A01-W3", "bambu": True},
}


def run(job, lines, ams=AMS):
    app.store.upsert_print(job_id=job, name="Test", started_at=time.time() - 3600,
                           ended_at=time.time(), final_state="FINISH", total_layers=100,
                           energy_wh=100, cost=0.03, peak_w=90)
    app.store.update_print_fields(
        job, ams_slots=json.dumps(ams),
        ams_bambu=json.dumps({k: v["bambu"] for k, v in ams.items()}))
    mapping = [{"slotId": slot - 1, "filamentId": sku, "filamentType": "PLA",
                "targetColor": "#" + col + "FF", "weight": 10.0}
               for slot, sku, col in lines]
    assert app._apply_cloud_task({"id": job, "status": 2, "weight": 10.0 * len(lines),
                                  "amsDetailMapping": mapping})
    return json.loads(app.store.get_print(job)["filament_detail"])


# 1. the bug: matte spool in tray 3, cloud says slot 1 and the Basic profile
d = run("pink", [(1, "GFA00", PINK)])[0]
print("tray 3, cloud says slot 1 :", d["filament_id"], d["code"], "slot", d["slot"])
assert d["filament_id"] == "GFA01", f"the slicer profile won over the spool: {d}"
assert d["code"] == "A01-P3", d
assert d["slot"] == 3, "the line should name the tray the spool was really in"
assert d["brand"] == "Bambu", d

# 2. the slot number happens to be right: unchanged behaviour
d = run("white", [(1, "GFA01", WHITE)])[0]
print("tray 1, cloud says slot 1 :", d["filament_id"], d["code"], "slot", d["slot"])
assert (d["filament_id"], d["code"], d["slot"]) == ("GFA00", "A00-W1", 1), d

# 3. the same spool in two trays is still one answer
d = run("bone", [(1, "GFA00", BONE)])[0]
print("two trays, same spool     :", d["filament_id"], d["code"], "slot", d["slot"])
assert (d["filament_id"], d["code"]) == ("GFA01", "A01-W3"), d

# 4. two trays of that colour with DIFFERENT spools: cannot tell, keep the profile
clash = dict(AMS)
clash["4"] = {"sku": "GFA00", "color": BONE, "type": "PLA", "code": "A00-W9", "bambu": True}
d = run("clash", [(1, "GFA02", BONE)], ams=clash)[0]
print("two trays, two spools     :", d["filament_id"], d["code"], "slot", d["slot"])
assert d["filament_id"] == "GFA02" and d["code"] is None, \
    f"guessed between two different spools: {d}"

# 5. a colour the AMS never held (external spool): the profile is all there is
d = run("ext", [(1, "GFL99", "123456")])[0]
print("colour not in the AMS     :", d["filament_id"], d["code"], "slot", d["slot"])
assert d["filament_id"] == "GFL99" and d["code"] is None, d

# 6. several lines in one job, all reported as slot 1, each lands on its own tray
ds = run("multi", [(1, "GFA00", PINK), (1, "GFA01", WHITE)])
print("two lines, both 'slot 1'  :", [(x["filament_id"], x["slot"]) for x in ds])
assert [(x["filament_id"], x["slot"]) for x in ds] == [("GFA01", 3), ("GFA00", 1)], ds

# and the filament page no longer offers the pink spool as its own duplicate
app.store.upsert_filament(f"GFA01|{PINK}", filament_id="GFA01", type="PLA", color=PINK,
                          code="A01-P3", product="PLA Matte", color_name="Sakura-Pink",
                          is_bambu=1)
app._rebuild_filament_meta()
keys = {f["fkey"] for f in app._filament_stats()["filaments"]}
sugg = app._filament_stats()["suggestions"]
print("identities:", sorted(k for k in keys if PINK in k), "suggestions:", sugg)
assert f"GFA00|{PINK}" not in keys, "the pink spool was split into a second identity"
assert not [s for s in sugg if PINK in s["from"]], sugg
print("ok")

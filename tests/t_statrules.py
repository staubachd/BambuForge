"""The statistics page's newer figures: the month split, where the material
money came from, how many prints have a measured power figure, and the single
dearest print. What has to hold:

  * a month's power + material add up to its cost
  * each pricing rule lands in exactly one of the four families
  * the dearest print is the one with the highest power + material
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app

store = app.store
now = time.time()

assert app._rule_bucket("set by hand") == "hand"
assert app._rule_bucket("order GFA01") == "orders"
assert app._rule_bucket("default") == "default" and app._rule_bucket(None) == "default"
for r in ("slot 2", "GFA00", "Bambu PLA", "PLA"):
    assert app._rule_bucket(r) == "matrix", r
print("every rule lands in one family")

rows = [("sr-1", 1.0, 2.0, "order GFA01", 500), ("sr-2", 0.5, 6.0, "set by hand", None),
        ("sr-3", 0.2, 1.0, "default", 100)]
for job, pc, mc, rule, wh in rows:
    store.upsert_print(job_id=job, name=job, started_at=now - 3600, ended_at=now - 60,
                       final_state="FINISH", total_layers=10)
    store.update_print_fields(job, cost=pc, filament_cost=mc, energy_wh=wh,
                              filament_detail=json.dumps([{"rule": rule, "cost": mc}]))

d = app._stats_block()
for m in d["by_month"]:
    assert abs(m["power_cost"] + m["material_cost"] - m["cost"]) < 0.02, m
print("month power + material = month cost")

cr = d["cost_rules"]
assert cr["orders"] >= 2.0 and cr["hand"] >= 6.0 and cr["default"] >= 1.0, cr
print("material money by rule:", cr)

assert d["power_measured"]["prints"] <= d["power_measured"]["of"]
assert d["dearest"]["job_id"] == "sr-2" and abs(d["dearest"]["cost"] - 6.5) < 1e-6, d["dearest"]
print("the dearest print is sr-2 at 6.50")

for job, *_ in rows:
    store.delete_print(job)
print("ok")

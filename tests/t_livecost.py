"""What the running print costs, on the live view.

The finished print is costed from the cloud's per-slot grams; while it runs
there is only the sliced file (read early, for the filament changes) and the
plug's integral for this job. What has to hold:

  * power so far is the plug's own figure for this job, never another job's
  * material so far is the file's total scaled by progress - and the total is
    priced by the same rule chain as a finished print
  * no projection until enough of the print has run to stretch the power over
  * each filament is tied to its AMS slot by colour, for the per-spool lines
  * the last finished print of the same model is offered for comparison
  * the colour column: the slicer's layer runs, with colours for the ids
  * nothing at all on an idle machine
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app

store = app.store
now = time.time()


class _Cfg:
    def __init__(self, real, **over):
        self.real, self.over = real, over

    def get(self, k, d=None):
        return self.over[k] if k in self.over else self.real.get(k, d)


app.COST_CFG = _Cfg(app.COST_CFG, price_per_kwh=0.30, currency="€")
# one fixed price per kg, so the arithmetic below is checkable by hand
app.FIL_CFG = _Cfg(app.FIL_CFG, default_per_kg=20.0, per_type={}, per_slot={},
                   per_filament_id={}, bambu={}, other={}, prices_from_orders=False)
app.PRICES_FROM_ORDERS = lambda: False
app._FIL_PRICES.clear()

META = {"v": 2, "changes": 1, "change_layers": [[10, 1]], "layer_h": 0.2,
        "profile": "0.20mm Standard @BBL X2D",
        "filaments": [{"slot": 1, "color": "#0078BF", "type": "PLA", "grams": 100.0,
                       "code": "GFA01"},
                      {"slot": 2, "color": "#F5F3EE", "type": "PLA", "grams": 50.0,
                       "code": "GFA00"}],
        "layer_fils": [[0, 9, [1]], [10, 19, [1, 2]]]}
SLOTS = {"1": {"color": "F5F3EE", "type": "PLA", "sku": "GFA00", "code": "A00-W01"},
         "2": {"color": "0078BF", "type": "PLA", "sku": "GFA01", "code": "A01-B04"}}


def start(job, design=None):
    store.upsert_print(job_id=job, name="Vase", started_at=now - 600, ended_at=None,
                       final_state="RUNNING", total_layers=20)
    app._print_row.update(job_id=job, design_id=design,
                          stored={"ams_slots": json.dumps(SLOTS), "ams_bambu": "{}"})
    app._live_slice.update(job_id=job, meta=META, change_layers=META["change_layers"],
                           changes=1, done=0, busy=False, tries=0, next_at=1e12)
    app._live_cost_cache.update(job_id=job, material=None, last=None, last_done=False)
    app._job_energy.update(task_id=job, wh=0.0, last_ts=None)


def frame(job, layer, state="RUNNING", design=None):
    s = {"job": {"task_id": job, "state": state, "layer": layer, "total_layers": 20,
                 "name": "Vase", "design_id": design}}
    app._live_cost(s)
    return s["job"]


# --- a finished print of the same model, to compare against ----------------
store.upsert_print(job_id="lcost-old", name="Vase", started_at=now - 86400 * 3,
                   ended_at=now - 86400 * 3 + 3600, final_state="FINISH", total_layers=20)
store.update_print_fields("lcost-old", cost=0.5, filament_cost=2.75)

# --- early in the print: power only, no projection yet ---------------------
start("lcost-1")
app._job_energy["wh"] = 100.0                      # 0.1 kWh -> 0.03 €
j = frame("lcost-1", 0)
c = j["live_cost"]
assert c["energy_cost"] == 0.03, c
assert c["material_total"] == 3.0, c               # 150 g at 20 €/kg
assert "projected" not in c, "projected from a print that has barely started"
print("at layer 0: power is the plug's, material known, no projection yet")

# --- halfway: material scales with progress, the projection appears --------
app._job_energy["wh"] = 1000.0                     # 1 kWh -> 0.30 €
c = frame("lcost-1", 10)["live_cost"]
assert c["fraction"] == 0.5, c
assert c["material_so_far"] == 1.5 and c["grams_so_far"] == 75.0, c
assert c["so_far"] == 1.8, c                       # 0.30 + 1.50
assert c["projected"] == 3.6, c                    # 3.00 + 0.30 / 0.5
print("halfway: 1.80 so far, 3.60 projected")

# --- the filaments are tied to their AMS slots by colour -------------------
by_color = {s["color"]: s["slot"] for s in c["spools"]}
assert by_color == {"0078BF": 2, "F5F3EE": 1}, c["spools"]
print("each filament found its slot by colour")

# --- the last print of the same model -----------------------------------
assert c["last_of_model"]["cost"] == 3.25, c.get("last_of_model")
print("the last print of the same model is offered: 3.25")

# --- the colour column and the slicer facts -----------------------------------
j = frame("lcost-1", 10)
assert j["layer_runs"] == [[0, 9, ["0078BF"]], [10, 19, ["0078BF", "F5F3EE"]]], j["layer_runs"]
assert j["slice"]["layer_h"] == 0.2 and j["slice"]["profile"], j["slice"]
print("layer runs carry colours, not ids")

# --- another job's energy is never this one's ---------------------------------
app._job_energy.update(task_id="someone-else", wh=5000.0)
c = frame("lcost-1", 10)["live_cost"]
assert c["energy_cost"] is None and "projected" not in c, c
print("another job's energy is not counted")

# --- nothing while idle --------------------------------------------------------
j = frame("lcost-1", 20, state="FINISH")
assert "live_cost" not in j and "layer_runs" not in j
print("an idle machine shows nothing")

# --- the history page does not carry the layer runs ------------------------
store.update_print_fields("lcost-1", slice_json=json.dumps(META), ended_at=now,
                          final_state="FINISH")
rows = app.app.test_client().get("/api/prints?limit=50").get_json()
rows = rows.get("prints", rows) if isinstance(rows, dict) else rows
row = next(r for r in rows if r["job_id"] == "lcost-1")
assert "layer_fils" not in (row.get("slice") or {}), row.get("slice")
print("the history leaves the layer runs out")

for job in ("lcost-1", "lcost-old"):
    store.delete_print(job)
print("ok")

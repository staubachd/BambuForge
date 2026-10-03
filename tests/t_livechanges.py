"""Filament changes of the running print: done / total on the live view.

The printer never reports them, so the sliced file is read once, early in the
print, and the count follows the layer from then on. What has to hold:

  * nothing is read in the first moments of a print, and only once after that -
    this runs on the MQTT frame rate and must not become an FTP poll
  * a row that already has the list (an app restart mid-print) is not read again
  * a file that cannot be read is tried twice, then left alone
  * a partial MQTT frame with no layer keeps the last count instead of blanking
  * the per-layer list stays off the history page
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


app.SLICER_CFG = _Cfg(app.SLICER_CFG, enabled=True)
app.LIVE_SLICE_RETRY = 0.0
reads = []


def fake_apply(row, conn=None):
    """What reading the drive would store: the stripe from gcode_meta's test."""
    reads.append(row["job_id"])
    if row["job_id"] == "lc-missing":
        return False                               # no such file on the drive
    meta = {"v": 2, "changes": 2, "change_layers": [[5, 1], [8, 1]], "layers": 9}
    store.update_print_fields(row["job_id"], slice_json=json.dumps(meta))
    return True


app._slicer_apply = fake_apply


def a_print(job):
    store.upsert_print(job_id=job, name=job, started_at=now - 600, ended_at=None,
                       final_state="RUNNING", total_layers=9)


def frame(job, layer, state="RUNNING"):
    s = {"job": {"task_id": job, "state": state, "layer": layer}}
    app._live_changes(s)
    return s["job"].get("fil_changes")


def settle():
    for _ in range(100):
        if not app._live_slice["busy"]:
            return
        time.sleep(0.02)
    raise AssertionError("the background read never finished")


# --- nothing in the first moments -------------------------------------------
a_print("lc-1")
app.LIVE_SLICE_DELAY = 30.0
assert frame("lc-1", 1) is None and not reads and not app._live_slice["busy"]
print("the first frames of a print read nothing")

# --- then exactly one read ---------------------------------------------------
app._live_slice["next_at"] = 0
frame("lc-1", 2); settle()
assert reads == ["lc-1"], reads
got = frame("lc-1", 2)
assert got == {"done": 0, "total": 2}, got
for layer in range(3, 10):
    frame("lc-1", layer)
assert reads == ["lc-1"], f"read again while printing: {reads}"
assert frame("lc-1", 6) == {"done": 1, "total": 2}
assert frame("lc-1", 9) == {"done": 2, "total": 2}
print("one read, then the count follows the layer: 0/2 -> 1/2 -> 2/2")

# --- a partial frame keeps the last count ---------------------------------
assert frame("lc-1", None) == {"done": 2, "total": 2}
print("a frame without a layer keeps the count")

# --- not while idle --------------------------------------------------------
s = {"job": {"task_id": "lc-1", "state": "FINISH", "layer": 9}}
app._live_changes(s)
assert "fil_changes" not in s["job"]
print("a finished job shows nothing")

# --- an app restart mid-print: the row already knows ----------------------
reads.clear()
app._live_slice.update(job_id=None)
app.LIVE_SLICE_DELAY = 0.0
frame("lc-1", 7); settle()
assert reads == [], "the drive was read for a print whose row already had the list"
assert frame("lc-1", 7) == {"done": 1, "total": 2}
print("after a restart the stored list is used, the drive is left alone")

# --- a file that is not there: twice, then never ------------------------------
a_print("lc-missing")
reads.clear()
for _ in range(8):
    frame("lc-missing", 3); settle()
assert reads == ["lc-missing", "lc-missing"], reads
assert frame("lc-missing", 3) is None
print("an unreadable file is tried twice, then left alone")

# --- the history page does not carry the per-layer list --------------------
store.update_print_fields("lc-1", ended_at=now, final_state="FINISH")
rows = app.app.test_client().get("/api/prints?limit=50").get_json()
rows = rows.get("prints", rows) if isinstance(rows, dict) else rows
row = next(r for r in rows if r["job_id"] == "lc-1")
assert row["slice"]["changes"] == 2 and "change_layers" not in row["slice"], row["slice"]
print("the history shows the count, without the per-layer list")

for job in ("lc-1", "lc-missing"):
    store.delete_print(job)
print("ok")

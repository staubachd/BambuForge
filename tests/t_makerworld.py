"""The MakerWorld tab, without the network.

The API behind makerworld.com is undocumented, so the tests feed makerworld.py
a canned answer in the shape it returns today and check what the page is given:

  * a profile re-sliced for the printer in this workshop carries THAT printer's
    figures, and profiles for it come first
  * the author's HTML never reaches the page - only its text does
  * each filament of a profile is matched against the AMS by material first and
    colour second, a tray is handed out once, and the shelf is the fallback
  * the history's picture lookup fetches a few new models per call and says
    which are still to come, and a model gone from MakerWorld is not asked for
    again
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
import makerworld

c = app.app.test_client()
calls = []

DESIGN = {
    "id": 111, "title": "Desk Tidy", "coverUrl": "https://makerworld.bblmw.com/m/cover.jpg",
    "summary": "<p>Hi&nbsp;there</p><script>alert(1)</script><ul><li>glue</li></ul>"
               "<img src=x onerror=alert(2)>",
    "designCreator": {"name": "Maker <b>Bob</b>"},
    "license": "BY", "tags": ["desk", "<i>tidy</i>"], "categories": [{"name": "Household"}],
    "likeCount": 1500, "printCount": 20, "downloadCount": 30, "collectionCount": 4,
    "designExtension": {"design_pictures": [
        {"url": "https://makerworld.bblmw.com/m/p1.jpg"},
        {"url": "https://makerworld.bblmw.com/m/p1.jpg"}]},     # a duplicate
    "instances": [
        {   # sliced for a P1S, re-sliced by Bambu for the X2D
            "id": 1, "profileId": 10, "title": "P1S original", "printCount": 900,
            "weight": 50, "prediction": 3600, "needAms": True,
            "instanceFilaments": [{"type": "PLA", "color": "#FFFFFF", "usedG": "30"},
                                  {"type": "PLA", "color": "#000000", "usedG": "20"}],
            "extention": {"modelInfo": {"compatibility": {"devProductName": "P1S"},
                                        "otherCompatibility": [{"devProductName": "X2D"}],
                                        "plates": [{}]},
                          "otherCompatibilityModelInfo": [{
                              "devProductName": "X2D", "profileId": 99, "weight": 48,
                              "prediction": 3000,
                              "instanceFilaments": [
                                  {"type": "PLA", "color": "#FFFFFF", "usedG": "29"},
                                  {"type": "PLA", "color": "#101010", "usedG": "19"}]}]},
        },
        {   # another printer entirely, popular
            "id": 2, "profileId": 20, "title": "A1 only", "printCount": 5000,
            "weight": 40, "prediction": 2400,
            "instanceFilaments": [{"type": "PETG", "color": "#FF0000", "usedG": "40"}],
            "extention": {"modelInfo": {"compatibility": {"devProductName": "A1"}}},
        },
        {   # made for the X2D
            "id": 3, "profileId": 30, "title": "X2D native", "printCount": 1,
            "weight": 300, "prediction": 600,
            "instanceFilaments": [{"type": "PLA", "color": "#F0F0F0", "usedG": "300"},
                                  {"type": "PLA", "color": "#FDFDFD", "usedG": "5"}],
            "extention": {"modelInfo": {"compatibility": {"devProductName": "X2D"}}},
        },
    ],
}


def fake_get(path, ttl, token=None):
    """Answers like the real _get, caching included - the history lookup
    decides what to fetch by what is already cached."""
    calls.append((path, token))
    data = _answer(path, token)
    makerworld._cache[("auth:" if token else "") + path] = (time.time() + 60, data)
    return data


def _answer(path, token=None):
    if path == "/v1/design-user-service/my/profile":
        if token != "good":
            raise makerworld.MWError("login")
        return {"uid": 42, "name": "me"}
    if path.startswith("/v1/design-user-service/user/42/follows"):
        return {"total": 1, "hits": [{"uid": 7, "name": "Chan", "handle": "chan",
                                      "fanCount": 1200,
                                      "avatar": "https://public-cdn.bblmw.com/a.jpg"}]}
    if path == "/v1/design-user-service/user/profile/7":
        return {"uid": 7, "name": "Chan", "handle": "chan", "fanCount": 1200}
    if path.startswith("/v1/design-service/published/7/design"):
        return {"total": 1, "hits": [{"id": 111, "title": "Desk Tidy",
                                      "coverUrl": "https://makerworld.bblmw.com/x.png"}]}
    if path.startswith("/v1/search-service/select/design/nav"):
        if "navKey=Following" in path and token == "good":
            return {"total": 1, "hits": [{"id": 112, "title": "Hook"}]}
        return {"total": 0, "hits": []}     # what Following answers anonymously
    if path == "/v1/search-service/homepage/nav":
        return {"navs": [{"key": "Following", "name": "Following", "type": 3},
                         {"key": "Trending", "name": "Trending", "type": 2}]}
    if path.startswith("/v1/design-service/my/favorites/listlite"):
        if token != "good":
            raise makerworld.MWError("login")
        return {"code": 0, "data": {"list": [
            {"id": 555, "title": "Werkstatt", "designCnt": 2, "status": 1,
             "designCover": ["https://makerworld.bblmw.com/a.png"]},
            {"id": 556, "title": "<b>Default</b>", "designCnt": 0, "isDefault": True}]}}
    if path.startswith("/v1/design-service/favorites/555"):
        if token != "good":
            raise makerworld.MWError("private")
        if "/designs" in path:
            return {"total": 2, "hits": [{"id": 111, "title": "Desk Tidy",
                                          "designCreator": {"name": "Bob"}},
                                         {"id": 112, "title": "Hook"}]}
        return {"id": 555, "title": "Werkstatt", "designCnt": 2, "status": 1,
                "creator": {"name": "me"}}
    if path.startswith("/v1/design-service/favorites/777"):
        if token:                    # an expired login is refused even on a public one
            raise makerworld.MWError("login")
        if "/designs" in path:
            return {"total": 1, "hits": [{"id": 40146, "title": "Benchy"}]}
        return {"id": 777, "title": "Public", "designCnt": 1, "status": 2}
    if path.startswith("/v1/design-service/design/111"):
        return DESIGN
    if path.startswith("/v1/design-service/design/404"):
        return {}                           # what _get caches for a 404
    if path.startswith("/v1/design-service/design/"):
        did = int(path.rsplit("/", 1)[1])
        return {"id": did, "title": f"Model {did}", "coverUrl": None,
                "designCreator": {"name": "x"}}
    if "select/design2" in path:
        return {"total": 1, "hits": [{"id": 5, "title": "Found", "cover": None,
                                      "designCreator": {"name": "y"}, "nsfw": False}]}
    raise makerworld.MWError(f"unexpected call {path}")


makerworld._get = fake_get
class _Cfg:
    """The printer model this workshop has, whatever the database copy says."""
    def __init__(self, real):
        self.real = real

    def get(self, k, d=None):
        return "X2D" if k == "model" else self.real.get(k, d)


app.CFG = _Cfg(app.CFG)

# what is loaded: a white and a near-black PLA, and a PETG in an unrelated colour
with app._state_lock:
    app._state["ams"] = {"units": [{"id": 0, "trays": [
        {"id": 0, "type": "PLA", "color": "FFFFFF", "filament_id": "GFA00", "grams_left": 800},
        {"id": 1, "type": "PLA", "color": "000000", "filament_id": "GFA00", "grams_left": 10},
        {"id": 2, "type": "PETG", "color": "00FF00", "filament_id": "GFG00", "grams_left": 500},
    ]}], "external": []}

r = c.get("/api/mw/design/111")
assert r.status_code == 200, r.get_data(as_text=True)
d = r.get_json()["design"]

# --- what the page is given ------------------------------------------------
assert "<" not in d["summary"] and "alert" not in d["summary"], d["summary"]
assert d["summary"] == "Hi there\n\n• glue", repr(d["summary"])
print("the description reaches the page as text only")
assert len(d["pictures"]) == 1, "the same picture twice"
assert d["pictures"][0]["full"].endswith("format,webp"), "a full-size original would be MBs"
assert d["url"] == "https://makerworld.com/models/111"
print("pictures deduplicated and resized")

# --- profiles for this printer first, with this printer's figures ----------
order = [p["title"] for p in d["profiles"]]
assert order == ["X2D native", "P1S original", "A1 only"], order
p1s = d["profiles"][1]
assert p1s["for_printer"] == "adapted" and p1s["profile_id"] == 99, p1s
assert p1s["weight_g"] == 48 and p1s["minutes"] == 50, "the P1S figures were kept"
print("the X2D profile first, then the one Bambu re-sliced for it, with its own figures")

# --- matching ----------------------------------------------------------------
w, b = p1s["filaments"]
assert w["ams"]["slot"] == "1" and w["ams"]["level"] == "same", w
assert b["ams"]["slot"] == "2" and b["ams"]["level"] == "same", b      # 101010 vs 000000
assert b["ams"]["short"], "19 g wanted, 10 g left, and nothing said"
assert p1s["all_loaded"]
print("white and black found in slots 1 and 2; the black one is flagged as running short")

native = d["profiles"][0]
first, second = native["filaments"]
# two near-whites, one white spool: the closer one (FDFDFD) gets it, and the
# other must not claim the same tray
assert second["ams"]["slot"] == "1", second
assert "ams" not in first, f"one spool was handed out twice: {first}"
assert not native["all_loaded"]
print("a spool is handed out once, even to two near-identical colours")

petg = d["profiles"][2]["filaments"][0]
assert "ams" not in petg, "a green PETG was offered for a red one"
print("material has to agree, and a far-off colour is not a match")

# the shelf is the fallback when nothing is loaded
shelf = [{"type": "PETG", "color": "EE1111", "name": "Sunlu PETG Red", "left_g": 700}]
m = app._mw_match([{"type": "PETG", "color": "FF0000", "grams": 40}], [], shelf)[0]
assert m["shelf"]["name"] == "Sunlu PETG Red" and m["shelf"]["level"] == "same", m
m = app._mw_match([{"type": "PLA", "color": "FF0000", "grams": 40}], [], shelf)[0]
assert "shelf" not in m and "ams" not in m
print("the shelf answers when the AMS does not, and only for the same material")

# an offline printer is an unknown AMS, not an empty one
assert d["ams_known"] is True
with app._state_lock:
    saved = app._state.pop("ams")
off = c.get("/api/mw/design/111").get_json()["design"]
with app._state_lock:
    app._state["ams"] = saved
assert off["ams_known"] is False, "an offline printer would read as 'nothing loaded'"
print("with the printer offline the page is told the AMS is unknown")

# --- errors -----------------------------------------------------------------
assert c.get("/api/mw/design/404").status_code == 404
print("a model gone from MakerWorld answers 404, not a crash")

# --- the history's pictures ----------------------------------------------------
makerworld._cache.clear()
calls.clear()
ids = ",".join(str(1000 + i) for i in range(12)) + ",404,junk"
r = c.get("/api/mw/briefs?ids=" + ids).get_json()
assert r["ok"]
assert len(r["briefs"]) == 8, f"fetched {len(r['briefs'])} in one call, expected a batch of 8"
assert "junk" not in r["briefs"] and "junk" not in r["pending"]
assert len(r["pending"]) == 5, r["pending"]    # 4 left over + the 404 not asked yet
print("one call fetches a batch of 8 and says what is still to come:", len(r["pending"]))
r = c.get("/api/mw/briefs?ids=" + ids).get_json()
assert len(r["briefs"]) == 12 and r["pending"] == [], r
assert "404" not in r["briefs"]
print("the next call finishes it; the removed model is simply left without a picture")

# --- browse ---------------------------------------------------------------------
r = c.get("/api/mw/browse?q=found").get_json()
assert r["ok"] and r["hits"][0]["title"] == "Found", r
print("search answers through the same reduced shape")

# --- my collections ------------------------------------------------------------
app._mw_token = lambda: None
r = c.get("/api/mw/collections")
assert r.status_code == 401 and r.get_json()["error"] == "login", r.get_json()
assert c.get("/api/mw/navs").get_json()["logged_in"] is False
print("without a cloud login the page is told so, rather than shown nothing")

app._mw_token = lambda: "good"
cols = c.get("/api/mw/collections").get_json()["collections"]
assert [x["id"] for x in cols] == [555, 556], cols
assert cols[0]["private"] and cols[0]["count"] == 2 and cols[0]["covers"], cols[0]
assert cols[1]["title"] == "<b>Default</b>" and cols[1]["default"], "the title is the page's to escape"
print("your collections, found inside the answer wherever it keeps them:", len(cols))

r = c.get("/api/mw/collection/555").get_json()
assert r["ok"] and r["title"] == "Werkstatt" and r["total"] == 2, r
assert [h["id"] for h in r["hits"]] == [111, 112], r["hits"]
print("a private collection opens with the login")

app._mw_token = lambda: None
r = c.get("/api/mw/collection/555")
assert r.status_code == 403 and r.get_json()["error"] == "private", r.get_json()
print("...and without it the page hears 'private', not 'broken'")

app._mw_token = lambda: "expired"
r = c.get("/api/mw/collection/777").get_json()
assert r["ok"] and r["hits"][0]["id"] == 40146, r
print("an expired login does not hide a collection anyone could read")

# --- channels I follow ---------------------------------------------------------
app._mw_token = lambda: None
assert c.get("/api/mw/following").status_code == 401
assert c.get("/api/mw/browse?nav=Following").get_json()["error"] == "login"
print("without a login: no channels and no feed, and the page is told why")

app._mw_token = lambda: "good"
f = c.get("/api/mw/following").get_json()
assert f["ok"] and [x["uid"] for x in f["creators"]] == [7], f
assert f["creators"][0]["avatar"].endswith("format,webp"), "a 1 MB avatar per tile"
assert f["creators"][0]["url"] == "https://makerworld.com/@chan"
print("the channels you follow, found through your uid:", [x["name"] for x in f["creators"]])

ch = c.get("/api/mw/creator/7").get_json()
assert ch["ok"] and ch["name"] == "Chan" and ch["total"] == 1, ch
assert ch["hits"][0]["cover"].startswith("https://makerworld.bblmw.com/x.png?"), \
    "a channel's models carry coverUrl, not cover - and lost their pictures"
print("a channel's models, with their pictures")

calls.clear()
feed = c.get("/api/mw/browse?nav=Following").get_json()
assert feed["hits"][0]["id"] == 112, feed
c.get("/api/mw/browse?nav=Trending")
sent = {p.split("navKey=")[1].split("&")[0]: tok for p, tok in calls if "navKey=" in p}
assert sent == {"Following": "good", "Trending": None}, sent
print("the feed is read with the login; the shared categories are not")

# the token never reaches the page
body = "".join(c.get(u).get_data(as_text=True) for u in (
    "/api/mw/navs", "/api/mw/collection/777", "/api/mw/following",
    "/api/mw/creator/7", "/api/mw/browse?nav=Following"))
assert "expired" not in body and '"good"' not in body and "Bearer" not in body
print("the login itself is never sent to the page")
print("ok")

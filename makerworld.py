#!/usr/bin/env python3
"""
MakerWorld, read through the API the website and Bambu Handy use.

makerworld.com itself cannot be shown inside the app: it sends
`X-Frame-Options: SAMEORIGIN` and sits behind a Cloudflare challenge. The data
behind it is served by api.bambulab.com, which answers the read-only calls used
here without a login - browse, search, and a model's details and print profiles.

None of this is a documented API, so everything that leaves this module is
reduced to a small shape of our own. When Bambu changes a field, this file is
the one place that has to follow; the page never sees the raw payload.

Every call is cached. Browsing is something a person does, one page at a time,
and nothing here should turn into a crawler.

Only stdlib is used, so nothing extra has to be installed on the NAS.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.bambulab.com"
SITE = "https://makerworld.com"
UA = "bambu-monitor/1.0"

LIST_TTL = 10 * 60          # listings move; ten minutes is fresh enough
DESIGN_TTL = 24 * 3600      # a model's page rarely changes within a day
CACHE_MAX = 600             # entries, oldest dropped first

# Images on this host resize on request. The originals run to several MB each,
# and the default answer is application/octet-stream - asking for webp returns a
# proper image type as well as a file a few hundred times smaller.
_IMG_HOSTS = {"makerworld.bblmw.com", "public-cdn.bblmw.com"}   # avatars are on the second


class MWError(RuntimeError):
    pass


_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _get(path: str, ttl: int, token: str | None = None) -> dict:
    """GET one API path, cached. With `token` the call is made as the account
    the app is logged in with (the Bambu Cloud login it already has for the
    print history) and cached apart from anonymous answers."""
    now = time.time()
    key = ("auth:" if token else "") + path
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # remembered too: a model taken down since it was printed would
            # otherwise be asked for again on every look at the history
            data = {}
        elif e.code == 401:
            raise MWError("login") from None
        elif e.code == 403:
            raise MWError("private") from None
        else:
            # what MakerWorld said about it: a bare "HTTP 400" gives nothing to
            # go on when an undocumented call changes
            try:
                why = e.read().decode("utf-8", "replace")
                why = (json.loads(why).get("error") or why) if why.strip().startswith("{") else why
            except Exception:
                why = ""
            why = re.sub(r"\s+", " ", str(why)).strip()[:160]
            raise MWError(f"MakerWorld answered HTTP {e.code}"
                          + (f": {why}" if why else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MWError(f"cannot reach MakerWorld: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise MWError("MakerWorld sent something that is not JSON") from None
    with _lock:
        if len(_cache) >= CACHE_MAX:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:CACHE_MAX // 5]:
                _cache.pop(k, None)
        _cache[key] = (now + ttl, data)
    return data


def img(url: str | None, width: int = 400) -> str | None:
    """A resized, correctly typed copy of a MakerWorld image."""
    if not url or not isinstance(url, str):
        return None
    if urllib.parse.urlsplit(url).hostname not in _IMG_HOSTS or "x-oss-process" in url:
        return url
    return f"{url}?x-oss-process=image/resize,w_{int(width)}/format,webp"


def _text(raw: str | None, limit: int = 6000) -> str:
    """A description as plain text. It arrives as the author's HTML, which is
    not ours to put into the page - paragraphs and list items survive as line
    breaks, everything else is dropped."""
    if not raw:
        return ""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>", "\n", s)
    s = re.sub(r"(?i)<li\b[^>]*>", "\n• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    s = "\n".join(line.strip() for line in s.splitlines()).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def model_url(design_id, profile_id=None) -> str:
    url = f"{SITE}/models/{int(design_id)}"
    return url + (f"#profileId-{int(profile_id)}" if profile_id else "")


def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _card(h: dict) -> dict:
    c = h.get("designCreator") or {}
    return {
        "id": h.get("id"),
        "title": h.get("titleTranslated") or h.get("title") or "",
        "cover": img(h.get("cover") or h.get("coverUrl"), 400),
        "creator": c.get("name") or "",
        "likes": h.get("likeCount") or 0,
        "prints": h.get("printCount") or 0,
        "downloads": h.get("downloadCount") or 0,
        "nsfw": bool(h.get("nsfw")),
    }


# ---- listings -----------------------------------------------------------------
def navs() -> list[dict]:
    """Trending and the categories. Following / For You need an account and are
    left out rather than offered and then failing."""
    d = _get("/v1/search-service/homepage/nav", LIST_TTL * 6)
    return [{"key": n.get("key"), "name": n.get("name")}
            for n in (d.get("navs") or []) if n.get("type") == 2 and n.get("key")]


FEED_NAV = "Following"      # new models from the channels you follow; needs a login


def browse(nav: str | None = None, keyword: str | None = None,
           offset: int = 0, limit: int = 24, token: str | None = None) -> dict:
    """A page of a category, or of a search. `token` only matters for the
    Following feed - the one category that is about you - and is sent for
    nothing else, so the shared listings stay cached anonymously."""
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 48))
    q = {"offset": offset, "limit": limit}
    if keyword:
        q["keyword"] = keyword[:100]
        path = "/v1/search-service/select/design2?" + urllib.parse.urlencode(q)
    else:
        q["navKey"] = (nav or "Trending")[:80]
        path = "/v1/search-service/select/design/nav?" + urllib.parse.urlencode(q)
    feed = not keyword and nav == FEED_NAV
    d = _get(path, MINE_TTL if feed else LIST_TTL, token if feed else None)
    return {"total": d.get("total") or 0, "offset": offset,
            "hits": [_card(h) for h in (d.get("hits") or []) if h.get("id")]}


# ---- one model ----------------------------------------------------------------
def _filaments(raw) -> list[dict]:
    out = []
    for f in raw or []:
        col = str(f.get("color") or "").lstrip("#").upper()[:6]
        out.append({"type": (f.get("type") or "").strip(),
                    "color": col if re.fullmatch(r"[0-9A-F]{6}", col) else None,
                    "grams": _num(f.get("usedG")),
                    "metres": _num(f.get("usedM"))})
    return out


def _profile(i: dict, printer: str | None) -> dict:
    ext = i.get("extention") or {}
    info = ext.get("modelInfo") or {}
    native = (info.get("compatibility") or {}).get("devProductName")
    others = [o.get("devProductName") for o in (info.get("otherCompatibility") or [])]
    plates = info.get("plates") or []
    p = {
        "id": i.get("id"),
        "profile_id": i.get("profileId"),
        "title": i.get("titleTranslated") or i.get("title") or "",
        "cover": img(i.get("cover"), 480),
        "printer": native,
        "printers": [x for x in [native] + others if x],
        "weight_g": _num(i.get("weight")),
        "minutes": round(i["prediction"] / 60) if _num(i.get("prediction")) else None,
        "plates": len(plates) or None,
        "need_ams": bool(i.get("needAms")),
        "prints": i.get("printCount") or 0,
        "rating": (round(i["ratingScoreTotal"] / i["ratingCount"], 1)
                   if i.get("ratingCount") else None),
        "default": bool(i.get("isDefault")),
        "filaments": _filaments(i.get("instanceFilaments")),
        "for_printer": None,
    }
    # The author sliced for one printer; Bambu re-slices for the others. For the
    # printer in this workshop the re-sliced figures are the ones that apply.
    if printer:
        if native and native.upper() == printer.upper():
            p["for_printer"] = "native"
        else:
            for o in ext.get("otherCompatibilityModelInfo") or []:
                if (o.get("devProductName") or "").upper() == printer.upper():
                    p["for_printer"] = "adapted"
                    p["profile_id"] = o.get("profileId") or p["profile_id"]
                    p["weight_g"] = _num(o.get("weight")) or p["weight_g"]
                    if _num(o.get("prediction")):
                        p["minutes"] = round(o["prediction"] / 60)
                    if o.get("instanceFilaments"):
                        p["filaments"] = _filaments(o["instanceFilaments"])
                    break
            else:
                # listed as printable there, but without figures of its own
                if any((x or "").upper() == printer.upper() for x in others):
                    p["for_printer"] = "compatible"
    return p


def design(design_id, printer: str | None = None) -> dict:
    did = int(design_id)
    d = _get(f"/v1/design-service/design/{did}", DESIGN_TTL)
    if not d.get("id"):
        raise MWError("not found")
    ext = d.get("designExtension") or {}
    pics = []
    for p in (ext.get("design_pictures") or []) + (ext.get("real_pictures") or []):
        u = p.get("url") if isinstance(p, dict) else None
        if u and img(u, 1200) not in (x["full"] for x in pics):
            pics.append({"thumb": img(u, 160), "full": img(u, 1200)})
    if not pics and d.get("coverUrl"):
        pics.append({"thumb": img(d["coverUrl"], 160), "full": img(d["coverUrl"], 1200)})
    c = d.get("designCreator") or {}
    profiles = [_profile(i, printer) for i in (d.get("instances") or [])]
    # the printer here first, then what people actually print
    rank = {"native": 0, "adapted": 1, "compatible": 2}
    profiles.sort(key=lambda p: (rank.get(p["for_printer"], 3), -(p["prints"] or 0)))
    return {
        "id": did,
        "title": d.get("titleTranslated") or d.get("title") or "",
        "cover": img(d.get("coverUrl"), 800),
        "pictures": pics[:24],
        "summary": _text(d.get("summaryTranslated") or d.get("summary")),
        "creator": c.get("name") or "",
        "license": d.get("license") or "",
        "tags": [t for t in (d.get("tagsTranslated") or d.get("tags") or [])
                 if isinstance(t, str)][:20],
        "categories": [x.get("name") for x in (d.get("categories") or []) if x.get("name")],
        "likes": d.get("likeCount") or 0,
        "prints": d.get("printCount") or 0,
        "downloads": d.get("downloadCount") or 0,
        "collections": d.get("collectionCount") or 0,
        "nsfw": bool(d.get("nsfw")),
        "url": model_url(did),
        "profiles": profiles,
    }


def brief(design_id) -> dict | None:
    """Title and cover for one model, for the print history. Never raises: a
    history row without a picture is fine, a history that fails to load is not."""
    try:
        did = int(design_id)
        d = _get(f"/v1/design-service/design/{did}", DESIGN_TTL)
    except (MWError, TypeError, ValueError):
        return None
    if not d.get("id"):
        return None
    return {"id": did, "title": d.get("titleTranslated") or d.get("title") or "",
            "cover": img(d.get("coverUrl"), 160),
            "creator": (d.get("designCreator") or {}).get("name") or ""}


# ---- collections --------------------------------------------------------------
MINE_TTL = 2 * 60           # your own list: a model saved on the phone shows soon


def _collection_card(c: dict) -> dict:
    covers = [img(u, 240) for u in (c.get("designCover") or []) if isinstance(u, str)]
    if not covers and c.get("cover"):
        covers = [img(c["cover"], 240)]
    return {"id": c.get("id"),
            "title": c.get("titleTranslated") or c.get("title") or c.get("name") or "",
            "count": c.get("designCnt") if c.get("designCnt") is not None else c.get("count"),
            "covers": covers[:4],
            "default": bool(c.get("isDefault")),
            "private": c.get("status") not in (None, 2)}


def _find_collections(d) -> list[dict]:
    """The list of your collections, wherever the answer keeps it. Its shape is
    not documented, so this looks for the first list of objects that carry an
    id and a title rather than trusting one key name."""
    if isinstance(d, list):
        if d and all(isinstance(x, dict) and x.get("id") is not None
                     and (x.get("title") or x.get("name")) for x in d):
            return d
        for x in d:
            got = _find_collections(x)
            if got:
                return got
    elif isinstance(d, dict):
        for k in ("favorites", "list", "hits", "data", "collections", "items"):
            if k in d:
                got = _find_collections(d[k])
                if got:
                    return got
        for v in d.values():
            if isinstance(v, (list, dict)):
                got = _find_collections(v)
                if got:
                    return got
    return []


# Where the account's collections are listed. Found by what the API admits to
# (a login-only 401 rather than a 404), not from any documentation - so the
# answer is read for either shape it could plausibly have: the collections
# themselves, or only their ids. `my/design/favoriteslist` is NOT it: that one
# answers which of your collections hold one given model.
MINE_PATHS = ("/v1/design-service/my/favorites/listlite",)
MINE_MAX = 60               # collections looked up one by one, at most


def _find_ids(d) -> list[int]:
    """A list of bare ids - numbers, or objects that carry nothing but an id."""
    if isinstance(d, list):
        if d and all(isinstance(x, int) and not isinstance(x, bool) for x in d):
            return list(d)
        if d and all(isinstance(x, dict) and isinstance(x.get("id"), int) for x in d):
            return [x["id"] for x in d]
        return []
    if isinstance(d, dict):
        for k in ("favoritesIds", "ids", "list", "hits", "data", "favorites", "items"):
            if k in d:
                got = _find_ids(d[k])
                if got:
                    return got
    return []


def _resolve(ids: list[int], token: str) -> list[dict]:
    """Collections known only by id, looked up in parallel. An id that does not
    open as a collection is dropped rather than shown as an empty tile."""
    from concurrent.futures import ThreadPoolExecutor

    def one(i):
        try:
            h = _get(f"/v1/design-service/favorites/{int(i)}", MINE_TTL, token)
        except (MWError, ValueError):
            return None
        return h if h.get("id") and (h.get("title") or h.get("name")) else None

    with ThreadPoolExecutor(max_workers=6) as pool:
        heads = list(pool.map(one, ids[:MINE_MAX]))
    return [h for h in heads if h]


def _empty_list(d, depth: int = 0) -> bool:
    """An answer that holds a list, and the list is empty: no collections, as
    opposed to an answer this module does not understand."""
    if isinstance(d, list):
        return not d
    if isinstance(d, dict) and depth < 3:
        return any(_empty_list(v, depth + 1) for v in d.values())
    return False


def my_collections(token: str) -> list[dict]:
    """The collections of the logged-in account."""
    err, answers = None, []
    for path in MINE_PATHS:
        try:
            d = _get(path, MINE_TTL, token)
        except MWError as e:
            if str(e) == "login":
                raise                 # the login is the problem, not the path
            err = e
            continue
        found = _find_collections(d)
        if not found:
            ids = _find_ids(d)
            found = _resolve(ids, token) if ids else []
        if found:
            return [_collection_card(c) for c in found]
        answers.append(d)
    if any(_empty_list(d) for d in answers):
        return []
    if answers:
        raise MWError("answer not understood - tools/why_no_collections.py --json shows it")
    raise err


def collection(cid, token: str | None = None, offset: int = 0, limit: int = 24) -> dict:
    """One collection and a page of its models. Public ones need no login; your
    private ones are read as you."""
    cid = int(cid)
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 48))
    head = _get(f"/v1/design-service/favorites/{cid}", LIST_TTL, token)
    if not head.get("id"):
        raise MWError("not found")
    q = urllib.parse.urlencode({"offset": offset, "limit": limit})
    page = _get(f"/v1/design-service/favorites/{cid}/designs?{q}", LIST_TTL, token)
    card = _collection_card(head)
    return {**card, "creator": (head.get("creator") or {}).get("name") or "",
            "total": page.get("total") or 0, "offset": offset,
            "hits": [_card(h) for h in (page.get("hits") or []) if h.get("id")]}


def collection_id(text: str) -> int | None:
    """A collection's number from its link or from the number itself -
    makerworld.com/en/collections/35678497-home-prints, or just 35678497."""
    m = re.search(r"collections/(\d+)", text or "") or re.fullmatch(r"\s*(\d{3,})\s*", text or "")
    return int(m.group(1)) if m else None


# ---- channels you follow ---------------------------------------------------------
# Who someone follows is public (`user/<uid>/follows`, as MakerWorld's profile
# pages show it), and so are a creator's published models. Only which uid is
# yours needs the login.
MY_PROFILE_PATHS = ("/v1/design-user-service/my/profile",
                    "/v1/user-service/my/profile")


def _uid_of(d) -> int | None:
    """The account's uid from a profile answer, wherever it keeps it."""
    if isinstance(d, dict):
        for k in ("uid", "uidStr", "userId", "user_id"):
            v = d.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        for k in ("data", "user", "profile", "account"):
            got = _uid_of(d.get(k))
            if got:
                return got
    return None


def my_uid(token: str) -> int:
    err = None
    for path in MY_PROFILE_PATHS:
        try:
            uid = _uid_of(_get(path, 3600, token))
        except MWError as e:
            if str(e) == "login":
                raise
            err = e
            continue
        if uid:
            return uid
    raise err or MWError("answer not understood - no uid in the profile")


def _avatar(u: str | None) -> str | None:
    return img(u, 160) if u else None


def _creator(u: dict) -> dict:
    return {"uid": u.get("uid"), "name": u.get("name") or u.get("handle") or "",
            "handle": u.get("handle") or "", "avatar": _avatar(u.get("avatar")),
            "fans": u.get("fanCount") or 0,
            "url": f"{SITE}/@{urllib.parse.quote(u['handle'])}" if u.get("handle") else None}


def following(uid, offset: int = 0, limit: int = 48) -> dict:
    """The channels `uid` follows."""
    q = urllib.parse.urlencode({"offset": max(0, int(offset)),
                                "limit": max(1, min(int(limit), 48))})
    d = _get(f"/v1/design-user-service/user/{int(uid)}/follows?{q}", MINE_TTL)
    return {"total": d.get("total") or 0,
            "creators": [_creator(u) for u in (d.get("hits") or []) if u.get("uid")]}


def creator(uid, offset: int = 0, limit: int = 24) -> dict:
    """One channel and a page of its models, newest first."""
    uid = int(uid)
    head = _get(f"/v1/design-user-service/user/profile/{uid}", DESIGN_TTL)
    if not head.get("uid"):
        raise MWError("not found")
    q = urllib.parse.urlencode({"offset": max(0, int(offset)),
                                "limit": max(1, min(int(limit), 48))})
    page = _get(f"/v1/design-service/published/{uid}/design?{q}", LIST_TTL)
    return {**_creator(head), "total": page.get("total") or 0,
            "offset": int(offset),
            "hits": [_card(h) for h in (page.get("hits") or []) if h.get("id")]}


def forget_mine() -> None:
    """Drop the cached list of your own collections, e.g. after a new login."""
    with _lock:
        for k in [k for k in _cache if k.startswith("auth:")]:
            _cache.pop(k, None)


def cached(design_id) -> bool:
    with _lock:
        hit = _cache.get(f"/v1/design-service/design/{int(design_id)}")
        return bool(hit and hit[0] > time.time())


if __name__ == "__main__":
    # offline self-test: the parts that do not need the network
    assert img("https://makerworld.bblmw.com/a/b.jpg", 200) == \
        "https://makerworld.bblmw.com/a/b.jpg?x-oss-process=image/resize,w_200/format,webp"
    assert img("https://evil.example/a.jpg") == "https://evil.example/a.jpg"
    assert img(None) is None
    assert img("https://public-cdn.bblmw.com/avatar/1/a.jpeg", 160).endswith("w_160/format,webp")
    assert _uid_of({"data": {"uid": "123"}}) == 123 and _uid_of({"uid": 5}) == 5
    assert _uid_of({"uid": True}) is None and _uid_of({}) is None
    cr = _creator({"uid": 9, "name": "A b", "handle": "a b", "fanCount": 3})
    assert cr["url"] == "https://makerworld.com/@a%20b" and cr["fans"] == 3, cr
    t = _text("<p>Hi&nbsp;there</p><ul><li>one</li><li>two</li></ul>"
              "<script>alert(1)</script><img src=x onerror=alert(1)>")
    assert "<" not in t and "alert" not in t, t
    assert t == "Hi there\n\n• one\n• two", repr(t)
    f = _filaments([{"type": "PLA", "color": "#ff8000", "usedG": "4", "usedM": "1.2"},
                    {"type": "PETG", "color": "junk"}])
    assert f[0] == {"type": "PLA", "color": "FF8000", "grams": 4.0, "metres": 1.2}, f
    assert f[1]["color"] is None
    assert model_url(12, 34) == "https://makerworld.com/models/12#profileId-34"
    assert collection_id("https://makerworld.com/en/collections/35678497-home-prints") == 35678497
    assert collection_id("35678497") == 35678497 and collection_id("hello") is None
    found = _find_collections({"code": 0, "data": {"list": [
        {"id": 1, "title": "Home", "designCnt": 3, "designCover": ["https://makerworld.bblmw.com/a.png"]},
        {"id": 2, "title": "Toys", "designCnt": 0, "isDefault": True}]}})
    assert [c["id"] for c in found] == [1, 2], found
    card = _collection_card(found[0])
    assert card["count"] == 3 and card["covers"][0].endswith("w_240/format,webp"), card
    assert _find_collections({"hits": [{"id": 5}]}) == [], "a list without titles is not it"
    assert _empty_list({"code": 0, "data": {"list": []}}) and not _empty_list({"ids": [1, 2]})

    # the list may carry the collections themselves, or only their ids
    _real_get = _get
    assert _find_ids({"list": [3, 4]}) == [3, 4] and _find_ids({"data": [{"id": 7}]}) == [7]
    assert _find_ids({"favoritesIds": None}) == [] and _find_ids([True]) == []
    try:
        _get = lambda p, t, token=None: {"list": [{"id": 9, "title": "Mine"}]}  # noqa: E731
        assert [c["id"] for c in my_collections("t")] == [9]

        def _ids(path, ttl, token=None):
            if path.endswith("listlite"):
                return {"list": [11, 12, 13]}
            if path.endswith("/12"):
                raise MWError("private")                 # not one it can open
            if path.endswith("/13"):
                return {}                                # a 404, i.e. not a collection
            return {"id": 11, "title": "Found by id", "designCnt": 4}
        _get = _ids
        got = my_collections("t")
        assert [(c["id"], c["title"], c["count"]) for c in got] == [(11, "Found by id", 4)], got

        # ids that are not collections (e.g. of models) must not pass as "none"
        _get = lambda p, t, token=None: {"list": [1, 2]} if p.endswith("listlite") else {}  # noqa: E731
        try:
            my_collections("t")
            raise AssertionError("an answer it cannot read passed as 'no collections'")
        except MWError as e:
            assert "not understood" in str(e), e
        _get = lambda p, t, token=None: {"designId": 1, "favoritesIds": None}  # noqa: E731
        try:
            my_collections("t")
            raise AssertionError("favoriteslist's shape passed as 'no collections'")
        except MWError as e:
            assert "not understood" in str(e), e
        _get = lambda p, t, token=None: {"data": {"list": []}}   # noqa: E731
        assert my_collections("t") == []

        def _nologin(path, ttl, token=None):
            raise MWError("login")
        _get = _nologin
        try:
            my_collections("t")
            raise AssertionError("an expired login was hidden behind the next path")
        except MWError as e:
            assert str(e) == "login"
    finally:
        _get = _real_get
    print("makerworld.py self-test ok")

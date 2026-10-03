#!/usr/bin/env python3
"""Read-only: why "My collections" on the MakerWorld tab is empty, or wrong.

The list of your collections comes from an undocumented call, read with the
Bambu Cloud login the app already has. This makes each form of that call the
app tries (makerworld.MINE_PATHS) and says what came back: the HTTP status,
MakerWorld's own words when it refuses, and what the app made of it - the
collections themselves, or ids it then looked up one by one. A few related
calls are shown too, as field names only, so nothing personal is printed. It
writes nothing, and it never prints the token.

    ./venv/bin/python3 tools/why_no_collections.py [--json]

Run it with the app's own Python (the venv): the system one lacks the
database driver. --json also prints each raw answer of the list call,
shortened - the thing to send along if the app reads it wrong.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import config_store  # noqa: E402
import makerworld    # noqa: E402

try:
    store, cfg = config_store.open_live()
except ModuleNotFoundError as e:
    print(f"{e} - this is not the app's Python. Run it with the venv's, from the "
          f"app folder:\n\n    ./venv/bin/python3 tools/{os.path.basename(__file__)} "
          + " ".join(sys.argv[1:]))
    sys.exit(1)
token = cfg.section("cloud").get("token")
if not token:
    print("No Bambu Cloud login is stored (Settings > Cloud, or tools/setup_cloud.py).")
    print("Without one only collections opened by their link can be shown.")
    sys.exit(1)

show_json = "--json" in sys.argv


def call(path):
    req = urllib.request.Request(makerworld.API + path, headers={
        "User-Agent": makerworld.UA, "Accept": "application/json",
        "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, raw = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        print(f"  cannot reach {makerworld.API}: {e.reason}")
        sys.exit(2)
    try:
        return status, json.loads(raw or "{}")
    except ValueError:
        return status, raw


def shape(d, depth=0):
    """Field names and types, no values - safe to paste anywhere."""
    if isinstance(d, dict):
        if depth >= 2:
            return "{...}"
        return {k: shape(v, depth + 1) for k, v in list(d.items())[:25]}
    if isinstance(d, list):
        return [f"{len(d)} x", shape(d[0], depth + 1)] if d else []
    return type(d).__name__


first_found = None
for path in makerworld.MINE_PATHS:
    print(f"\nGET {path}")
    status, data = call(path)
    print(f"  HTTP {status}")
    if status in (401, 403):
        print("  the stored login is not accepted - sign in again under "
              "Settings > Cloud (or tools/setup_cloud.py)")
    if not isinstance(data, (dict, list)):
        print("  not JSON:", str(data)[:300])
        continue
    if status != 200:
        print("  MakerWorld says:", json.dumps(data, ensure_ascii=False)[:300])
        continue
    print("  shape:", json.dumps(shape(data), ensure_ascii=False)[:600])
    found = makerworld._find_collections(data)
    how = "listed with their names"
    if not found:
        ids = makerworld._find_ids(data)
        if ids:
            print(f"  {len(ids)} bare id(s), looking each up as a collection…")
            found = makerworld._resolve(ids, token)
            how = f"looked up by id ({len(found)} of {len(ids)} opened)"
    if found:
        print(f"  {len(found)} collection(s), {how}:")
        for c in found:
            card = makerworld._collection_card(c)
            print(f"    {str(card['id']):<12} {card['title'][:40]:<40} "
                  f"{'' if card['count'] is None else str(card['count']) + ' models':<12}"
                  f"{'private' if card['private'] else 'public'}"
                  f"{'  (default)' if card['default'] else ''}")
        first_found = first_found or found[0].get("id")
    elif makerworld._empty_list(data):
        print("  an empty list: the account has no collections")
    else:
        print("  no collections recognised in it")
    if show_json:
        print("  raw answer:")
        print("  " + json.dumps(data, indent=2, ensure_ascii=False)[:3000].replace("\n", "\n  "))

# related calls: what else the account side offers, as field names only
print("\nrelated calls (field names only):")
for path in ("/v1/design-service/my/favorites/count",
             "/v1/design-service/my/profile",
             "/v1/design-user-service/my/profile"):
    status, data = call(path)
    print(f"  GET {path}\n    HTTP {status}  "
          + json.dumps(shape(data) if isinstance(data, (dict, list)) else str(data)[:80],
                       ensure_ascii=False)[:500])

# "Channels I follow": your uid from the profile, then the public list
print("\nchannels you follow:")
try:
    uid = makerworld.my_uid(token)
    fol = makerworld.following(uid)
    print(f"  your account was found; {fol['total']} channel(s) followed"
          + (": " + ", ".join(c["name"] for c in fol["creators"][:8]) if fol["creators"] else ""))
    feed = makerworld.browse(nav=makerworld.FEED_NAV, token=token)
    print(f"  the feed of new models from them has {feed['total']} model(s)")
except makerworld.MWError as e:
    print(f"  FAILED: {e}")

if first_found:
    try:
        col = makerworld.collection(first_found, token, 0, 3)
        print(f"\nopening collection {first_found} works: {col['total']} model(s), e.g. "
              + ", ".join(h["title"][:30] for h in col["hits"]))
    except makerworld.MWError as e:
        print(f"\nopening collection {first_found} FAILED: {e}")
else:
    print("\nnothing usable yet. Send this output along (with --json) - the "
          "reader needs to learn this shape.")

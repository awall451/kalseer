"""Validated, backed-up, atomic edits to $DATA/watchlist.json. Stdlib only.

The watchlist is the judgment step's only memory, and every run edited it
with a fresh one-off script ending in json.dump(w, open(P, 'w')), which
truncates the file if anything fails mid-dump. This applies a JSON patch
all-or-nothing instead.

  python3 kalshi/watchlist.py show [ID]       # id, window, title (or one item)
  python3 kalshi/watchlist.py apply PATCH     # e.g. $DATA/watchlist-patch.json

PATCH is a JSON object with any of:
  "update": {"<id>": {"title": ..., "append": "text added to thesis",
                      "notes": ..., "market": ..., "check_from": ...,
                      "expires": ..., "thesis": "full replacement"}}
  "add":    [{"id", "title", "check_from", "expires", "thesis", ...}]
  "remove": ["<id>", ...]
Nothing is written unless every id, field and date checks out. A "thesis"
replacement shorter than the current one also needs "shrink": true (the
journal must never lose history by accident). The first apply of the day
snapshots the untouched file to watchlist-bak-MMDD.json; the write goes
through a temp file and os.replace, so the old file survives any failure.
"""

import datetime as dt
import json
import os
import pathlib
import sys

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
FIELDS = {"title", "append", "notes", "market", "check_from", "expires",
          "thesis", "shrink"}
REQUIRED = ("id", "title", "check_from", "expires", "thesis")


def _today() -> str:
    return dt.date.today().isoformat()


def _fail(msg: str):
    print(f"watchlist: {msg}", file=sys.stderr)
    sys.exit(2)


def _path() -> pathlib.Path:
    return DATA / "watchlist.json"


def _load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        _fail(f"cannot read {path}: {e}")


def _date(value, where: str):
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail(f"{where}: {value!r} is not YYYY-MM-DD")


def apply(patch: dict, wl: dict) -> list[str]:
    """Apply patch to wl in place, or exit before touching anything."""
    if not isinstance(patch, dict) or set(patch) - {"update", "add", "remove"}:
        _fail("patch must be an object with update/add/remove only")
    by_id = {i["id"]: i for i in wl["items"]}
    update, add = patch.get("update") or {}, patch.get("add") or []
    remove = patch.get("remove") or []
    unknown = [i for i in list(update) + list(remove) if i not in by_id]
    if unknown:
        _fail(f"unknown id(s): {' '.join(unknown)} "
              f"(have: {' '.join(by_id)})")
    for id_, changes in update.items():
        bad = set(changes) - FIELDS
        if bad:
            _fail(f"{id_}: unknown field(s) {' '.join(sorted(bad))}")
        for key in ("check_from", "expires"):
            if key in changes:
                _date(changes[key], f"{id_}.{key}")
        if ("thesis" in changes and not changes.get("shrink")
                and len(changes["thesis"]) < len(by_id[id_]["thesis"])):
            _fail(f"{id_}: replacement thesis is shorter "
                  f"({len(changes['thesis'])} < {len(by_id[id_]['thesis'])} "
                  "chars); add \"shrink\": true if that is intended")
    new_ids = set()
    for it in add:
        missing = [k for k in REQUIRED if not it.get(k)]
        if missing:
            _fail(f"added item {it.get('id')!r} lacks {' '.join(missing)}")
        if it["id"] in by_id or it["id"] in new_ids:
            _fail(f"added item {it['id']!r} already exists")
        new_ids.add(it["id"])
        for key in ("check_from", "expires"):
            _date(it[key], f"{it['id']}.{key}")

    done = []
    for id_, changes in update.items():
        it = by_id[id_]
        for key, value in changes.items():
            if key == "append":
                sep = "" if not it["thesis"] or it["thesis"].endswith(" ") else " "
                it["thesis"] += sep + value
            elif key != "shrink":
                it[key] = value
        done.append(f"updated {id_}")
    wl["items"] = [i for i in wl["items"] if i["id"] not in remove]
    done += [f"removed {i}" for i in remove]
    wl["items"].extend(add)
    done += [f"added {i['id']}" for i in add]
    return done


def _write(path: pathlib.Path, wl: dict):
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(wl, f, indent=1)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv: list[str]):
    path = _path()
    if argv[:1] == ["show"] and len(argv) <= 2:
        wl = _load(path)
        if len(argv) == 2:
            match = [i for i in wl["items"] if i["id"] == argv[1]]
            if not match:
                _fail(f"no item {argv[1]!r}")
            print(json.dumps(match[0], indent=1))
            return
        for i in wl["items"]:
            print(f"{i['id']}  {i.get('check_from')}..{i.get('expires')}  "
                  f"{len(i.get('thesis', ''))}ch  {i.get('title')}")
        return
    if argv[:1] == ["apply"] and len(argv) == 2:
        wl = _load(path)
        patch = _load(pathlib.Path(argv[1]))
        done = apply(patch, wl)
        backup = DATA / f"watchlist-bak-{_today()[5:7]}{_today()[8:10]}.json"
        if not backup.exists():
            backup.write_text(path.read_text())
        _write(path, wl)
        print(f"watchlist: {'; '.join(done) or 'no changes'}; "
              f"{len(wl['items'])} items; backup {backup.name}")
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

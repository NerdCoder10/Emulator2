"""Export recorded battles to a self-contained HTML replay viewer ("Battle Theater")."""
import json
import os

KIND_CODE = {"troop": 0, "building": 1, "tower": 2}
VIEWER = os.path.join(os.path.dirname(__file__), "viewer.html")


def pack_game(frames, meta):
    """Compress a battle's recorded frames into the viewer's compact format."""
    names, index = [], {}

    def nid(name):
        if name not in index:
            index[name] = len(names)
            names.append(name)
        return index[name]

    out, plays, spells = [], [], []
    t = 0.0
    for f in frames:
        if "play" in f:
            p, card, x, y, pt = f["play"]
            plays.append([p, card, x, y, pt])
        elif "spell" in f:
            name, x, y, r, p = f["spell"]
            spells.append([t, name, x, y, r, p])
        else:
            t = f["t"]
            ents = [[nid(n), o, round(x, 1), round(y, 1), round(hp, 2), air,
                     KIND_CODE[k], eid] for n, o, x, y, hp, air, k, eid in f["e"]]
            out.append([t, f["elixir"][0], f["elixir"][1], f["crowns"][0],
                        f["crowns"][1], ents])
    return {"meta": meta, "names": names, "frames": out, "plays": plays, "spells": spells}


def export_games(games, path):
    """games: list of (frames, meta) pairs. meta keys are shown in the viewer."""
    data = [pack_game(fr, meta) for fr, meta in games]
    with open(VIEWER) as f:
        html = f.read()
    html = html.replace("/*__GAMES__*/[]", json.dumps(data, separators=(",", ":")))
    with open(path, "w") as f:
        f.write(html)


def export_html(frames, path, title="Battle Replay", meta=None):
    meta = dict(meta or {})
    meta.setdefault("title", title)
    export_games([(frames, meta)], path)

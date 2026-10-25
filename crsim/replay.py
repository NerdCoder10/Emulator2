"""Export a recorded battle to a self-contained HTML replay viewer."""
import json

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Battle Replay</title>
<style>
 body{background:#1d2330;color:#eee;font-family:system-ui,sans-serif;display:flex;
      flex-direction:column;align-items:center;margin:16px}
 canvas{background:#5d9c4a;border-radius:8px;max-width:100%}
 #bar{margin:8px;display:flex;gap:12px;align-items:center}
</style></head><body>
<h3>__TITLE__</h3>
<div id="bar"><button id="play">Pause</button><input id="seek" type="range" min="0" value="0">
<span id="info"></span></div>
<canvas id="c" width="360" height="640"></canvas>
<script>
const F = __FRAMES__;
const frames = F.filter(f => f.e), spells = [];
const S = 20, c = document.getElementById('c'), g = c.getContext('2d');
const seek = document.getElementById('seek'); seek.max = frames.length - 1;
let i = 0, playing = true;
// spells are interleaved with frames; attach each to the next frame index
let fi = 0; F.forEach(f => { if (f.e) fi++; else spells.push([fi, f.spell]); });
function draw() {
  const f = frames[i]; g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = '#3b7fc4'; g.fillRect(0, 15*S, 18*S, 2*S);
  g.fillStyle = '#8b6b3d'; [3.5, 14.5].forEach(x => g.fillRect((x-1)*S, 15*S, 2*S, 2*S));
  spells.filter(s => s[0] >= i - 2 && s[0] <= i).forEach(([_, s]) => {
    g.fillStyle = s[4] ? 'rgba(255,80,80,.35)' : 'rgba(80,160,255,.35)';
    g.beginPath(); g.arc(s[1]*S, (32-s[2])*S, s[3]*S, 0, 7); g.fill();
  });
  f.e.forEach(([name, owner, x, y, hp, air, kind]) => {
    const px = x*S, py = (32-y)*S;
    const r = kind === 'tower' ? (name.startsWith('king') ? 2 : 1.5)*S : kind === 'building' ? S : 0.45*S;
    g.fillStyle = owner ? '#d9443b' : '#2f6fd6';
    if (kind === 'tower' || kind === 'building') g.fillRect(px-r, py-r, 2*r, 2*r);
    else { g.beginPath(); g.arc(px, py, r, 0, 7); g.fill(); if (air) { g.strokeStyle='#fff'; g.stroke(); } }
    g.fillStyle = '#111'; g.fillRect(px-r, py-r-5, 2*r, 3);
    g.fillStyle = '#4f4'; g.fillRect(px-r, py-r-5, 2*r*hp, 3);
    if (kind !== 'tower') { g.fillStyle = '#fff'; g.font = '9px sans-serif';
      g.fillText(name.split(' ')[0].slice(0,6), px-r, py+r+9); }
  });
  document.getElementById('info').textContent =
    `t=${f.t.toFixed(1)}s  crowns blue ${f.crowns[0]} - ${f.crowns[1]} red  ` +
    `elixir ${f.elixir[0].toFixed(1)} / ${f.elixir[1].toFixed(1)}`;
  seek.value = i;
}
seek.oninput = () => { i = +seek.value; draw(); };
document.getElementById('play').onclick = e => {
  playing = !playing; e.target.textContent = playing ? 'Pause' : 'Play'; };
setInterval(() => { if (playing && i < frames.length - 1) { i++; draw(); } }, 50);
draw();
</script></body></html>"""


def export_html(frames, path, title="Battle Replay"):
    html = TEMPLATE.replace("__FRAMES__", json.dumps(frames, separators=(",", ":")))
    html = html.replace("__TITLE__", title)
    with open(path, "w") as f:
        f.write(html)

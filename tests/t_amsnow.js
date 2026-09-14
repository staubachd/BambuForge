// "Loaded now" on the Filament page: what is physically in the machine.
//
// The card is rendered by the SAME spoolCard() the live AMS panel uses - the
// point of lifting it out was that two copies would be two places for a colour,
// a remaining weight or a reorder link to go stale. So this checks the shared
// card and the Filament page's own assembly of it, against the real source.
//
// The part that has actual logic is the numbering: a tray's id restarts at 0 in
// every AMS unit, while the printer's "loaded" pointer counts across them. Get
// that wrong and the highlight sits on the wrong spool - which looks like the
// printer lying about what it is printing with.
const path = require("path");
const SRC_DIR = process.env.BAMBU_SRC || path.join(__dirname, "..");
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(path.join(SRC_DIR, "dashboard.html"), "utf8");
const src = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const lines = src.split("\n");
function grab(sig) {
  const s = lines.findIndex(l => l.startsWith(sig));
  if (s < 0) throw new Error("not found: " + sig);
  let e = s; while (lines[e] !== "}") e++;
  return lines.slice(s, e + 1).join("\n");
}

const els = {};
const $ = id => (els[id] = els[id] || {id, style: {}, innerHTML: "", textContent: ""});
const ctx = {
  $, lastState: null,
  t: s => s,
  esc: s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  kgF: g => (Math.abs(g) >= 1000 ? (g / 1000).toFixed(2) + " kg" : Math.round(g) + " g"),
};
vm.createContext(ctx);
for (const fn of ["function spoolCard(", "function renderAmsNow("])
  vm.runInContext(grab(fn), ctx);

const tray = (id, o = {}) => ({id, type: "PLA", color: "AA0000", remain_pct: 80,
                               grams_left: 800, is_bambu: true, ...o});
function paint(ams) {
  ctx.lastState = ams === null ? null : {ams};
  vm.runInContext("renderAmsNow()", ctx);
  return {html: $("amsNow").innerHTML, meta: $("amsNowMeta").textContent,
          shown: $("amsNowCard").style.display !== "none"};
}
const badges = h => (h.match(/slot-badge">([^<]*)</g) || []).map(m => m.replace(/.*">|<$/g, ""));
// `spool-type`, `spool-brand` and `spool-tags` all start with the same prefix,
// so a card boundary is the class plus its space
const cards = h => h.split('<div class="spool ').slice(1);
const activeAt = h => cards(h).findIndex(c => c.startsWith("active"));

// --- one AMS plus the external holder: four slots and a fifth spool ---------
let r = paint({units: [{trays: [0, 1, 2, 3].map(i => tray(i)), humidity_pct: 22}],
               external: [{id: 254, type: "PETG", color: "1B1B1B"}],
               active_tray: 2, can_assign: true});
if (!r.shown) throw new Error("the card hid itself with a full AMS");
if (badges(r.html).join(",") !== "1,2,3,4,EXT")
  throw new Error("wrong slots: " + badges(r.html).join(","));
console.log("four AMS slots plus the external holder:", badges(r.html).join(" "));

// the printer's loaded slot is the one highlighted, and only that one
if ((r.html.match(/class="spool active/g) || []).length !== 1)
  throw new Error("expected exactly one highlighted spool");
if (activeAt(r.html) !== 2)
  throw new Error(`the highlight sits on card ${activeAt(r.html)}, not the third`);
if ((r.html.match(/>Loaded</g) || []).length !== 1)
  throw new Error('exactly one spool may carry the "Loaded" tag');
console.log("the loaded slot is the one the printer says, and only it");

if (!/22%/.test(r.meta)) throw new Error("humidity is not reported: " + r.meta);
if (!/5 of 5 slots loaded/.test(r.meta)) throw new Error("miscounted: " + r.meta);
console.log("meta:", r.meta);

// --- an empty slot is a slot, not a spool ----------------------------------
r = paint({units: [{trays: [tray(0), {id: 1}, tray(2), tray(3)]}], external: [],
           active_tray: 0});
if (!/3 of 4 slots loaded/.test(r.meta))
  throw new Error("an empty tray was counted as loaded: " + r.meta);
if (!/Empty/.test(r.html)) throw new Error("the empty slot is not labelled");
if (/undefined|NaN|null/.test(r.html))
  throw new Error("an empty slot rendered rubbish: " + r.html.slice(0, 240));
console.log("an empty slot counts as a slot and shows as Empty");

// --- two AMS units: the ids restart, the loaded pointer does not ------------
r = paint({units: [{trays: [0, 1, 2, 3].map(i => tray(i))},
                   {trays: [0, 1, 2, 3].map(i => tray(i))}],
           external: [], active_tray: 5});
if (badges(r.html).join(",") !== "A1,A2,A3,A4,B1,B2,B3,B4")
  throw new Error("a second AMS is not labelled apart: " + badges(r.html).join(","));
if (activeAt(r.html) !== 5)
  throw new Error("tray 5 is slot 2 of the SECOND unit; the highlight landed on "
                  + `card ${activeAt(r.html)} - the units were not counted across`);
console.log("two units label apart and the loaded pointer counts across them");

// --- two external holders, one per nozzle ----------------------------------
r = paint({units: [{trays: [tray(0)]}],
           external: [{id: 254, type: "PLA"}, {id: 255, type: "PETG"}]});
if (badges(r.html).join(",") !== "1,EXT1,EXT2")
  throw new Error("a second nozzle's spool is not distinguishable: " + badges(r.html));
console.log("a second external holder is numbered, not doubled");

// --- nothing to show, no card ----------------------------------------------
if (paint({}).shown) throw new Error("the card stayed up with no AMS at all");
if (paint(null).shown) throw new Error("the card stayed up before the first frame");
console.log("no AMS reported: the card hides instead of showing an empty box");

// --- assigning is offered where it makes sense, and nowhere else ------------
r = paint({units: [{trays: [tray(0)]}], external: [{id: 254, type: "PLA"}],
           can_assign: true});
if ((r.html.match(/assign-btn/g) || []).length !== 1)
  throw new Error("the external holder was offered an assign button - the "
                  + "printer has no slot to assign it to");
if (!/data-slot="1"/.test(r.html)) throw new Error("the assign button names the wrong slot");
r = paint({units: [{trays: [tray(0)]}], external: [], can_assign: false});
if (/assign-btn/.test(r.html))
  throw new Error("assigning was offered although the setting is off");
console.log("assign is offered for real slots only, and only when switched on");

// --- hostile spool data stays data -----------------------------------------
r = paint({units: [{trays: [tray(0, {type: '"><script>alert(1)</script>'})]}], external: []});
if (/<script>alert/.test(r.html))
  throw new Error("a spool's type broke out of the markup");
console.log("a hostile spool name is escaped, not executed");

// --- and the live panel still renders through the same function ------------
if (!/\$\("spools"\)\.innerHTML = all\.map\(tr=>\s*\n?\s*spoolCard\(/.test(src))
  throw new Error("the live AMS panel no longer uses spoolCard() - the two "
                  + "panels have been forked apart again");
console.log("the live panel and the Filament page render the same card");
console.log("ok");

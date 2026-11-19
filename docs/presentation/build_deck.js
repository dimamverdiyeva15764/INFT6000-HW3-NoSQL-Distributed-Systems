// Group 4 slide deck, assembled by Habib Hasanov from every member's material.
//   node docs/presentation/build_deck.js        (needs pptxgenjs and python3; or: make deck)
// Numbers on the chart slides are read from results/summary/*.csv (make figures, make exp2-report),
// never typed in. Each presenter owns the content of their slides: edit the SLIDES below or the
// .pptx directly, and keep the speaker notes in sync with docs/presentation/*_talk.md.
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const P = (...p) => path.join(ROOT, ...p);
const OUT = P("docs", "presentation", "group4_deck.pptx");

function splitCsv(line) {             // RFC 4180 fields, quotes allowed
  const out = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q && ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
    else if (ch === '"') q = !q;
    else if (ch === "," && !q) { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}
function csv(file) {
  const [head, ...rows] = fs.readFileSync(file, "utf8").trim().split(/\r?\n/);
  const cols = splitCsv(head);
  return rows.map((r) => Object.fromEntries(splitCsv(r).map((v, i) => [cols[i], v])));
}
const imgSize = (file) => {           // PNG width/height from the IHDR chunk
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
};

const THEME = {
  name: "Group 4 Cassandra",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "14213D", lt1: "FFFFFF", dk2: "3D4A63", lt2: "EEF1F6",
    accent1: "FCA311", accent2: "2A78D6", accent3: "EB6834", accent4: "1BAF7A",
    accent5: "6250D6", accent6: "8A93A6", hlink: "2A78D6", folHlink: "6250D6",
  },
};
const HEX = THEME.colors;
const CL = { ONE: "2A78D6", QUORUM: "EB6834", ALL: "1BAF7A" };

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";              // 10 x 5.625 in
pres.author = "Group 4";
pres.title = "INFT 6000 HW3 - Apache Cassandra";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ------------------------------------------------------------------ layouts
pres.defineSlideMaster({
  title: "DARK_TITLE",
  background: { color: HEX.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.35, w: 8.8, h: 1.4,
        fontSize: 40, bold: true, color: C.background1, valign: "bottom" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 2.9, w: 8.8, h: 1.0,
        fontSize: 18, color: "CADCFC", valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.lt1 },
  margin: [0.5, 0.5, 0.5, 0.5],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 7.6, h: 0.72,
        fontSize: 22, bold: true, color: C.text1, valign: "middle", align: "left" }, text: "" } },
    { text: { text: "INFT 6000 HW3 · Group 4 · Apache Cassandra 5.0",
        options: { x: 0.5, y: 5.22, w: 6, h: 0.28, fontSize: 9, color: HEX.accent6 } } },
  ],
  slideNumber: { x: 9.0, y: 5.22, w: 0.5, h: 0.28, fontSize: 9, color: HEX.accent6, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK_CONTENT",
  background: { color: HEX.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.72,
        fontSize: 22, bold: true, color: C.background1, valign: "middle", align: "left" }, text: "" } },
  ],
  slideNumber: { x: 9.0, y: 5.22, w: 0.5, h: 0.28, fontSize: 9, color: "CADCFC", align: "right" },
});

// ------------------------------------------------------------------ helpers
let n = 0;
function slide(master, section, title, speaker, notes) {
  const s = pres.addSlide({ masterName: master, sectionTitle: section });
  n += 1;
  s.addText(title, { placeholder: "title" });
  if (speaker) {   // motif: speaker pill, top right
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.25, y: 0.42, w: 1.25, h: 0.38, rectRadius: 0.19,
      fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `speaker-${n}` });
    s.addText(speaker, { x: 8.25, y: 0.42, w: 1.25, h: 0.38, fontSize: 11, bold: true, align: "center",
      valign: "middle", color: C.text1, margin: 0, isTextBox: true, objectName: `speaker-text-${n}` });
  }
  if (notes) s.addNotes(notes);
  return s;
}
function image(s, file, box, name) {    // fit inside box, keep aspect ratio, centre
  const { w, h } = imgSize(file);
  const r = Math.min(box.w / w, box.h / h);
  const iw = w * r, ih = h * r;
  s.addImage({ path: file, x: box.x + (box.w - iw) / 2, y: box.y + (box.h - ih) / 2, w: iw, h: ih,
    altText: name, objectName: name });
}
function bullets(s, items, box, size = 14, color) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })),
    { ...box, fontSize: size, color: color || C.text1, paraSpaceAfter: 6, valign: "top", isTextBox: true,
      objectName: "bullets" });
}
function card(s, x, y, w, h, head, body, fill, headColor) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill || C.background2 },
    line: { color: fill || C.background2 }, objectName: `card-${head}` });
  s.addText(head, { x: x + 0.15, y: y + 0.1, w: w - 0.3, h: 0.36, fontSize: 15, bold: true,
    color: headColor || C.text1, margin: 0, isTextBox: true, valign: "top" });
  s.addText(body, { x: x + 0.15, y: y + 0.5, w: w - 0.3, h: h - 0.6, fontSize: 13, color: C.text2,
    margin: 0, isTextBox: true, valign: "top" });
}
function stat(s, x, y, w, value, label, color) {
  s.addText(value, { x, y, w, h: 0.7, fontSize: 36, bold: true, color: color || C.text1, margin: 0,
    isTextBox: true, fontFace: THEME.headFontFace });
  s.addText(label, { x, y: y + 0.7, w, h: 0.5, fontSize: 11, color: C.text2, margin: 0, isTextBox: true, valign: "top" });
}
function numberCircle(s, x, y, k, fill) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.42, h: 0.42, fill: { color: fill || C.accent1 },
    line: { color: fill || C.accent1 }, objectName: `step-${k}` });
  s.addText(String(k), { x, y, w: 0.42, h: 0.42, fontSize: 14, bold: true, align: "center",
    valign: "middle", color: C.text1, margin: 0, isTextBox: true });
}
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt",
  legendFontFace: "+mn-lt", titleFontFace: "+mn-lt", catAxisLabelColor: HEX.dk2, valAxisLabelColor: HEX.dk2,
  dataLabelColor: HEX.dk2, catAxisLabelFontSize: 11, valAxisLabelFontSize: 10, dataLabelFontSize: 9,
  legendFontSize: 11, valGridLine: { color: "E1E0D9", size: 0.5 }, catGridLine: { style: "none" },
  showLegend: true, legendPos: "b" };

// ------------------------------------------------------------------ data
const grid = csv(P("results", "summary", "exp2_grid.csv"));
const probe = csv(P("results", "summary", "exp2_probe.csv"));
const phases = csv(P("results", "summary", "availability_phases.csv"));
const det = csv(P("results", "summary", "detection_times.csv"));
const p50 = (mode, cl) => +(+grid.find((r) => r.mode === mode && r.cl === cl).p50_ms).toFixed(2);
const probesTotal = probe.reduce((a, r) => a + +r.probes, 0);
const staleTotal = probe.reduce((a, r) => a + +r.stale, 0);
const faultPct = (scen, cl) => +(+phases.find((r) => r.scenario === scen && r.phase === "fault" && r.cl === cl).success_pct).toFixed(1);
const detMean = (f) => (+det.find((r) => r.fault === f).mean_s).toFixed(1);

// ------------------------------------------------------------------ 1 title
pres.addSection({ title: "Opening" });
let s = pres.addSlide({ masterName: "DARK_TITLE", sectionTitle: "Opening" });
s.addText("Inside Apache Cassandra 5.0", { placeholder: "title" });
s.addText("Partitioning, tunable consistency, failures, anti-entropy and Paxos, measured on a three-node cluster",
  { placeholder: "body" });
s.addText("INFT 6000 · Homework 3 · Group 4", { x: 0.6, y: 4.35, w: 8.8, h: 0.35, fontSize: 14, bold: true,
  color: C.accent1, isTextBox: true, margin: 0 });
s.addText("Person 1 · Person 2 · Person 3 · Habib Hasanov", { x: 0.6, y: 4.72, w: 8.8, h: 0.35, fontSize: 14,
  color: "CADCFC", isTextBox: true, margin: 0 });
s.addNotes("Person 1 opens. Replace 'Person 1/2/3' with names before the talk. 20 minutes: 8.5 min slides, 11.5 min live demo, then 10 min Q&A.");

// ------------------------------------------------------------------ 2 run of show
s = slide("CONTENT", "Opening", "Twenty minutes, four speakers, four live demos", null,
  "Person 1: the plan. Every member presents slides and runs a live demo segment.");
const plan = [
  ["0:00", "Architecture & ring", "Person 1", 5.0], ["5:00", "Tunable consistency", "Person 2", 5.0],
  ["10:00", "Failures & partition", "Person 3", 5.0], ["15:00", "Repair, consensus, conclusion", "Habib Hasanov", 5.0],
];
let x = 0.5;
const fills = [C.background2, "DCE6F2", C.background2, "DCE6F2", C.background2];
plan.forEach(([t, what, who, min], i) => {
  const w = (9.0 * min) / 20;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.55, w: w - 0.04, h: 1.5, fill: { color: fills[i] }, line: { color: fills[i] },
    objectName: `segment-${i}` });
  s.addText(t, { x: x + 0.08, y: 1.62, w: w - 0.2, h: 0.3, fontSize: 11, color: C.text2, margin: 0, isTextBox: true });
  s.addText(what, { x: x + 0.08, y: 1.95, w: w - 0.2, h: 0.6, fontSize: min > 2 ? 15 : 11, bold: true, color: C.text1,
    margin: 0, isTextBox: true, valign: "top" });
  s.addText(who, { x: x + 0.08, y: 2.62, w: w - 0.2, h: 0.3, fontSize: 11, color: C.text2, margin: 0, isTextBox: true });
  x += w;
});
card(s, 0.5, 3.4, 2.85, 1.55, "Built", "3 × Cassandra 5.0.8 in Docker Compose, RF 3, 16 vnodes; CassChat CLI and workload generator", "FFF4DD");
card(s, 3.575, 3.4, 2.85, 1.55, "Measured", "6 experiments: baseline, ONE/QUORUM/ALL, crash, recovery, partition, Paxos LWT", "FFF4DD");
card(s, 6.65, 3.4, 2.85, 1.55, "Rule", "Every number on these slides is computed from committed CSVs (make figures)", "FFF4DD");

// ------------------------------------------------------------------ 3-4 Person 1
pres.addSection({ title: "Architecture" });
s = slide("CONTENT", "Architecture", "Every node owns ranges of one token ring", "Person 1",
  "Person 1. Murmur3 hashes the partition key to a token; 16 vnodes per node; RF 3 with 3 nodes means every node stores every row (Owns effective 100%). nodetool getendpoints chat messages general lists all three replicas. Any node can coordinate any request.");
image(s, P("docs", "diagrams", "token_ring.png"), { x: 0.5, y: 1.2, w: 4.6, h: 3.85 }, "Token ring diagram");
image(s, P("docs", "diagrams", "deployment.png"), { x: 5.3, y: 1.2, w: 4.2, h: 3.85 }, "Deployment diagram");

s = slide("CONTENT", "Architecture", "Gossip spreads membership; failures are suspected", "Person 1",
  "Person 1. Gossip every second with up to 3 peers; phi-accrual detector with phi_convict_threshold 8. Joining nodes go UJ -> UN; decommission UN -> UL -> removed. Each node has its own view.");
image(s, P("docs", "diagrams", "failure_detection.png"), { x: 0.5, y: 1.2, w: 5.8, h: 3.9 }, "Failure detection sequence");
stat(s, 6.6, 1.4, 2.9, `${detMean("kill (down)")} s`, "mean time for peers to log a crashed node DOWN", C.accent3);
stat(s, 6.6, 2.9, 2.9, `${detMean("stop (down)")} s`, "for a graceful stop: the node announces its shutdown", C.accent4);

// ------------------------------------------------------------------ 5-7 Person 2
pres.addSection({ title: "Consistency" });
s = slide("CONTENT", "Consistency", "Consistency is chosen per request", "Person 2",
  "Person 2. The level is how many replica answers the coordinator waits for; the write still goes to all replicas. R + W > N guarantees overlap with the latest acknowledged write, not linearizability. cqlsh defaults to ONE, the Python driver to LOCAL_ONE; our app always sets it.");
[["ONE", "1 reply", "fastest; may read stale data", CL.ONE], ["QUORUM", "2 replies", "survives 1 node down; QUORUM/QUORUM overlaps", CL.QUORUM],
 ["ALL", "3 replies", "freshest; fails if any replica is down", CL.ALL]].forEach(([name, rep, txt, col], i) => {
  const cx = 0.5 + i * 3.05;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: 1.2, w: 2.9, h: 1.35, rectRadius: 0.08, fill: { color: C.background2 },
    line: { color: C.background2 }, objectName: `cl-${name}` });
  s.addShape(pres.shapes.OVAL, { x: cx + 0.15, y: 1.32, w: 0.3, h: 0.3, fill: { color: col }, line: { color: col } });
  s.addText(`${name} · ${rep}`, { x: cx + 0.55, y: 1.3, w: 2.25, h: 0.35, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true });
  s.addText(txt, { x: cx + 0.15, y: 1.75, w: 2.6, h: 0.7, fontSize: 12, color: C.text2, margin: 0, isTextBox: true, valign: "top" });
});
image(s, P("docs", "diagrams", "quorum_overlap.png"), { x: 0.5, y: 2.75, w: 9.0, h: 2.35 }, "Quorum overlap diagram");

s = slide("CONTENT", "Consistency", "Writes reach every replica; reads compare digests", "Person 2",
  "Person 2. Write: commit log + memtable, reply after W acks, hints for down replicas, timeout is not rollback. Read: 1 data + R-1 digest requests; mismatch -> full reads -> LWW -> blocking read repair before replying.");
image(s, P("docs", "diagrams", "write_path.png"), { x: 0.5, y: 1.15, w: 4.4, h: 3.95 }, "Write path");
image(s, P("docs", "diagrams", "read_path.png"), { x: 5.1, y: 1.15, w: 4.4, h: 3.95 }, "Read path");

s = slide("CONTENT", "Consistency", "Stronger levels cost a little latency on one host", "Person 2",
  "Person 2. Median latency of successful operations, 200 ops/s open loop, 3 repetitions pooled (results/summary/exp2_grid.csv). Differences are sub-millisecond because all replicas share one host. Freshness probes: write then immediately read through another coordinator.");
s.addChart(pres.charts.BAR, ["ONE", "QUORUM", "ALL"].map((cl) => ({
  name: cl, labels: ["write", "read", "mixed"], values: ["write", "read", "mixed"].map((m) => p50(m, cl)) })),
{ x: 0.5, y: 1.15, w: 6.0, h: 3.95, barDir: "col", barGapWidthPct: 60, chartColors: [CL.ONE, CL.QUORUM, CL.ALL],
  showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", valAxisTitle: "median latency (ms)",
  showValAxisTitle: true, valAxisTitleFontSize: 10, valAxisTitleColor: HEX.dk2, valAxisTitleFontFace: "+mn-lt",
  showTitle: false, ...chartText });
stat(s, 6.9, 1.4, 2.6, `${staleTotal} / ${probesTotal.toLocaleString("en-US")}`, "stale reads in freshness probes across all five write/read pairs", C.text1);
s.addText("Staleness is possible when R + W ≤ N, but replicas apply writes within milliseconds on one host; it becomes visible in the recovery and partition experiments.",
  { x: 6.9, y: 2.85, w: 2.6, h: 1.8, fontSize: 12, color: C.text2, margin: 0, isTextBox: true, valign: "top" });

// ------------------------------------------------------------------ 8-10 Person 3
pres.addSection({ title: "Failures" });
s = slide("CONTENT", "Failures", "With one node down, QUORUM survives and ALL fails", "Person 3",
  "Person 3. Share of probe operations that succeeded inside the fault window (from the injection command to the restart/heal command), 3 repetitions pooled (results/summary/availability_phases.csv). ALL fails first as timeouts until gossip marks the node down, then as Unavailable. In 3b QUORUM held until the second node was killed.");
const scen = [["3a", "1 node killed"], ["3b", "2 nodes killed"], ["3c", "stop, then kill"], ["partition", "partition"]];
s.addChart(pres.charts.BAR, ["ONE", "QUORUM", "ALL"].map((cl) => ({
  name: cl, labels: scen.map((x) => x[1]), values: scen.map(([k]) => faultPct(k, cl)) })),
{ x: 0.5, y: 1.15, w: 6.3, h: 3.95, barDir: "col", barGapWidthPct: 55, chartColors: [CL.ONE, CL.QUORUM, CL.ALL],
  showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0", valAxisMaxVal: 110, valAxisMinVal: 0,
  valAxisLabelFormatCode: "0", valAxisTitle: "success in fault window (%)", showValAxisTitle: true,
  valAxisTitleFontSize: 10, valAxisTitleColor: HEX.dk2, valAxisTitleFontFace: "+mn-lt", ...chartText });
stat(s, 7.1, 1.4, 2.4, `${detMean("kill (down)")} s`, "until peers mark a crashed node DOWN: ALL times out meanwhile", C.accent3);
stat(s, 7.1, 2.75, 2.4, `${faultPct("3a", "ALL")}%`, "of ALL operations succeeded with one node killed", C.text1);

s = slide("CONTENT", "Failures", "A partition splits availability by consistency level", "Person 3",
  "Person 3. cass3 disconnected from the Docker network while its container keeps running; both sides suspect each other. Writes use explicit timestamps so the winner is deterministic. Evidence: results/logs/exp5/<run>/06-09.");
[["Minority · QUORUM", "rejected: cannot reach 2 replicas", CL.QUORUM], ["Minority · ONE", "accepted on the isolated node", CL.ONE],
 ["Majority · QUORUM", "accepted by cass1 + cass2", CL.QUORUM], ["After heal · ALL", "returns the higher-timestamp majority write; the minority's acknowledged write is gone (LWW)", CL.ALL]]
  .forEach(([h, b, col], i) => {
    const cy = 1.2 + i * 0.97;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y: cy, w: 5.0, h: 0.85, rectRadius: 0.08, fill: { color: C.background2 },
      line: { color: C.background2 }, objectName: `partition-${i}` });
    s.addShape(pres.shapes.OVAL, { x: 0.65, y: cy + 0.27, w: 0.3, h: 0.3, fill: { color: col }, line: { color: col } });
    s.addText(h, { x: 1.1, y: cy + 0.07, w: 4.3, h: 0.32, fontSize: 14, bold: true, color: C.text1, margin: 0, isTextBox: true });
    s.addText(b, { x: 1.1, y: cy + 0.4, w: 4.3, h: 0.42, fontSize: 11, color: C.text2, margin: 0, isTextBox: true, valign: "top" });
  });
stat(s, 6.0, 1.3, 3.5, `${detMean("partition, majority view")} s`, "majority logs the isolated node DOWN", C.text1);
stat(s, 6.0, 2.5, 3.5, `${detMean("partition, minority view")} s`, "isolated node logs its peers DOWN: a true partition, not a crash", C.text1);
s.addText("Cassandra keeps both sides available at ONE and reconciles afterwards: it tolerates split-brain for ordinary data instead of preventing it.",
  { x: 6.0, y: 3.75, w: 3.5, h: 1.3, fontSize: 12, italic: true, color: C.text2, margin: 0, isTextBox: true, valign: "top" });

s = slide("CONTENT", "Failures", "Cassandra is neither simply AP nor CP", "Person 3",
  "Person 3. PACELC: the consistency level decides the trade-off per request. Client-side note from the analysis: in each Exp 5 repetition one probe level kept sending to the isolated coordinator and hit 5 s client timeouts until heal (results/summary/summary.md, per-repetition table).");
card(s, 0.5, 1.2, 4.35, 2.2, "If Partitioned: C or A, per request",
  "ONE stays available on both sides and diverges; QUORUM/SERIAL stay consistent and are rejected on the minority side.", C.background2);
card(s, 5.15, 1.2, 4.35, 2.2, "Else: Latency or Consistency",
  "Without faults, each step from ONE to ALL waits for one more replica: more latency for fresher reads.", C.background2);
card(s, 0.5, 3.6, 9.0, 1.45, "Availability also depends on the client's route",
  "During the partition the driver kept routing one probe level to the isolated coordinator: 5 s timeouts for over a minute although the majority could serve it. A retry or speculative-execution policy would mask this.", "FFF4DD");

// ------------------------------------------------------------------ 11-13 Habib Hasanov
pres.addSection({ title: "Repair and consensus" });
s = slide("CONTENT", "Repair and consensus", "Three ways replicas heal", "Habib Hasanov",
  "Habib Hasanov (45 s). Hints fix short outages for free, read repair fixes hot data, full Merkle-tree repair is the safety net and the only one that covers never-read rows and deletes - it must run within gc_grace_seconds (10 days) or deleted data comes back. All three resolve conflicts the same way: highest timestamp wins.");
image(s, P("docs", "diagrams", "antientropy_merkle.png"), { x: 0.5, y: 1.1, w: 9.0, h: 3.0 }, "Repair mechanisms diagram");
[["Hinted handoff", "best effort, ≤ 3 h, never counts toward the CL"], ["Read repair", "only the rows read, blocking since 4.0"],
 ["Anti-entropy", "all data; within gc_grace_seconds"]].forEach(([h, b], i) => {
  s.addText([{ text: h + ": ", options: { bold: true, color: C.text1 } }, { text: b, options: { color: C.text2 } }],
    { x: 0.5 + i * 3.05, y: 4.3, w: 2.9, h: 0.7, fontSize: 12, margin: 0, isTextBox: true, valign: "top" });
});

s = slide("CONTENT", "Repair and consensus", "Consensus only where needed: Paxos per partition", "Habib Hasanov",
  "Habib Hasanov (45 s). No leader, no replicated log, no election for ordinary operations; quorum overlap is not agreement. LWT = single-decree Paxos among the partition's replicas: prepare/promise, read, propose/accept, commit - 4 round trips in v1 (default in 5.0). Ballots, not a leader, decide. Majorities intersect, so two sides of a partition can never both commit. 6.0 (alpha) adds Transactional Cluster Metadata (CEP-21) and Accord (CEP-15).");
image(s, P("docs", "diagrams", "paxos_lwt.png"), { x: 0.5, y: 1.1, w: 4.3, h: 4.0 }, "Paxos LWT sequence diagram");
bullets(s, [
  "Ordinary reads/writes: no leader, no log, no election",
  "Gossip spreads membership; it does not agree",
  "IF NOT EXISTS / IF: one Paxos instance per partition, 4 round trips (v1)",
  "Any two majorities intersect: no split-brain for LWTs",
  "Cassandra 6.0 (alpha): TCM metadata log, Accord transactions",
], { x: 5.1, y: 1.2, w: 4.4, h: 3.9 }, 15);

s = slide("CONTENT", "Repair and consensus", "Live demo: heal, verify, race", "Habib Hasanov",
  "Habib Hasanov (2.5 min). Commands in docs/presentation/hasanov_talk.md. Starts with cass3 down after Person 3's segment. Backup: results/logs/exp4 and exp6 outputs.");
[["Write while cass3 is down", "verify_convergence write --n 2000", "coordinators keep hints: nodetool listpendinghints"],
 ["Restart cass3", "chaos/start_node.sh cass3", "hints replay automatically; pending list empties"],
 ["Prove convergence", "make verify", "Merkle-tree preview: IN SYNC → CONVERGENCE PASS"],
 ["Race for usernames", "make exp6-race", "10 clients × 20 handles: exactly one winner each, 0 violations"]]
  .forEach(([h, cmd, look], i) => {
    const cy = 1.2 + i * 0.98;
    numberCircle(s, 0.5, cy + 0.15, i + 1);
    s.addText(h, { x: 1.1, y: cy + 0.05, w: 3.2, h: 0.36, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true });
    s.addText(cmd, { x: 1.1, y: cy + 0.42, w: 3.2, h: 0.3, fontSize: 11, fontFace: "Courier New", color: C.text2, margin: 0, isTextBox: true });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 4.6, y: cy, w: 4.9, h: 0.82, rectRadius: 0.08, fill: { color: C.background2 },
      line: { color: C.background2 }, objectName: `look-${i}` });
    s.addText(look, { x: 4.75, y: cy, w: 4.6, h: 0.82, fontSize: 13, color: C.text1, margin: 0, isTextBox: true, valign: "middle" });
  });

// ------------------------------------------------------------------ 14-15 closing
pres.addSection({ title: "Closing" });
s = slide("DARK_CONTENT", "Closing", "What we learned", null,
  "Habib Hasanov (1 min). Then hand over to Q&A.");
[["Leaderless by design", "any node coordinates; consistency is chosen per request"],
 ["Failure is local opinion", `gossip needs ~${Math.round(+detMean("kill (down)"))} s to suspect a crash; ALL stops, QUORUM survives one node`],
 ["Divergence is healed in layers", "hints, read repair, Merkle-tree repair; acknowledged QUORUM writes must survive (Exp 4)"],
 ["LWW loses concurrent writes", "Paxos LWTs give one winner per key at several times the latency (Exp 6)"],
 ["Limits", "one host (sub-ms network), short outages, 5.0 only: TCM and Accord not tested"]]
  .forEach(([h, b], i) => {
    const cy = 1.2 + i * 0.78;
    numberCircle(s, 0.5, cy + 0.05, i + 1);
    s.addText(h, { x: 1.1, y: cy, w: 3.1, h: 0.55, fontSize: 16, bold: true, color: C.background1, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(b, { x: 4.3, y: cy, w: 5.2, h: 0.55, fontSize: 13, color: "CADCFC", margin: 0, isTextBox: true, valign: "middle" });
  });

s = slide("DARK_CONTENT", "Closing", "Questions", null, "All four answer by area of ownership.");
[["Person 1", "ring, vnodes, gossip, bootstrap / decommission, Docker setup"], ["Person 2", "consistency levels, read/write paths, quorum math, Exp 2"],
 ["Person 3", "crashes, partitions, CAP / PACELC, detection times"], ["Habib Hasanov", "LWW, hints, read repair, Merkle trees, Paxos, TCM / Accord, statistics"]]
  .forEach(([who, what], i) => {
    const cx = 0.5 + (i % 2) * 4.6, cy = 1.4 + Math.floor(i / 2) * 1.75;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: cy, w: 4.4, h: 1.5, rectRadius: 0.08, fill: { color: "24345A" },
      line: { color: "24345A" }, objectName: `qa-${i}` });
    s.addText(who, { x: cx + 0.2, y: cy + 0.15, w: 4.0, h: 0.4, fontSize: 17, bold: true, color: C.accent1, margin: 0, isTextBox: true });
    s.addText(what, { x: cx + 0.2, y: cy + 0.6, w: 4.0, h: 0.8, fontSize: 13, color: C.background1, margin: 0, isTextBox: true, valign: "top" });
  });

(async () => {
  await pres.writeFile({ fileName: OUT });
  const themeFile = path.join(__dirname, "theme.json");
  fs.writeFileSync(themeFile, JSON.stringify(THEME, null, 2));
  execFileSync("python3", [path.join(__dirname, "apply_theme.py"), OUT, themeFile], { stdio: "inherit" });
  console.log(`wrote ${OUT} (${n + 1} slides)`);
})();

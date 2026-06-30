// WebHID transport + UI. Mirrors the CLI menu: pick a device, fire colors/effects.
// Uses globals from devices.js (DEVICES, DEFAULT_PID, getDevice) and protocol.js
// (razerReport, buildReports, anyRGB).

const VID = 0x1532;
const QUICK = [["red", [255, 0, 0]], ["green", [0, 255, 0]], ["blue", [0, 0, 255]],
               ["white", [255, 255, 255]], ["yellow", [255, 255, 0]], ["cyan", [0, 255, 255]],
               ["magenta", [255, 0, 255]], ["orange", [255, 80, 0]]];
const NAMED = Object.assign({ off: [0, 0, 0], black: [0, 0, 0], purple: [128, 0, 128] },
                            Object.fromEntries(QUICK));
const HZ = { 1: 1000, 2: 500, 3: 125 };

let devicesByPid = new Map();   // pid -> [HIDDevice, ...]
let currentPid = null;
let save = true;

const $ = (id) => document.getElementById(id);
const hex4 = (p) => p.toString(16).padStart(4, "0");

// --- color / label helpers (port of core.parse_color / describe) -------------
function parseColor(s) {
  const t = s.trim().replace(/^#/, "").toLowerCase();
  if (t in NAMED) return NAMED[t].slice();
  if (s.includes(",")) {
    const parts = s.split(",");
    if (parts.length === 3 && parts.every((p) => /^\d+$/.test(p.trim()) && +p >= 0 && +p <= 255))
      return parts.map((p) => +p);
  }
  if (/^[0-9a-f]{6}$/.test(t)) return [0, 2, 4].map((i) => parseInt(t.slice(i, i + 2), 16));
  throw new Error(`bad color '${s}' (use ff0000, '255,0,0', or a name)`);
}
function describe(action, rgb) {
  if (action === "static" || (action === "breathing" && anyRGB(rgb))) {
    const hex = "#" + rgb.map((c) => c.toString(16).padStart(2, "0")).join("");
    return hex + (action === "breathing" ? " breathing" : "");
  }
  return action;
}
const pickerRGB = () => parseColor($("picker").value);
const ovHex = (id) => { const v = $(id).value.trim(); return v ? parseInt(v, 16) : null; };

// --- WebHID transport --------------------------------------------------------
async function refresh() {
  devicesByPid = new Map();
  if (navigator.hid) {
    for (const d of await navigator.hid.getDevices()) {
      if (d.vendorId !== VID) continue;
      if (!devicesByPid.has(d.productId)) devicesByPid.set(d.productId, []);
      devicesByPid.get(d.productId).push(d);
    }
  }
  renderDevices();
}

async function requestDevices() {
  try {
    await navigator.hid.requestDevice({ filters: [{ vendorId: VID }] });
    await refresh();
  } catch (e) { setStatus(e.message, "err"); }
}

async function sendReports(pid, reports) {
  const cands = devicesByPid.get(pid) || [];
  if (!cands.length) throw new Error(`no 1532:${hex4(pid)} granted -- click Connect`);
  let last = null;
  for (const dev of cands) {
    try {
      if (!dev.opened) await dev.open();
      for (const rep of reports) await dev.sendFeatureReport(0, rep);
      return;
    } catch (e) { last = e; }
  }
  throw new Error(`every granted collection rejected the report (last: ${last && last.message}). ` +
    `Chrome may be blocking this device's mouse collection (WebHID protected usage).`);
}

async function readHz(pid) {
  const req = razerReport(0x00, 0x85, 0x01, [], 0xFF);   // get polling rate
  for (const dev of devicesByPid.get(pid) || []) {
    try {
      if (!dev.opened) await dev.open();
      await dev.sendFeatureReport(0, req);
      const dv = await dev.receiveFeatureReport(0);
      if (dv.getUint8(0) === 0x02 && dv.getUint8(8)) {
        const code = dv.getUint8(8);
        return HZ[code] || (code >= 1 && code <= 8 ? Math.floor(1000 / code) : null);
      }
    } catch (e) { /* collection can't be read -- try next */ }
  }
  return null;
}

// --- apply (port of core.apply) ----------------------------------------------
async function applyAction(action, rgb) {
  if (currentPid == null) { setStatus("connect a device first", "err"); return; }
  const dev = getDevice(currentPid);
  let method, txn, led, label;
  const ovTxn = ovHex("txnInput"), ovLed = ovHex("ledInput");
  if (dev) {
    method = dev.method; txn = ovTxn ?? dev.txn; led = ovLed ?? dev.led; label = dev.name;
  } else {
    method = "custom"; txn = ovTxn ?? 0x3f; led = ovLed ?? 0x00; label = `unknown 1532:${hex4(currentPid)}`;
  }
  let reports;
  try { reports = buildReports(method, action, rgb, txn, led, save); }
  catch (e) { setStatus(`${label}: ${e.message}`, "err"); return; }
  try {
    await sendReports(currentPid, reports);
    setStatus(`OK  ${label} -> ${describe(action, rgb)}`, "ok");
  } catch (e) { setStatus(`${label}: ${e.message}`, "err"); }
}

// --- rendering ---------------------------------------------------------------
function setStatus(msg, kind) {
  const el = $("status");
  el.textContent = msg;
  el.className = "text-sm min-h-[1.25rem] " +
    (kind === "ok" ? "text-emerald-400" : kind === "err" ? "text-red-400" : "text-neutral-400");
}

function renderDevices() {
  const sel = $("deviceSelect");
  const pids = [...devicesByPid.keys()].sort((a, b) => a - b);
  if (!pids.length) {
    sel.innerHTML = "<option>No devices -- click Connect</option>";
    currentPid = null; $("deviceMeta").textContent = ""; toggleEffects();
    return;
  }
  if (currentPid == null || !devicesByPid.has(currentPid))
    currentPid = pids.includes(DEFAULT_PID) ? DEFAULT_PID : pids[0];
  sel.innerHTML = pids.map((p) => {
    const d = getDevice(p);
    const star = p === DEFAULT_PID ? " *" : "";
    return `<option value="${p}" ${p === currentPid ? "selected" : ""}>${d ? d.name : "unknown model"} (1532:${hex4(p)})${star}</option>`;
  }).join("");
  renderMeta();
}

async function renderMeta() {
  const d = getDevice(currentPid);
  const m = $("deviceMeta");
  const base = d ? `method ${d.method} · txn 0x${d.txn.toString(16)} · led 0x${d.led.toString(16)}`
                 : "unknown model · falls back to custom / txn 3f";
  m.textContent = base;
  toggleEffects();
  const hz = await readHz(currentPid);
  if (hz && getDevice(currentPid) === d) m.textContent = base + `  ·  ${hz} Hz`;
}

function toggleEffects() {
  const d = getDevice(currentPid);
  // wave hidden on single-LED (custom/logo) and unknown (treated as custom)
  const canWave = d && d.method !== "custom" && d.method !== "logo";
  const w = $("fxWave");
  w.disabled = !canWave;
  w.classList.toggle("opacity-30", !canWave);
  w.classList.toggle("cursor-not-allowed", !canWave);
}

function buildColorGrid() {
  $("colorGrid").innerHTML = QUICK.map(([name, rgb]) => {
    const css = `rgb(${rgb.join(",")})`;
    const dark = name === "white" || name === "yellow";
    return `<button class="swatch rounded-xl px-2 py-4 text-xs font-bold capitalize ring-1 ring-inset ring-black/20 shadow-lg shadow-black/40 hover:ring-2 hover:ring-white/60 ${dark ? "text-black/80" : "text-white drop-shadow"}"
            style="background:${css}" data-rgb="${rgb.join(",")}">${name}</button>`;
  }).join("");
  $("colorGrid").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    const rgb = b.dataset.rgb.split(",").map(Number);
    $("picker").value = "#" + rgb.map((c) => c.toString(16).padStart(2, "0")).join("");
    applyAction("static", rgb);
  }));
}

// --- init --------------------------------------------------------------------
function init() {
  if (!navigator.hid) {
    $("unsupported").classList.remove("hidden");
    document.querySelectorAll("button, select, input").forEach((e) => (e.disabled = true));
    return;
  }
  buildColorGrid();
  $("connectBtn").addEventListener("click", requestDevices);
  $("deviceSelect").addEventListener("change", (e) => { currentPid = +e.target.value; renderMeta(); });
  $("saveToggle").addEventListener("change", (e) => { save = e.target.checked; });
  $("picker").addEventListener("change", () => applyAction("static", pickerRGB()));
  const applyText = () => { try { const rgb = parseColor($("colorText").value); $("picker").value = "#" + rgb.map((c) => c.toString(16).padStart(2, "0")).join(""); applyAction("static", rgb); } catch (e) { setStatus(e.message, "err"); } };
  $("applyColorBtn").addEventListener("click", applyText);
  $("colorText").addEventListener("keydown", (e) => { if (e.key === "Enter") applyText(); });
  $("fxSpectrum").addEventListener("click", () => applyAction("spectrum", null));
  $("fxBreathing").addEventListener("click", () => applyAction("breathing", pickerRGB()));
  $("fxWave").addEventListener("click", () => applyAction("wave", null));
  $("fxOff").addEventListener("click", () => applyAction("static", [0, 0, 0]));
  navigator.hid.addEventListener("connect", refresh);
  navigator.hid.addEventListener("disconnect", refresh);
  refresh();
}

document.addEventListener("DOMContentLoaded", init);

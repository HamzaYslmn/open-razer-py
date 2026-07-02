import { useEffect, useRef, useState } from "react";
import { DEFAULT_PID, getDevice } from "./lib/devices.js";
import { matrixFor, zonesFor } from "./lib/matrix.js";
import { layoutFor } from "./lib/keyLayout.js";
import { buildReports, buildCustomFrame, brightnessReport, setDpiReport, setPollReport, setPoll2Report,
         setScrollModeReport, setScrollAccelReport, setSmartReelReport, setGameModeReport, setMacroModeReport,
         bladePerf, bladeCharge, PERF_MODES } from "./lib/protocol.js";
import MatrixPad from "./components/MatrixPad.jsx";
import ZoneEditor from "./components/ZoneEditor.jsx";
import DeviceControls from "./components/DeviceControls.jsx";
import LaptopControls from "./components/LaptopControls.jsx";
import ProfilesCard from "./components/ProfilesCard.jsx";
import { VID, supported, listDevices, requestDevices, indexByPid, sendReports, readHz, readDpi, readInfo } from "./lib/hid.js";
import { clamp, hex4, rgbToHex, QUICK, parseColor, describe } from "./lib/color.js";
import { store, persist } from "./lib/store.js";
import { makeT, useI18n } from "./i18n/index.jsx";
import logo from "./assets/logo.png";

const HID = supported();
const initRGB = Array.isArray(store.lastRGB) ? store.lastRGB.map(clamp) : [0, 255, 136];

// rich (HTML) string → props for dangerouslySetInnerHTML; plain string → text.
const html = (s) => ({ dangerouslySetInnerHTML: { __html: s } });

export default function App() {
  const { t, lang, setLang } = useI18n();
  const [devicesByPid, setDevicesByPid] = useState(new Map());
  const [currentPid, setCurrentPid] = useState(null);
  const [rgb, setRgb] = useState(initRGB);
  const [hexText, setHexText] = useState(rgbToHex(initRGB).slice(1));
  const [rgbText, setRgbText] = useState(initRGB.join(", "));
  const [save, setSave] = useState(store.save ?? true);
  const [txnOv, setTxnOv] = useState(typeof store.txn === "string" ? store.txn : "");
  const [ledOv, setLedOv] = useState(typeof store.led === "string" ? store.led : "");
  const [brightness, setBrightness] = useState(typeof store.lastBrightness === "number" ? store.lastBrightness : 100);
  const [dpiText, setDpiText] = useState("");
  const [poll, setPoll] = useState("");
  const [status, setStatusState] = useState({ msg: "", kind: "" });
  const [toasts, setToasts] = useState([]);
  const [hz, setHz] = useState(null);
  const [info, setInfo] = useState(null);
  const [reading, setReading] = useState(false);
  const [sponsor, setSponsor] = useState(true);
  const [tab, setTab] = useState("keyboard");         // active menu; heavy per-LED editors mount only on their tab

  const applyTimer = useRef(null);
  const briTimer = useRef(null);
  const toastId = useRef(0);
  // latest state for async callbacks (timers / HID events) — avoids stale closures
  const live = useRef({});
  live.current = { currentPid, devicesByPid, save, txnOv, ledOv, lang };

  // --- toasts / status ---
  const toast = (msg, kind = "ok") => {
    const id = ++toastId.current;
    setToasts((ts) => [...ts, { id, msg, kind }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), kind === "err" ? 6500 : 3000);
  };
  const setStatus = (msg, kind) => setStatusState({ msg, kind });

  // --- override readers (from latest state) ---
  const ovTxn = () => { const v = (live.current.txnOv || "").trim(); return v ? parseInt(v, 16) : null; };
  const ovLed = () => { const v = (live.current.ledOv || "").trim(); return v ? parseInt(v, 16) : null; };
  const txnCandidates = () => {
    const dev = getDevice(live.current.currentPid);
    return [...new Set([...(dev ? [dev.txn] : [0x3f]), 0xFF, 0x1F, 0x3F])];
  };

  // --- apply (port of core.apply) ---
  async function applyAction(action, color) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const dev = getDevice(pid), oTxn = ovTxn(), oLed = ovLed();
    let method, txn, led, label;
    if (dev) { method = dev.method; txn = oTxn ?? dev.txn; led = oLed ?? dev.led; label = dev.name; }
    else { method = "custom"; txn = oTxn ?? 0x3f; led = oLed ?? 0x00; label = `unknown 1532:${hex4(pid)}`; }
    let reports;
    try { reports = buildReports(method, action, color, txn, led, live.current.save); }
    catch (e) { setStatus(`${label}: ${e.message}`, "err"); toast(e.message, "err"); return; }
    try {
      await sendReports(live.current.devicesByPid.get(pid), reports);
      setStatus(t("okApply", { label, desc: describe(action, color) }), "ok");
      const key = hex4(pid);
      store.perDevice[key] = { rgb: color ? color.map(clamp) : store.perDevice[key]?.rgb, action };
      if (color) store.lastRGB = color.map(clamp);
      store.lastPid = pid; persist();
    } catch (e) { setStatus(`${label}: ${e.message}`, "err"); toast(e.message, "err"); }
  }
  const applyDebounced = (action, color) => { clearTimeout(applyTimer.current); applyTimer.current = setTimeout(() => applyAction(action, color), 500); };
  const applyNow = (action, color) => { clearTimeout(applyTimer.current); applyAction(action, color); };

  // --- profiles: snapshot of per-device state; apply hits every connected device in it ---
  const profileSnapshot = () => {
    const snap = {};
    for (const [key, ent] of Object.entries(store.perDevice)) {
      if (ent && (Array.isArray(ent.rgb) || ent.action)) snap[key] = { rgb: ent.rgb, action: ent.action || "static" };
    }
    return Object.keys(snap).length ? snap : null;
  };
  async function applyProfile(name) {
    const prof = (store.profiles || {})[name];
    if (!prof) return;
    let n = 0, firstErr = null;
    for (const [key, ent] of Object.entries(prof)) {
      const pid = parseInt(key, 16);
      if (!live.current.devicesByPid.has(pid) || !ent) continue;
      const d = getDevice(pid);
      const method = d ? d.method : "custom", txn = d ? d.txn : 0x3f, led = d ? d.led : 0x00;
      const action = ent.action || "static";
      const color = Array.isArray(ent.rgb) ? ent.rgb.map(clamp) : null;
      if (action === "static" && !color) continue;
      try {
        await sendReports(live.current.devicesByPid.get(pid), buildReports(method, action, color, txn, led, live.current.save));
        store.perDevice[key] = { rgb: color ?? store.perDevice[key]?.rgb, action };
        n++;
      } catch (e) { firstErr = e; }
    }
    persist();
    if (n) {
      setStatus(t("okProfile", { name, n }), "ok"); toast(t("okProfile", { name, n }), "ok");
      if (live.current.currentPid != null) reflect(live.current.currentPid);
    } else {
      toast(firstErr ? firstErr.message : t("profNoDev"), firstErr ? "err" : "warn");
    }
  }

  // --- color sync: fromText=true means the text inputs are the source (don't clobber them) ---
  function setColor(next, { fromText = false, apply = false } = {}) {
    next = next.map(clamp);
    setRgb(next);
    if (!fromText) { setHexText(rgbToHex(next).slice(1)); setRgbText(next.join(", ")); }
    if (apply) applyDebounced("static", next);
  }

  async function setBrightnessDevice(pct) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const dev = getDevice(pid), method = dev ? dev.method : "custom";
    const txn = ovTxn() ?? (dev ? dev.txn : 0x3f), led = ovLed() ?? (dev ? dev.led : 0x00);
    const level = Math.round(Math.max(0, Math.min(100, pct)) * 255 / 100);
    try {
      await sendReports(live.current.devicesByPid.get(pid), brightnessReport(method, level, txn, led, live.current.save));
      setStatus(t("okBrightness", { pct }), "ok"); store.lastBrightness = pct; persist();
    } catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }

  // re-read the live values (Hz + DPI) and update the display for the given device
  const refreshLive = async (pid) => {
    const cands = live.current.devicesByPid.get(pid), d = getDevice(pid);
    const hz = await readHz(cands, pid, d);
    if (live.current.currentPid === pid && hz != null) setHz(hz);
    const dpi = await readDpi(cands, pid, d);
    if (live.current.currentPid === pid && dpi) setInfo((prev) => (prev ? { ...prev, dpi } : { battery: null, charging: null, fw: null, serial: null, dpi }));
  };

  async function setDpiWeb(spec) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const m = String(spec).toLowerCase().split("x");                 // "1600" or "1600x800"
    const x = +m[0], y = m[1] ? +m[1] : x;
    if (!(x >= 100 && x <= 30000 && y >= 100 && y <= 30000)) { toast(t("dpiRange"), "err"); return; }
    const reports = [];
    for (const tx of txnCandidates()) reports.push(...setDpiReport(x, y, tx));
    try {
      await sendReports(live.current.devicesByPid.get(pid), reports);
      setStatus(t("okDpi", { x: x === y ? x : `${x}×${y}` }), "ok");
      setTimeout(() => refreshLive(pid), 300);                       // confirm the change from the device
    } catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }
  async function setPollWeb(rate) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const build = [1000, 500, 125].includes(rate) ? setPollReport : setPoll2Report;  // HyperPolling for the rest
    let reports = [];
    try { for (const tx of txnCandidates()) reports.push(...build(rate, tx)); }
    catch (e) { toast(e.message, "err"); return; }
    try {
      await sendReports(live.current.devicesByPid.get(pid), reports);
      setStatus(t("okPoll", { hz: rate }), "ok");
      setTimeout(() => refreshLive(pid), 300);                       // confirm the change from the device
    } catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }
  // onboard toggles (scroll modes / game+macro) — fire-and-forget, no readback
  async function sendSimple(reports, what, val) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    try { await sendReports(live.current.devicesByPid.get(pid), reports); setStatus(t("okSet", { what, val }), "ok"); }
    catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }
  const featTxn = () => methodTxnLed().txn;
  const onScrollMode = (mode) => sendSimple(setScrollModeReport(mode, featTxn()), t("scrollLabel"), mode ? t("scrollTactile") : t("scrollFree"));
  const onScrollAccel = (on) => sendSimple(setScrollAccelReport(on, featTxn()), t("accelLabel"), on ? "on" : "off");
  const onSmartReel = (on) => sendSimple(setSmartReelReport(on, featTxn()), t("smartReelLabel"), on ? "on" : "off");
  const onGameMode = (on) => sendSimple(setGameModeReport(on), t("gameModeLabel"), on ? "on" : "off");
  const onMacroMode = (on) => sendSimple(setMacroModeReport(on), t("macroModeLabel"), on ? "on" : "off");

  // Razer Blade laptop: fan / performance / battery (same HID transport)
  async function bladeSend(reports, what, val) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    try { await sendReports(live.current.devicesByPid.get(pid), reports); setStatus(t("okSet", { what, val }), "ok"); }
    catch (e) { setStatus(e.message, "err"); toast(t("bladeReach"), "err"); }
  }
  const onBladePerf = (mode) => bladeSend(bladePerf(PERF_MODES[mode]), t("bladePerf"), mode);
  const onBladeCharge = (spec) => {
    const off = String(spec).toLowerCase() === "off";
    const pct = off ? 0 : +spec;
    if (!off && !(pct >= 50 && pct <= 95)) { toast("50-95% or off", "err"); return; }
    bladeSend(bladeCharge(pct), t("bladeCharge"), off ? "off" : pct + "%");
  };

  // --- per-key frame + per-zone (custom lighting) ---
  const methodTxnLed = () => {
    const dev = getDevice(live.current.currentPid);
    return {
      method: dev ? dev.method : "custom",
      txn: ovTxn() ?? (dev ? dev.txn : 0x3f),
      led: ovLed() ?? (dev ? dev.led : 0x00),
    };
  };
  async function applyFrame(frameRows) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const { method, txn, led } = methodTxnLed();
    let reports;
    try { reports = buildCustomFrame(method, frameRows, txn, led, live.current.save); }
    catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); return; }
    try {
      await sendReports(live.current.devicesByPid.get(pid), reports);
      setStatus(t("okFrame", { n: frameRows.reduce((s, r) => s + r.colors.length, 0) }), "ok");
    } catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }
  async function applyZone(zoneLed, color) {
    const pid = live.current.currentPid;
    if (pid == null) { toast(t("connectFirst"), "warn"); return; }
    const { method, txn } = methodTxnLed();
    try {
      await sendReports(live.current.devicesByPid.get(pid), buildReports(method, "static", color, txn, zoneLed, live.current.save));
      setStatus(t("okZone", { zone: "0x" + zoneLed.toString(16).padStart(2, "0"), hex: rgbToHex(color) }), "ok");
    } catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  }

  // --- device discovery ---
  const refresh = async () => {
    try { setDevicesByPid(indexByPid(await listDevices())); }
    catch (e) { toast("device scan failed: " + e.message, "err"); }
  };
  const reflect = (pid) => {   // show a device's last-known color (preview only)
    const d = store.perDevice[hex4(pid)];
    if (d && Array.isArray(d.rgb)) setColor(d.rgb.map(clamp));
  };
  async function connect() {
    let granted;
    try { granted = await requestDevices(); } catch (e) { toast(e.message, "err"); return; }
    if (!granted.length) { toast(t("noDeviceSelected"), "warn"); return; }
    // merge granted with already-permitted so a just-granted device is never lost
    const known = await listDevices();
    const map = indexByPid([...new Set([...known, ...granted])]);
    setDevicesByPid(map);
    const pid = granted[0].productId;
    if (map.has(pid)) {
      setCurrentPid(pid); reflect(pid);
      toast(t("connected", { name: getDevice(pid)?.name || granted[0].productName || hex4(pid) }), "ok");
    } else {
      toast(t("noUsable", { name: granted[0].productName || `1532:${hex4(pid)}` }), "err");
    }
  }

  // mount: initial scan + HID connect/disconnect listeners
  useEffect(() => {
    if (!HID) return;
    refresh();
    const name = (d) => getDevice(d.productId)?.name || d.productName || "Razer";
    const onConnect = (e) => { refresh(); if (e.device?.vendorId === VID) toast(makeT(live.current.lang)("connected", { name: name(e.device) }), "ok"); };
    const onDisconnect = (e) => { refresh(); if (e.device?.vendorId === VID) toast(makeT(live.current.lang)("disconnected", { name: name(e.device) }), "warn"); };
    navigator.hid.addEventListener("connect", onConnect);
    navigator.hid.addEventListener("disconnect", onDisconnect);
    return () => { navigator.hid.removeEventListener("connect", onConnect); navigator.hid.removeEventListener("disconnect", onDisconnect); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // keep a valid selection as the device set changes
  useEffect(() => {
    setCurrentPid((prev) => {
      if (prev != null && devicesByPid.has(prev)) return prev;
      const pids = [...devicesByPid.keys()];
      if (!pids.length) return null;
      if (store.lastPid && devicesByPid.has(store.lastPid)) return store.lastPid;
      if (devicesByPid.has(DEFAULT_PID)) return DEFAULT_PID;
      return pids.sort((a, b) => a - b)[0];
    });
  }, [devicesByPid]);

  // jump to the matching menu when the selected device changes
  useEffect(() => {
    const d = getDevice(currentPid);
    if (d) setTab(d.category === "keyboard" ? "keyboard" : "mouse");
  }, [currentPid]);

  // read Hz + battery/dpi/fw/serial when the selected device changes
  useEffect(() => {
    const pid = currentPid;
    if (pid == null) { setHz(null); setInfo(null); setReading(false); return; }
    let alive = true;
    setInfo(null); setReading(true);
    const cands = live.current.devicesByPid.get(pid), dev = getDevice(pid);
    (async () => {
      const h = await readHz(cands, pid, dev);
      if (alive) setHz(h);
      const inf = await readInfo(cands, pid, dev);
      if (!alive) return;
      setInfo(inf); setReading(false);
      if (inf.dpi) setDpiText((prev) => prev || String(inf.dpi[0]));
    })();
    return () => { alive = false; };
  }, [currentPid]); // eslint-disable-line react-hooks/exhaustive-deps

  // live poll: re-read Hz + DPI every 3s for mice, so external changes show up.
  // Self-scheduling (no overlap) and paused while the tab is hidden.
  useEffect(() => {
    const pid = currentPid;
    if (pid == null || getDevice(pid)?.category !== "mouse") return;
    let alive = true, timer;
    const tick = async () => {
      if (!document.hidden) await refreshLive(pid);
      if (alive) timer = setTimeout(tick, 3000);
    };
    timer = setTimeout(tick, 3000);
    return () => { alive = false; clearTimeout(timer); };
  }, [currentPid]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- derived view data ---
  const pids = [...devicesByPid.keys()].sort((a, b) => a - b);
  const dev = currentPid != null ? getDevice(currentPid) : null;
  const multi = dev && dev.method !== "custom" && dev.method !== "logo";   // single-LED can't wave/react
  // split the per-LED editor into a Keyboard card and a Mouse card by device type
  const cat = dev?.category;
  const matrix = matrixFor(currentPid);
  const layout = layoutFor(matrix);
  const zones = zonesFor(currentPid);
  const showKb = !dev || cat === "keyboard";
  const showMouse = !dev || cat !== "keyboard";
  const mouseGrid = !!(matrix && dev && cat !== "keyboard");   // real mouse/accessory underglow strip
  const isBlade = !!(dev && dev.name.includes("Blade"));       // laptop: fan/perf/charge
  const bladeVerified = currentPid === 0x02b7;                 // Blade 16 2024 (razerctl-verified)
  const metaBase = currentPid == null ? "" : dev
    ? `method ${dev.method} · txn 0x${dev.txn.toString(16)} · led 0x${dev.led.toString(16)}`
    : "unknown model · falls back to custom / txn 3f";
  const metaText = metaBase + (hz ? `  ·  ${hz} Hz` : "");
  let infoText = "";
  if (reading) infoText = t("reading");
  else if (info) {
    const bits = [];
    if (info.battery != null) bits.push(`🔋 ${info.battery}%${info.charging ? " ⚡" : ""}`);
    if (info.dpi) bits.push(`${info.dpi[0]}×${info.dpi[1]} dpi`);
    if (info.fw) bits.push(`fw ${info.fw}`);
    if (info.serial) bits.push(info.serial);
    infoText = bits.join("  ·  ");
  }

  // three menus total: everything for a device type lives in ONE place.
  // help & advanced is a fixed section at the bottom of the page, not a tab.
  const tabs = [
    ["keyboard", t("tabKeyboard")],
    ["mouse", t("tabMouse")],
    ["profiles", t("tabProfiles")],
  ];
  const activeTab = tabs.some(([k]) => k === tab) ? tab : "keyboard";

  const commitText = (raw) => {
    try { const c = parseColor(raw); setColor(c); applyNow("static", c); }
    catch (e) { setStatus(e.message, "err"); toast(e.message, "err"); }
  };
  const setSlider = (i, v) => { const next = rgb.slice(); next[i] = clamp(v); setColor(next, { apply: true }); };

  const fxBtn = "fx rounded-md bg-neutral-800/60 hover:bg-neutral-700/80 border border-neutral-700 hover:border-emerald-500/50 px-2 py-2.5 text-xs font-semibold";
  const chan = [["R", "#ef4444"], ["G", "#22c55e"], ["B", "#3b82f6"]];

  return (
    <>
      <div id="toasts" className="pointer-events-none fixed bottom-4 right-4 z-40 flex w-80 max-w-[90vw] flex-col gap-2">
        {toasts.map((tt) => (
          <div key={tt.id} className={"toast-in pointer-events-auto rounded-lg border px-4 py-3 text-sm shadow-xl " + (
            tt.kind === "err" ? "border-red-500/40 bg-red-950/80 text-red-100"
            : tt.kind === "warn" ? "border-amber-500/40 bg-amber-950/80 text-amber-100"
            : "border-emerald-500/40 bg-emerald-950/80 text-emerald-100")}>{tt.msg}</div>
        ))}
      </div>

      {sponsor && (
        <div id="sponsor" className="fixed top-4 right-4 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-white/10 bg-neutral-900/95 p-4 pr-9 shadow-2xl shadow-black/40">
          <button onClick={() => setSponsor(false)} aria-label="Close" className="absolute top-2.5 right-2.5 grid h-6 w-6 place-items-center rounded-md text-neutral-500 hover:bg-white/10 hover:text-neutral-200 transition">
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l8 8M14 6l-8 8" /></svg>
          </button>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-pink-500/15 text-pink-400 ring-1 ring-pink-500/30">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7-4.5-9.5-9C1 9 2.5 5.5 6 5.5c2 0 3.2 1.2 4 2.3.8-1.1 2-2.3 4-2.3 3.5 0 5 3.5 3.5 6.5C19 16.5 12 21 12 21z" /></svg>
            </span>
            <p className="text-sm font-bold text-neutral-100">{t("sponsorTitle")}</p>
          </div>
          <p className="text-xs leading-relaxed text-neutral-400">{t("sponsorBody")}</p>
          <a href="https://github.com/sponsors/HamzaYslmn" target="_blank" rel="noopener"
             className="mt-3 flex items-center justify-center gap-2 rounded-lg bg-pink-500 hover:bg-pink-400 px-3 py-2 text-sm font-bold text-black transition">
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7-4.5-9.5-9C1 9 2.5 5.5 6 5.5c2 0 3.2 1.2 4 2.3.8-1.1 2-2.3 4-2.3 3.5 0 5 3.5 3.5 6.5C19 16.5 12 21 12 21z" /></svg>
            <span>{t("sponsorBtn")}</span>
          </a>
        </div>
      )}

      <main className="mx-auto w-full max-w-4xl">
        <header className="mb-6 flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-black ring-1 ring-white/10">
            <img src={logo} alt="RazerKit" className="h-full w-full object-cover" />
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold tracking-tight text-neutral-100">RazerKit</h1>
            <p className="text-xs text-neutral-500">{t("headerSub")}</p>
          </div>
          <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language" className="shrink-0 rounded-lg bg-neutral-800/80 border border-neutral-700 px-2 py-1.5 text-xs font-semibold focus:border-emerald-500 focus:outline-none">
            <option value="en">EN</option>
            <option value="tr">TR</option>
          </select>
        </header>

        {!pids.length && (
        <ol className="mb-6 grid grid-cols-3 gap-2.5">
          {[["step1", "step1d"], ["step2", "step2d"], ["step3", "step3d"]].map(([s, d], i) => (
            <li key={s} className="step rounded-lg border border-white/5 bg-neutral-900/50 px-3 py-2.5">
              <p className="text-xs font-semibold text-neutral-200">
                <span className="mr-1.5 font-mono text-emerald-500">{i + 1}.</span>{t(s)}
              </p>
              <p className="hidden text-[11px] text-neutral-500 sm:block">{t(d)}</p>
            </li>
          ))}
        </ol>
        )}

        {!HID && <div {...html(t("unsupported"))} className="mb-6 rounded-xl border border-red-800/60 bg-red-950/40 p-4 text-sm text-red-300" />}

        <fieldset disabled={!HID} className="contents">
        {/* device bar -- always on top */}
        <div className="panel rounded-xl border border-white/5 bg-neutral-900/85 p-4 sm:p-5 shadow-lg shadow-black/20">
              <section>
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("s1Title")}</span>
                  <span className="tip"><svg className="h-3.5 w-3.5 text-neutral-600" viewBox="0 0 20 20" fill="currentColor"><path d="M10 2a8 8 0 100 16 8 8 0 000-16zm.9 12H9.1v-1.8h1.8V14zm0-3H9.1V6h1.8v5z" /></svg>
                    <span {...html(t("s1Tip"))} className="tip-body" /></span>
                </div>
                <div className="flex items-center gap-2.5">
                  <div className="relative flex-1">
                    <select value={currentPid ?? ""} onChange={(e) => { const p = +e.target.value; setCurrentPid(p); reflect(p); }}
                            className="w-full appearance-none rounded-lg bg-neutral-800/80 border border-neutral-700 pl-9 pr-8 py-2.5 text-sm focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 focus:outline-none">
                      {!pids.length && <option value="">{t("noDevices")}</option>}
                      {pids.map((p) => {
                        const d = getDevice(p), star = p === DEFAULT_PID ? " ★" : "";
                        return <option key={p} value={p}>{(d ? d.name : "unknown model") + ` (1532:${hex4(p)})` + star}</option>;
                      })}
                    </select>
                    <span className={"pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-2 w-2 rounded-full " + (pids.length ? "bg-emerald-400 pulse-dot" : "bg-neutral-600")} />
                    <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-500" viewBox="0 0 20 20" fill="currentColor"><path d="M5.5 7.5 10 12l4.5-4.5" /></svg>
                  </div>
                  <button onClick={connect} className="rounded-lg bg-emerald-500 hover:bg-emerald-400 px-4 py-2.5 text-sm font-bold text-black transition">{t("connect")}</button>
                </div>
                <p className="mt-2 text-[11px] font-mono text-neutral-500">{metaText}</p>
                <p className="mt-1 text-[11px] font-mono text-emerald-400/80">{infoText}</p>
              </section>
        </div>

        {/* tab bar -- every feature area is always visible */}
        <nav role="tablist" className="mt-5 flex flex-wrap border-b border-white/10">
          {tabs.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={activeTab === k} onClick={() => setTab(k)}
                    className={"-mb-px border-b-2 px-3.5 py-2 text-sm font-semibold transition " +
                      (activeTab === k ? "border-emerald-500 text-neutral-100"
                                       : "border-transparent text-neutral-500 hover:text-neutral-200")}>
              {label}
            </button>
          ))}
        </nav>

        <div className="panel mt-4 rounded-xl border border-white/5 bg-neutral-900/85 p-5 sm:p-6 shadow-lg shadow-black/20">
          {(activeTab === "keyboard" || activeTab === "mouse") && (
          <div className="grid gap-7 lg:grid-cols-[1.55fr_1fr] lg:gap-8">
            <div className="space-y-7">
              <section>
                <div className="mb-2.5 flex items-center justify-between">
                  <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("s2Title")}</span>
                  <label className="tip flex items-center gap-2 text-xs text-neutral-400 cursor-pointer select-none">
                    <input type="checkbox" checked={save} onChange={(e) => { setSave(e.target.checked); store.save = e.target.checked; persist(); }} className="h-3.5 w-3.5 accent-emerald-500" />
                    <span>{t("saveToggle")}</span>
                    <span {...html(t("saveTip"))} className="tip-body text-left" />
                  </label>
                </div>
                <p className="mb-3 text-[11px] text-neutral-500">{t("colorHelp")}</p>

                <div className="flex gap-3">
                  <input id="picker" type="color" value={rgbToHex(rgb)} onChange={(e) => setColor(parseColor(e.target.value), { apply: true })} onBlur={() => applyNow("static", rgb)} className="h-24 w-16 shrink-0 cursor-pointer rounded-xl ring-1 ring-white/10" />
                  <div id="preview" className="relative flex-1 rounded-xl ring-1 ring-white/10 grid place-items-center min-h-24" style={{ background: rgbToHex(rgb) }}>
                    <span className="rounded-md bg-black/55 px-2 py-1 text-xs font-mono font-semibold text-white">{`${rgbToHex(rgb).toUpperCase()}  ·  rgb(${rgb.join(", ")})`}</span>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3">
                  <label className="text-[11px] text-neutral-500"><span>{t("hexLabel")}</span>
                    <div className="mt-1 flex items-center rounded-lg bg-neutral-800/80 border border-neutral-700 focus-within:border-emerald-500">
                      <span className="pl-2.5 text-neutral-500 font-mono text-sm">#</span>
                      <input type="text" maxLength={6} value={hexText} placeholder="00ff88"
                             onChange={(e) => { setHexText(e.target.value); try { setColor(parseColor(e.target.value), { fromText: true, apply: true }); } catch { /* partial */ } }}
                             onBlur={(e) => commitText(e.target.value)}
                             onKeyDown={(e) => { if (e.key === "Enter") commitText(e.target.value); }}
                             className="w-full bg-transparent px-1.5 py-2 text-sm font-mono focus:outline-none" />
                    </div>
                  </label>
                  <label className="text-[11px] text-neutral-500"><span>{t("rgbLabel")}</span>
                    <input type="text" value={rgbText} placeholder="0, 255, 136"
                           onChange={(e) => { setRgbText(e.target.value); try { setColor(parseColor(e.target.value), { fromText: true, apply: true }); } catch { /* partial */ } }}
                           onBlur={(e) => commitText(e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Enter") commitText(e.target.value); }}
                           className="mt-1 w-full rounded-lg bg-neutral-800/80 border border-neutral-700 px-3 py-2 text-sm font-mono focus:border-emerald-500 focus:outline-none" />
                  </label>
                </div>

                <div className="mt-4 space-y-2.5">
                  {chan.map(([ch, col], i) => (
                    <div key={ch} className="flex items-center gap-3">
                      <span className="w-3 text-xs font-bold" style={{ color: col }}>{ch}</span>
                      <input type="range" min={0} max={255} value={rgb[i]} onChange={(e) => setSlider(i, e.target.value)} onPointerUp={() => applyNow("static", rgb)}
                             className="flex-1" style={{ background: `linear-gradient(90deg,#171717,${col})` }} />
                      <input type="number" min={0} max={255} value={rgb[i]} onChange={(e) => setSlider(i, e.target.value)} onBlur={() => applyNow("static", rgb)}
                             className="w-16 rounded-md bg-neutral-800/80 border border-neutral-700 px-2 py-1 text-sm font-mono text-center focus:border-emerald-500 focus:outline-none" />
                    </div>
                  ))}
                </div>

                <div className="mt-4">
                  <div className="mb-1 flex items-center justify-between text-[11px] text-neutral-500">
                    <span>{t("brightnessLabel")}</span><span className="font-mono">{brightness}%</span>
                  </div>
                  <input type="range" min={0} max={100} value={brightness}
                         onChange={(e) => { const v = +e.target.value; setBrightness(v); clearTimeout(briTimer.current); briTimer.current = setTimeout(() => setBrightnessDevice(v), 500); }}
                         className="w-full" style={{ background: "linear-gradient(90deg,#171717,#fafafa)" }} />
                </div>

                <p className="mt-4 mb-2 text-[11px] text-neutral-500">{t("presets")}</p>
                <div className="grid grid-cols-4 gap-2.5 sm:grid-cols-8 lg:grid-cols-4">
                  {QUICK.map(([name, c]) => {
                    const dark = name === "white" || name === "yellow";
                    return (
                      <button key={name} onClick={() => { setColor(c); applyNow("static", c); }}
                              className={"swatch rounded-md px-2 py-3 text-xs font-bold capitalize ring-1 ring-inset ring-black/20 shadow-sm shadow-black/30 hover:ring-2 hover:ring-white/50 " + (dark ? "text-black/80" : "text-white drop-shadow")}
                              style={{ background: `rgb(${c.join(",")})` }}>{t("preset_" + name)}</button>
                    );
                  })}
                </div>
              </section>
            </div>

            {/* RIGHT: effects + status + advanced */}
            <div className="space-y-6 lg:border-l lg:border-white/5 lg:pl-8">
              <section>
                <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("s3Title")}</span>
                <p className="mt-1 mb-2.5 text-[11px] text-neutral-500">{t("effectsHelp")}</p>
                <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-5 lg:grid-cols-2">
                  {[["spectrum", null, "fxSpectrum", true], ["breathing", rgb, "fxBreathing", true],
                    ["reactive", rgb, "fxReactive", multi], ["wave", null, "fxWave", multi],
                    ["starlight", rgb, "fxStarlight", multi]].map(([act, col, key, on]) => (
                    <button key={key} onClick={() => applyNow(act, col)} disabled={!on} title={t(key + "Tip")}
                            className={fxBtn + (on ? "" : " opacity-30 cursor-not-allowed")}>
                      <span>{t(key)}</span><span className="block text-[10px] font-normal text-neutral-500">{t(key + "Sub")}</span>
                    </button>
                  ))}
                  <button onClick={() => applyNow("static", [0, 0, 0])} title={t("fxOffTip")} className="fx rounded-md bg-neutral-800/60 hover:bg-neutral-700/80 border border-neutral-700 hover:border-red-500/40 px-2 py-2.5 text-xs font-semibold">
                    <span>{t("fxOff")}</span><span className="block text-[10px] font-normal text-neutral-500">{t("fxOffSub")}</span>
                  </button>
                </div>
              </section>

            </div>
          </div>
          )}

          {activeTab === "keyboard" && showKb && matrix && (
          <section className="mt-8 border-t border-white/5 pt-6">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("kbTitle")}</span>
            <p className="mt-2.5 mb-4 text-[11px] text-neutral-500">{t("kbHelp")}</p>
            <MatrixPad matrix={matrix} layout={layout} accent={rgb} applyFrame={applyFrame} />
          </section>
          )}

          {activeTab === "keyboard" && dev?.category === "keyboard" && (
          <section className="mt-8 max-w-xl border-t border-white/5 pt-6">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("featTitle")}</span>
            <p className="mt-1 mb-3 text-[11px] leading-relaxed text-neutral-500">{t("featHelp")}</p>
            <DeviceControls category={dev.category} onScrollMode={onScrollMode} onScrollAccel={onScrollAccel}
                            onSmartReel={onSmartReel} onGameMode={onGameMode} onMacroMode={onMacroMode} />
          </section>
          )}

          {activeTab === "mouse" && showMouse && (zones || mouseGrid) && (
          <section className="mt-8 border-t border-white/5 pt-6">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("mouseTitle")}</span>
            <p className="mt-2.5 mb-4 text-[11px] text-neutral-500">{t("mouseHelp")}</p>
            {zones && <ZoneEditor zones={zones} currentPid={currentPid} accent={rgb} applyZone={applyZone} />}
            {mouseGrid && <div className={zones ? "mt-5" : ""}><MatrixPad matrix={matrix} layout={null} accent={rgb} applyFrame={applyFrame} /></div>}
          </section>
          )}

          {activeTab === "mouse" && (
          <div className="mt-8 max-w-xl border-t border-white/5 pt-6">
            <section>
              <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("perfTitle")}</span>
              <p className="mt-1 mb-3 text-[11px] leading-relaxed text-neutral-500">{t("perfHelp")}</p>
              <div className="flex items-end gap-2">
                <label className="flex-1 text-[11px] text-neutral-500"><span>{t("dpiLabel")}</span>
                  <input type="text" placeholder="1600 or 1600x800" value={dpiText}
                         onChange={(e) => setDpiText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") setDpiWeb(dpiText); }}
                         className="mt-1 w-full rounded-md bg-neutral-800/80 border border-neutral-700 px-2.5 py-1.5 text-sm font-mono focus:border-emerald-500 focus:outline-none" />
                </label>
                <button onClick={() => setDpiWeb(dpiText)} className="rounded-md bg-neutral-700 hover:bg-neutral-600 px-3 py-1.5 text-sm font-semibold">{t("setBtn")}</button>
                <label className="flex-1 text-[11px] text-neutral-500"><span>{t("pollLabel")}</span>
                  <select value={poll} onChange={(e) => { setPoll(e.target.value); if (e.target.value) setPollWeb(+e.target.value); }}
                          className="mt-1 w-full rounded-md bg-neutral-800/80 border border-neutral-700 px-2 py-1.5 text-sm focus:border-emerald-500 focus:outline-none">
                    <option value="">—</option>
                    <option value="8000">8000 Hz</option>
                    <option value="4000">4000 Hz</option>
                    <option value="2000">2000 Hz</option>
                    <option value="1000">1000 Hz</option>
                    <option value="500">500 Hz</option>
                    <option value="250">250 Hz</option>
                    <option value="125">125 Hz</option>
                  </select>
                </label>
              </div>
            </section>
            {dev?.category === "mouse" && (
              <section className="mt-8">
                <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("featTitle")}</span>
                <p className="mt-1 mb-3 text-[11px] leading-relaxed text-neutral-500">{t("featHelp")}</p>
                <DeviceControls category={dev.category} onScrollMode={onScrollMode} onScrollAccel={onScrollAccel}
                                onSmartReel={onSmartReel} onGameMode={onGameMode} onMacroMode={onMacroMode} />
              </section>
            )}
          </div>
          )}

          {activeTab === "keyboard" && isBlade && (
          <div className="mt-8 max-w-xl border-t border-white/5 pt-6">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("bladeTitle")}</span>
            <p className="mt-2.5 mb-4 text-[11px] text-neutral-500">{t("bladeHelp")}</p>
            <LaptopControls verified={bladeVerified} onPerf={onBladePerf} onCharge={onBladeCharge} />
          </div>
          )}

          {activeTab === "profiles" && (
          <div className="max-w-xl">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("profTitle")}</span>
            <div className="mt-3">
              <ProfilesCard onApply={applyProfile} getSnapshot={profileSnapshot} toast={toast} />
            </div>
          </div>
          )}

        </div>

        <div className={"mt-4 rounded-lg bg-black/20 px-3 py-2 text-sm min-h-[2.5rem] font-mono break-words " + (status.kind === "ok" ? "text-emerald-400" : status.kind === "err" ? "text-red-400" : "text-neutral-400")}>{status.msg}</div>

        {/* help & advanced -- always at the bottom, never a tab */}
        <div className="panel mt-5 rounded-xl border border-white/5 bg-neutral-900/50 p-5 sm:p-6">
          <section className="max-w-xl">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("advTitle")}</span>
            <p {...html(t("advHelp"))} className="mt-2.5 text-[11px] leading-relaxed text-neutral-500" />
            <div className="mt-3 flex gap-3">
              <label className="flex-1 text-[11px] text-neutral-500"><span>{t("txnLabel")}</span>
                <input type="text" placeholder="3f" value={txnOv} onChange={(e) => setTxnOv(e.target.value)} onBlur={() => { store.txn = txnOv.trim(); persist(); }}
                       className="mt-1 w-full rounded-md bg-neutral-800/80 border border-neutral-700 px-2.5 py-1.5 text-sm font-mono focus:border-emerald-500 focus:outline-none" />
              </label>
              <label className="flex-1 text-[11px] text-neutral-500"><span>{t("ledLabel")}</span>
                <input type="text" placeholder="04" value={ledOv} onChange={(e) => setLedOv(e.target.value)} onBlur={() => { store.led = ledOv.trim(); persist(); }}
                       className="mt-1 w-full rounded-md bg-neutral-800/80 border border-neutral-700 px-2.5 py-1.5 text-sm font-mono focus:border-emerald-500 focus:outline-none" />
              </label>
            </div>
          </section>
          <section className="mt-6 border-t border-white/5 pt-5">
            <span className="eyebrow text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{t("faqTitle")}</span>
            <div className="mt-4 grid gap-4 text-[13px] leading-relaxed text-neutral-400 sm:grid-cols-2">
              {[["faqQ1", "faqA1"], ["faqQ2", "faqA2"], ["faqQ3", "faqA3"], ["faqQ4", "faqA4"]].map(([q, a]) => (
                <div key={q}>
                  <p className="font-semibold text-neutral-200">{t(q)}</p>
                  <p {...html(t(a))} />
                </div>
              ))}
            </div>
          </section>
        </div>
        </fieldset>

        <p className="mt-4 flex flex-wrap gap-4 text-xs">
          <a href="https://github.com/HamzaYslmn/open-razerkit" className="text-neutral-500 hover:text-emerald-400 transition underline-offset-2 hover:underline">{t("linkRepo")}</a>
          <a href="https://hamzayslmn.github.io/open-razerkit/" className="text-neutral-500 hover:text-emerald-400 transition underline-offset-2 hover:underline">{t("linkLive")}</a>
          <a href="https://github.com/sponsors/HamzaYslmn" className="text-pink-400/80 hover:text-pink-400 transition underline-offset-2 hover:underline">{t("linkSponsor")}</a>
        </p>
      </main>
    </>
  );
}

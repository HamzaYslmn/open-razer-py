// Port of src/drivers/protocol.py -- builds the 90-byte Razer report sequence
// for one action. Classic script (no modules) so file:// works.

const LOGO_LED = 0x04;
const VARSTORE = 0x01, NOSTORE = 0x00, ON = 0x01, OFF = 0x00;
const ACTIONS = ["static", "off", "spectrum", "breathing", "wave"];
const METHODS = ["ext_static", "std_static", "custom", "logo"];

function razerReport(cls, id, dataSize, args, txn) {
  // One 90-byte Razer report. args start at byte 8. CRC = XOR of bytes 2..87 at byte 88.
  const r = new Uint8Array(90);
  r[1] = txn; r[5] = dataSize; r[6] = cls; r[7] = id;
  r.set(args, 8);
  let crc = 0;
  for (let i = 2; i < 88; i++) crc ^= r[i];
  r[88] = crc;
  return r;
}

const anyRGB = (rgb) => rgb && (rgb[0] || rgb[1] || rgb[2]);

// --- extended matrix (0x0F/0x02) ---------------------------------------------
function extStatic(rgb, txn, led, sv) {
  const a = new Uint8Array(9);
  a[0] = sv; a[1] = led; a[2] = 0x01; a[5] = 0x01;
  a[6] = rgb[0]; a[7] = rgb[1]; a[8] = rgb[2];
  return [razerReport(0x0F, 0x02, 0x09, a, txn)];
}
function extSimple(effect, txn, led, sv) {
  return [razerReport(0x0F, 0x02, 0x06, [sv, led, effect], txn)];
}
function extBreathing(rgb, txn, led, sv) {
  if (anyRGB(rgb)) {
    const a = new Uint8Array(9);
    a[0] = sv; a[1] = led; a[2] = 0x02; a[3] = 0x01; a[5] = 0x01;
    a[6] = rgb[0]; a[7] = rgb[1]; a[8] = rgb[2];
    return [razerReport(0x0F, 0x02, 0x09, a, txn)];
  }
  return extSimple(0x02, txn, led, sv);
}
function extWave(rgb, txn, led, sv) {
  return [razerReport(0x0F, 0x02, 0x06, [sv, led, 0x04, 0x01], txn)];
}

// --- standard matrix (0x03/0x0A) ---------------------------------------------
function stdStatic(rgb, txn, led, sv) {
  return [razerReport(0x03, 0x0A, 0x04, [0x06, rgb[0], rgb[1], rgb[2]], txn)];
}
function stdSimple(effect, txn) {
  return [razerReport(0x03, 0x0A, 0x01, [effect], txn)];
}
function stdWave(rgb, txn, led, sv) {
  return [razerReport(0x03, 0x0A, 0x02, [0x01, 0x01], txn)];
}

// --- standard LED / logo (0x03 CLASSIC effects) ------------------------------
function logoStatic(rgb, txn, led, sv) {
  led = led || LOGO_LED;
  return [razerReport(0x03, 0x01, 0x05, [sv, led, rgb[0], rgb[1], rgb[2]], txn),
          razerReport(0x03, 0x02, 0x03, [sv, led, 0x00], txn),
          razerReport(0x03, 0x00, 0x03, [sv, led, ON], txn)];
}
function logoEffect(effect, txn, led, sv) {
  led = led || LOGO_LED;
  return [razerReport(0x03, 0x02, 0x03, [sv, led, effect], txn),
          razerReport(0x03, 0x00, 0x03, [sv, led, ON], txn)];
}
function logoOff(txn, led, sv) {
  led = led || LOGO_LED;
  return [razerReport(0x03, 0x00, 0x03, [sv, led, OFF], txn)];
}

const STATIC = { ext_static: extStatic, std_static: stdStatic, custom: extStatic, logo: logoStatic };
const FAMILY = { ext_static: "ext", std_static: "std", custom: "ext", logo: "logo" };
const ANIM = {
  ext: { off: (r, t, l, s) => extSimple(0x00, t, l, s),
         spectrum: (r, t, l, s) => extSimple(0x03, t, l, s),
         breathing: extBreathing, wave: extWave },
  std: { off: (r, t, l, s) => stdSimple(0x00, t),
         spectrum: (r, t, l, s) => stdSimple(0x04, t),
         breathing: (r, t, l, s) => stdSimple(0x03, t), wave: stdWave },
  logo: { off: (r, t, l, s) => logoOff(t, l, s),
          spectrum: (r, t, l, s) => logoEffect(0x04, t, l, s),
          breathing: (r, t, l, s) => logoEffect(0x02, t, l, s),
          wave: null },
};

function buildReports(method, action, rgb, txn, led, store = true) {
  // Reports for one action. Throws for unsupported (method, action) -- e.g.
  // 'kraken' (different protocol) or 'wave' on a single-LED logo/custom zone.
  if (!METHODS.includes(method)) throw new Error(`lighting method '${method}' not implemented`);
  const sv = store ? VARSTORE : NOSTORE;
  if (action === "static") return STATIC[method](rgb || [0, 0, 0], txn, led, sv);
  if (action === "breathing" && method === "custom") txn = 0xFF; // Viper-Mini-class breathing
  if (action === "wave" && (method === "custom" || method === "logo"))
    throw new Error("wave needs a multi-zone device; this one has a single LED");
  const fn = ANIM[FAMILY[method]][action];
  if (!fn) throw new Error(`'${action}' not available for '${method}' devices`);
  return fn(rgb, txn, led, sv);
}

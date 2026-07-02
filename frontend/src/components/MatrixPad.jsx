import { useEffect, useRef, useState } from "react";
import { rgbToHex, parseColor, QUICK } from "../lib/color.js";
import { useT } from "../i18n/index.jsx";
import KeyboardLayout from "./KeyboardLayout.jsx";

// Paintable LED matrix — a labeled keyboard (when `layout` is given) or a raw
// cell grid. Shared by the keyboard editor and mouse underglow strips.
// `accent` seeds the paint color; the painter has its own picker + swatches so
// choosing a color never requires leaving this tab. applyFrame(rows) does the HID write.
export default function MatrixPad({ matrix, layout, accent, applyFrame }) {
  const t = useT();
  const rows = matrix.rows, cols = matrix.cols;
  const [paint, setPaint] = useState(accent.slice());
  const [base, setBase] = useState([0, 0, 0]);
  const [cells, setCells] = useState([]);       // flat rows*cols of [r,g,b]
  const [asKeyboard, setAsKeyboard] = useState(true);
  const painting = useRef(false);
  const applyTimer = useRef(null);

  useEffect(() => {
    setCells(Array.from({ length: rows * cols }, () => base.slice()));
  }, [rows, cols]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const up = () => { painting.current = false; };
    window.addEventListener("pointerup", up);
    return () => window.removeEventListener("pointerup", up);
  }, []);

  const toRows = (flat) => Array.from({ length: rows }, (_, r) => ({ row: r, colors: flat.slice(r * cols, (r + 1) * cols) }));
  const liveApply = (flat) => { clearTimeout(applyTimer.current); applyTimer.current = setTimeout(() => applyFrame(toRows(flat)), 250); };
  const paintCell = (i) => setCells((prev) => { const next = prev.slice(); next[i] = paint.slice(); liveApply(next); return next; });
  const paintAt = (r, c) => paintCell(r * cols + c);
  const fill = (rgb) => { const next = Array.from({ length: rows * cols }, () => rgb.slice()); setCells(next); applyFrame(toRows(next)); };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
          {t("keysBase")}
          <input type="color" value={rgbToHex(base)} onChange={(e) => setBase(parseColor(e.target.value))}
                 className="h-6 w-8 cursor-pointer rounded ring-1 ring-white/10" />
        </label>
        <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
          {t("keysAccent")}
          <input type="color" value={rgbToHex(paint)} onChange={(e) => setPaint(parseColor(e.target.value))}
                 className="h-6 w-8 cursor-pointer rounded ring-1 ring-white/10" />
        </label>
        <span className="flex items-center gap-1">
          {QUICK.map(([name, c]) => (
            <button key={name} title={name} onClick={() => setPaint(c.slice())}
                    className={"h-5 w-5 rounded-full ring-1 ring-inset ring-black/30 " +
                      (rgbToHex(paint) === rgbToHex(c) ? "outline outline-2 outline-white/70" : "hover:ring-white/50")}
                    style={{ background: rgbToHex(c) }} />
          ))}
        </span>
        <button onClick={() => fill(base)} className="rounded-md bg-neutral-700 hover:bg-neutral-600 px-2.5 py-1 text-xs font-semibold">{t("keysFill")}</button>
        <button onClick={() => applyFrame(toRows(cells))} className="rounded-md bg-emerald-600 hover:bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-black">{t("keysApply")}</button>
        {layout && (
          <button onClick={() => setAsKeyboard((v) => !v)} className="rounded-md bg-neutral-800 border border-neutral-700 hover:border-emerald-500/60 px-2.5 py-1 text-xs font-semibold">
            {asKeyboard ? t("keysViewGrid") : t("keysViewKeyboard")}
          </button>
        )}
        {matrix.guess && !layout && <span className="text-[10px] text-amber-400/80">layout is a best-guess {rows}×{cols}</span>}
        {matrix.demo && <span className="text-[10px] text-neutral-500">demo — connect a device</span>}
      </div>
      {layout && asKeyboard ? (
        <KeyboardLayout layout={layout} cells={cells} cols={cols} onPaint={paintAt} />
      ) : (
        <div className="overflow-x-auto">
          <div className="grid gap-1 w-max" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
               onPointerLeave={() => (painting.current = false)}>
            {cells.map((c, i) => (
              <button key={i}
                      onPointerDown={() => { painting.current = true; paintCell(i); }}
                      onPointerEnter={() => { if (painting.current) paintCell(i); }}
                      title={`row ${Math.floor(i / cols)}, col ${i % cols}`}
                      className="h-5 w-5 rounded-[3px] ring-1 ring-black/40 ring-inset hover:ring-white/50"
                      style={{ background: rgbToHex(c) }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

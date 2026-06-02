/* 轻录 — Claude Code terminal-panel redesign.
   A faithful re-skin of the MiniRecorder control panel as a warm, monospace
   terminal panel. Every function of the original is preserved:
   mode / quality / source pickers, record-stop, pause, open-dir, settings, pin. */

const { useState, useEffect, useRef, useCallback } = React;

/* ---------- data ---------- */
const MODES = [
  { v: "fullscreen", label: "全屏" },
  { v: "window", label: "窗口" },
  { v: "custom", label: "自定义" },
];
const QUALITY = [
  { v: "ultra", label: "超高清", meta: "10M · 60fps" },
  { v: "high", label: "高清", meta: "6M · 60fps" },
  { v: "medium", label: "标清", meta: "6M · 30fps" },
  { v: "low", label: "流畅", meta: "3M · 30fps" },
  { v: "custom", label: "自定义", meta: "" },
];
const SCREENS = [
  { v: "s1", label: "屏幕1", meta: "1920×1080 · 主屏" },
  { v: "s2", label: "屏幕2", meta: "2560×1440" },
  { v: "all", label: "全部屏幕", meta: "4480×1440" },
];
const WINDOWS = [
  { v: "w1", label: "GameClient.exe", meta: "1600×900" },
  { v: "w2", label: "Unreal Editor", meta: "2048×1152" },
  { v: "w3", label: "Visual Studio", meta: "1920×1040" },
  { v: "w4", label: "Chrome — localhost", meta: "1440×900" },
];

/* ---------- tiny glyphs drawn with CSS, not emoji ---------- */
function RecGlyph() { return <span className="g-rec" />; }
function StopGlyph() { return <span className="g-stop" />; }
function PauseGlyph() { return <span className="g-pause"><i /><i /></span>; }
function PlayGlyph() { return <span className="g-play" />; }
function Folder() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M1.5 4.2c0-.5.4-.9.9-.9h3.1c.3 0 .6.1.8.4l.7.9h6.6c.5 0 .9.4.9.9v6.3c0 .5-.4.9-.9.9H2.4c-.5 0-.9-.4-.9-.9V4.2Z"
        stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  );
}
function Gear() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="2.1" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 1.4v1.8M8 12.8v1.8M14.6 8h-1.8M3.2 8H1.4M12.7 3.3l-1.3 1.3M4.6 11.4l-1.3 1.3M12.7 12.7l-1.3-1.3M4.6 4.6 3.3 3.3"
        stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- dropdown ---------- */
function Flag({ flag, options, value, onChange, width, open, setOpen, id }) {
  const cur = options.find((o) => o.v === value) || options[0];
  const isOpen = open === id;
  return (
    <div className="row">
      <span className="flag">{flag}</span>
      <div className="sel-wrap" style={{ width }}>
        <button
          className={"sel" + (isOpen ? " on" : "")}
          onClick={(e) => { e.stopPropagation(); setOpen(isOpen ? null : id); }}
        >
          <span className="sel-val">{cur.label}</span>
          {cur.meta ? <span className="sel-meta">{cur.meta}</span> : null}
          <span className="caret">▾</span>
        </button>
        {isOpen && (
          <div className="menu" onClick={(e) => e.stopPropagation()}>
            {options.map((o) => (
              <button
                key={o.v}
                className={"opt" + (o.v === value ? " sel" : "")}
                onClick={() => { onChange(o.v); setOpen(null); }}
              >
                <span className="opt-dot">{o.v === value ? "›" : " "}</span>
                <span className="opt-label">{o.label}</span>
                {o.meta ? <span className="opt-meta">{o.meta}</span> : null}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function pad(n) { return String(n).padStart(2, "0"); }
function fmt(s) { return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`; }

/* ---------- the recorder window ---------- */
function RecorderWindow({ theme, accent, font, ascii }) {
  const [mode, setMode] = useState("fullscreen");
  const [quality, setQuality] = useState("high");
  const [screen, setScreen] = useState("s1");
  const [win, setWin] = useState("w1");
  const [rec, setRec] = useState("idle"); // idle | recording | paused
  const [elapsed, setElapsed] = useState(0);
  const [pinned, setPinned] = useState(false);
  const [open, setOpen] = useState(null);
  const [saved, setSaved] = useState(null);

  useEffect(() => {
    if (rec !== "recording") return;
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [rec]);

  // close dropdowns on outside click
  const rootRef = useRef(null);
  useEffect(() => {
    const h = () => setOpen(null);
    document.addEventListener("click", h);
    return () => document.removeEventListener("click", h);
  }, []);

  const toggleRec = () => {
    if (rec === "idle") { setElapsed(0); setSaved(null); setRec("recording"); }
    else {
      const mb = (elapsed * 1.7 + 4.2).toFixed(1);
      setSaved(`录制_2026-06-02.mp4 · ${mb} MB`);
      setRec("idle");
    }
  };
  const togglePause = () => {
    if (rec === "recording") setRec("paused");
    else if (rec === "paused") setRec("recording");
  };

  const isRec = rec !== "idle";
  const statusWord = rec === "recording" ? "recording" : rec === "paused" ? "paused" : "idle";

  const vars = {
    ...THEMES[theme],
    "--accent": accent,
    "--mono": `'${font}', ui-monospace, 'SF Mono', Menlo, monospace`,
  };

  return (
    <div className="win" style={vars} ref={rootRef} data-screen-label={"recorder-" + theme}>
      {/* title bar */}
      <div className="bar">
        <div className="bar-l">
          <span className="logo"><span className="logo-dot" /></span>
          <span className="brand">轻录</span>
          <span className="brand-sub">recorder</span>
        </div>
        <div className="bar-r">
          <button
            className={"wc pin" + (pinned ? " on" : "")}
            onClick={() => setPinned((p) => !p)}
            title="置顶"
          >置顶</button>
          <button className="wc" title="最小化">—</button>
          <button className="wc x" title="关闭">✕</button>
        </div>
      </div>

      <div className="body">
        {/* prompt / status line */}
        <div className={"prompt s-" + statusWord}>
          <span className="ps1">$</span>
          <span className="cmd">rec --status</span>
          <span className="status">
            <span className={"sdot d-" + statusWord} />
            <span className="sword">{statusWord}</span>
            {!isRec && <span className="caret-blink">▋</span>}
          </span>
          <span className="clock">{fmt(elapsed)}</span>
        </div>

        {ascii && <div className="rule">{"────────────────────────────────"}</div>}

        {/* config flags */}
        <div className="config">
          <Flag flag="--mode" id="mode" options={MODES} value={mode}
            onChange={setMode} open={open} setOpen={setOpen} />
          <Flag flag="--quality" id="quality" options={QUALITY} value={quality}
            onChange={setQuality} open={open} setOpen={setOpen} />
          {mode === "fullscreen" && (
            <Flag flag="--source" id="src" options={SCREENS} value={screen}
              onChange={setScreen} open={open} setOpen={setOpen} />
          )}
          {mode === "window" && (
            <Flag flag="--source" id="src" options={WINDOWS} value={win}
              onChange={setWin} open={open} setOpen={setOpen} />
          )}
          {mode === "custom" && (
            <div className="row">
              <span className="flag">--region</span>
              <button className="sel region">
                <span className="sel-val">960 × 540</span>
                <span className="sel-meta">@ 200,200</span>
                <span className="edit">编辑 ✎</span>
              </button>
            </div>
          )}
        </div>

        {ascii && <div className="rule dim">{"· · · · · · · · · · · · · · · · ·"}</div>}

        {/* primary action */}
        <button
          className={"record" + (isRec ? " stop" : "")}
          style={isRec ? { background: "var(--inset)", color: "var(--t1)", borderColor: "var(--line2)", boxShadow: "none" } : undefined}
          onClick={toggleRec}
        >
          <span className="rec-ico">{isRec ? <StopGlyph /> : <RecGlyph />}</span>
          <span className="rec-label">{isRec ? "停止录制" : "开始录制"}</span>
          <kbd className="kc" style={isRec ? { background: "color-mix(in srgb, var(--t1) 7%, transparent)", borderColor: "var(--line2)", color: "var(--t2)" } : undefined}>F9</kbd>
        </button>

        {/* footer controls */}
        <div className="footer">
          <button className={"fbtn" + (isRec ? "" : " off")} disabled={!isRec} onClick={togglePause}>
            {rec === "paused" ? <PlayGlyph /> : <PauseGlyph />}
            <span>{rec === "paused" ? "继续" : "暂停"}</span>
            <kbd className="kc sm">F10</kbd>
          </button>
          <div className="fgap" />
          <button className="fbtn"><Folder /><span>输出</span></button>
          <button className="fbtn"><Gear /><span>设置</span></button>
        </div>

        {/* save toast line */}
        <div className={"saveline" + (saved ? " show" : "")}>
          {saved ? <><span className="ok">✓ saved</span><span className="savemeta">{saved}</span></> : null}
        </div>
      </div>
    </div>
  );
}

/* ---------- theme token sets (CSS vars) ---------- */
const THEMES = {
  light: {
    "--bg": "#FAF9F5", "--panel": "#F1EFE7", "--inset": "#FFFFFF",
    "--line": "#E5E2D7", "--line2": "#D8D4C6",
    "--t1": "#2B2925", "--t2": "#6F6B61", "--t3": "#A8A395",
    "--ink": "#FFFFFF", "--shadow": "0 14px 40px -16px rgba(60,52,38,.34), 0 2px 8px -3px rgba(60,52,38,.18)",
    "--barbg": "#EDEAE1", "--menubg": "#FFFFFF",
  },
  dark: {
    "--bg": "#1A1815", "--panel": "#221F19", "--inset": "#2A2620",
    "--line": "#343027", "--line2": "#3D3830",
    "--t1": "#ECE9E0", "--t2": "#A6A092", "--t3": "#706B5F",
    "--ink": "#1A1512", "--shadow": "0 18px 48px -18px rgba(0,0,0,.6), 0 2px 10px -4px rgba(0,0,0,.5)",
    "--barbg": "#201D17", "--menubg": "#262219",
  },
};

/* ---------- page: two instances side by side ---------- */
function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const accent = Array.isArray(t.accent) ? t.accent[0] : t.accent;
  return (
    <div className="stage">
      <div className="head">
        <div className="kicker">轻录 · 重新皮肤化</div>
        <h1>Claude Code 风格 · 终端控制面板</h1>
        <p className="lede">
          同一套设计，浅色（暖奶油）与深色（暖棕）两种主题并排对比。每个窗口都可交互——
          点击 <b>开始录制</b> 计时，切换 <b>--mode</b> 看来源选择器变化，打开下拉、置顶、暂停都能用。
        </p>
      </div>

      <div className="grid">
        <figure className="cell">
          <figcaption><span className="tag light">浅色 / Light</span><span className="hex">{THEMES.light["--bg"]}</span></figcaption>
          <RecorderWindow theme="light" accent={accent} font={t.font} ascii={t.ascii} />
        </figure>
        <figure className="cell">
          <figcaption><span className="tag dark">深色 / Dark</span><span className="hex">{THEMES.dark["--bg"]}</span></figcaption>
          <RecorderWindow theme="dark" accent={accent} font={t.font} ascii={t.ascii} />
        </figure>
      </div>

      <div className="legend">
        <span><i className="lg-mono" />等宽 {t.font}</span>
        <span><i className="lg-acc" style={{ background: accent }} />主色 {accent}</span>
        <span>CLI flag 配置行 · 提示符 + 光标 · 键帽提示</span>
      </div>

      <TweaksPanel>
        <TweakSection label="外观" />
        <TweakColor label="主色 / 录制色" value={t.accent}
          options={["#D97757", "#C84A38", "#B8863F", "#6E8B6E"]}
          onChange={(v) => setTweak("accent", v)} />
        <TweakSelect label="等宽字体" value={t.font}
          options={["IBM Plex Mono", "JetBrains Mono", "Space Mono", "DM Mono"]}
          onChange={(v) => setTweak("font", v)} />
        <TweakToggle label="ASCII 装饰线" value={t.ascii}
          onChange={(v) => setTweak("ascii", v)} />
      </TweaksPanel>
    </div>
  );
}

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#D97757",
  "font": "IBM Plex Mono",
  "ascii": true
}/*EDITMODE-END*/;

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

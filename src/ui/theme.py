"""Design tokens for the Claude-Code terminal-panel skin.

Two themes (warm cream light / warm brown dark) mirroring the prototype's
THEMES object in 轻录-prototype/app.jsx. Tokens drive both the QSS for the
main window and the QPainter colors used by the custom widgets, so a theme
switch only needs new token dicts + a repaint.
"""
from __future__ import annotations

# Brand constants — shared by both themes.
ACCENT = "#D97757"          # Claude clay-orange: flags, record action, focus
ACCENT_HOVER = "#E2856A"    # brightened accent for hover
CLOSE_RED = "#E0303A"       # close button hover only
PAUSED = "#D99A30"          # paused amber
OK_GREEN = "#5A9B6B"        # "saved" confirmation

# Monospace stack — bundled IBM Plex Mono first, then Windows system monos.
MONO_FAMILIES = ["IBM Plex Mono", "Cascadia Mono", "Consolas", "Courier New"]
MONO_CSS = ", ".join(f"'{f}'" for f in MONO_FAMILIES) + ", monospace"

# Per-theme token sets. Keys match the prototype CSS vars (minus the `--`).
TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1A1815", "panel": "#221F19", "inset": "#2A2620",
        "line": "#343027", "line2": "#3D3830",
        "t1": "#ECE9E0", "t2": "#A6A092", "t3": "#706B5F",
        "ink": "#1A1512",                 # text/glyph drawn ON the accent button
        "barbg": "#201D17", "menubg": "#262219",
        "hover": "rgba(255,255,255,0.06)",
        "press": "rgba(255,255,255,0.10)",
        "sel_bg": "#382C24",              # accent ~8% over inset
        "pin_bg": "rgba(217,119,87,0.18)",
        "pin_border": "rgba(217,119,87,0.50)",
        "keycap_bg": "rgba(255,255,255,0.05)",
        "keycap_border": "#3D3830",
        "accent": ACCENT, "accent_hover": ACCENT_HOVER,
        "close": CLOSE_RED, "paused": PAUSED, "ok": OK_GREEN,
    },
    "light": {
        "bg": "#FAF9F5", "panel": "#F1EFE7", "inset": "#FFFFFF",
        "line": "#E5E2D7", "line2": "#D8D4C6",
        "t1": "#2B2925", "t2": "#6F6B61", "t3": "#A8A395",
        "ink": "#FFFFFF",
        "barbg": "#EDEAE1", "menubg": "#FFFFFF",
        "hover": "rgba(0,0,0,0.045)",
        "press": "rgba(0,0,0,0.075)",
        "sel_bg": "#FCF4F1",              # accent ~8% over white
        "pin_bg": "rgba(217,119,87,0.16)",
        "pin_border": "rgba(217,119,87,0.45)",
        "keycap_bg": "rgba(0,0,0,0.04)",
        "keycap_border": "#D8D4C6",
        "accent": ACCENT, "accent_hover": ACCENT_HOVER,
        "close": CLOSE_RED, "paused": PAUSED, "ok": OK_GREEN,
    },
}


def tokens(name: str) -> dict[str, str]:
    return TOKENS.get(name, TOKENS["dark"])


def build_qss(t: dict[str, str]) -> str:
    """Stylesheet for the main window + its QSS-styled custom widgets.

    Painted parts (record glyph, status dot, logo) read tokens directly; this
    covers the card surface, title-bar buttons, flag rows, popup and footer.
    """
    return f"""
    /* ---- card surface ---- */
    #card {{
        background-color: {t['bg']};
        border: 1px solid {t['line']};
        border-radius: 12px;
    }}
    #titleBar {{
        background-color: {t['barbg']};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border-bottom: 1px solid {t['line']};
    }}
    QLabel {{ background: transparent; }}

    /* ---- title bar text ---- */
    #brand {{ color: {t['t1']}; font-size: 13px; font-weight: 700; }}
    #brandSub {{ color: {t['t3']}; font-size: 11px; }}

    /* ---- window control buttons (theme / pin / min / close) ---- */
    QPushButton[wc="true"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 5px; color: {t['t2']};
        font-size: 12px; padding: 0;
    }}
    QPushButton[wc="true"]:hover {{ background: {t['hover']}; color: {t['t1']}; }}
    QPushButton[wc="true"]:pressed {{ background: {t['press']}; }}
    QPushButton#pinBtn:checked {{
        background: {t['pin_bg']}; border-color: {t['pin_border']};
        color: {t['accent']};
    }}
    QPushButton#closeBtn:hover {{ background: {t['close']}; color: #ffffff; }}

    /* ---- prompt / status line ---- */
    #ps1 {{ color: {t['accent']}; font-weight: 700; }}
    #cmd {{ color: {t['t2']}; }}
    #statusWord {{ color: {t['t1']}; font-weight: 600; }}
    #statusWord[state="recording"] {{ color: {t['accent']}; }}
    #statusWord[state="paused"]    {{ color: {t['paused']}; }}
    #statusWord[state="ok"]        {{ color: {t['ok']}; }}
    #clock {{ color: {t['t2']}; }}
    #clock[state="recording"] {{ color: {t['t1']}; }}
    #caret {{ color: {t['accent']}; }}
    #rule {{ color: {t['line2']}; }}

    /* ---- flag label + dropdown (value box is a QFrame[sel]) ---- */
    #flag {{ color: {t['accent']}; font-weight: 500; }}
    QFrame[sel="true"] {{
        background-color: {t['inset']};
        border: 1px solid {t['line']};
        border-radius: 7px;
    }}
    QFrame[sel="true"]:hover {{ border-color: {t['line2']}; }}
    QFrame[sel="true"][open="true"] {{
        border-color: {t['accent']}; background-color: {t['sel_bg']};
    }}

    /* ---- mini refresh button ---- */
    QPushButton[mini="true"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 6px; color: {t['t3']}; font-size: 13px;
    }}
    QPushButton[mini="true"]:hover {{ background: {t['hover']}; color: {t['t1']}; }}

    /* ---- footer flat buttons (inner layout handles padding) ---- */
    QPushButton[foot="true"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 7px; color: {t['t2']};
        font-size: 12px; padding: 0; text-align: left;
    }}
    QPushButton[foot="true"]:hover {{
        background: {t['hover']}; color: {t['t1']}; border-color: {t['line']};
    }}
    QPushButton[foot="true"]:disabled {{ color: {t['t3']}; }}
    """

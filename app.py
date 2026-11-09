"""Fillet (Text2CAD) - Streamlit UI.  Run:  streamlit run app.py

Landing page (centred prompt) -> after the first model is built the prompt slides to the left
and becomes a chat for follow-up fixes, the 3D preview slides in on the right. A pen tool on the
preview marks problems; marks are sent with the next chat message. Models can be saved to a
local library (sidebar) and reopened later.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

import library
import about
import config
import llm
import sandbox
import ui_art
import print_check
import share
from llm import CodeGenerator
from pipeline import MAX_REPAIRS, run_pipeline
from viewer_component import cad_viewer, describe_marks

ROOT = Path(__file__).parent
EXAMPLES = json.loads((ROOT / "examples" / "examples.json").read_text(encoding="utf-8"))

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&display=swap');
/* ---- palette: near-black, warm off-white ink, one sage accent, clay for marks ---- */
:root {
  --bg: #0E0E0D; --surface: #171716; --surface-2: #1F1F1D; --line: #2A2927;
  --ink: #EDEBE6; --muted: #8C8880; --accent: #6FA08E; --accent-ink: #0E0E0D;
  --clay: #D27A52; --good: #7FB394; --bad: #E07A5F;
}
html, body, [class*="css"], .stApp, button, input, textarea {font-family: 'Inter Tight', system-ui, sans-serif !important;}
.stApp {background: var(--bg);}
#MainMenu, footer, header[data-testid="stHeader"] {visibility: hidden; height: 0;}
.block-container {padding-top: 1.6rem; max-width: 1400px;}

.hero {padding: 46px 4px 28px; margin-bottom: 8px; border-bottom: 1px solid var(--line);}
.hero h1 {font-size: 2.6rem; margin: 0; letter-spacing: -.03em; font-weight: 600; color: var(--ink);}
.hero p {margin: 10px 0 0; color: var(--muted); font-size: 1.05rem; max-width: 560px; line-height: 1.5;}
.brand {font-size: 1.3rem; font-weight: 600; letter-spacing: -.02em; color: var(--ink);}
.pill {display: inline-block; padding: 2px 10px; margin: 0 6px 4px 0; border-radius: 999px; font-size: .76rem;
  color: var(--muted); border: 1px solid var(--line); background: var(--surface);}
.section {font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); margin: 22px 0 8px;}

div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {
  border-radius: 10px; border: 1px solid var(--line); background: var(--surface); color: var(--ink);
  box-shadow: none; transition: border-color .15s, background .15s; font-weight: 500;}
div[data-testid="stButton"] button:hover, div[data-testid="stDownloadButton"] button:hover {
  border-color: var(--ink); color: var(--ink); background: var(--surface);}
div[data-testid="stButton"] button[kind="primary"], div[data-testid="stDownloadButton"] button[kind="primary"] {
  background: var(--accent); color: var(--accent-ink); border-color: var(--accent); padding: .6rem 1.3rem;}
div[data-testid="stButton"] button[kind="primary"]:hover, div[data-testid="stDownloadButton"] button[kind="primary"]:hover {
  background: #86B3A2; border-color: #86B3A2; color: var(--accent-ink);}
textarea, input {border-radius: 10px !important; background: var(--surface) !important;}
textarea {font-size: 1rem !important;}

.cards {display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;}
.card {padding: 14px 16px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line);}
.card .lbl {font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted);}
.card .val {font-size: 1.25rem; font-weight: 600; margin-top: 4px; color: var(--ink); letter-spacing: -.01em;}
.card .sub {font-size: .8rem; color: var(--muted); margin-top: 2px;}
.card.good .val {color: var(--good);}
.card.bad {border-color: var(--bad);} .card.bad .val {color: var(--bad);}
.card.wide {grid-column: span 2;}
div[data-testid="stExpander"] details, div[data-testid="stStatus"] {border-radius: 12px; border-color: var(--line); background: var(--surface);}
button[data-baseweb="tab"] {font-weight: 500;}

.st-key-chatpane {background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px 14px 6px;}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {display: none;}
[data-testid="stChatMessage"] {background: transparent; padding: .4rem .2rem;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background: var(--surface-2); border-radius: 10px; padding: .6rem .8rem;}
.marks-note {font-size: .84rem; color: var(--clay); border: 1px solid var(--clay); border-radius: 8px; padding: 6px 10px; margin: 6px 0;}

.lib-thumb {background: var(--surface); border-radius: 8px; padding: 2px; border: 1px solid var(--line);}
.lib-name {font-weight: 600; font-size: .86rem; line-height: 1.25; color: var(--ink);}
.lib-sub {font-size: .72rem; color: var(--muted);}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {display: none;}

.skeleton {height: 540px; border-radius: 14px; border: 1px solid var(--line); position: relative; overflow: hidden;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: var(--surface);}
.skeleton::after {content: ""; position: absolute; inset: 0;
  background: linear-gradient(105deg, transparent 35%, rgba(111,160,142,.07) 50%, transparent 65%);
  background-size: 250% 100%; animation: t2c-shimmer 2s ease-in-out infinite;}
.skeleton.idle::after {display: none;}
@keyframes t2c-shimmer {0% {background-position: 120% 0;} 100% {background-position: -120% 0;}}
.sk-orb {width: 40px; height: 40px; border-radius: 50%; margin-bottom: 10px; border: 2px solid var(--line);
  border-top-color: var(--accent); animation: t2c-spin 1s linear infinite;}
@keyframes t2c-spin {to {transform: rotate(360deg);}}
.sk-text {font-size: 1.05rem; font-weight: 600; color: var(--ink);}
.sk-sub {font-size: .82rem; color: var(--muted);}
</style>
"""

# Played the moment "Generate" is clicked: the prompt panel glides from the centre of the page to the
# left column (spring-like ease, as on Apple devices) while the preview panel opens on the right.
# The left column is 2/5 of the width, so its centre sits 30% of the page (= 75% of itself) left of centre.
SPRING = "cubic-bezier(.22, 1, .36, 1)"
TRANSITION_CSS = f"""
<style>
@keyframes t2c-to-left {{
  0%   {{transform: translateX(75%); opacity: .8;}}
  100% {{transform: none; opacity: 1;}}
}}
@keyframes t2c-open-right {{
  0%   {{transform: translateX(40px); opacity: 0;}}
  100% {{transform: none; opacity: 1; filter: none;}}
}}
.st-key-chatpane {{animation: t2c-to-left 1.05s {SPRING} both;}}
.st-key-previewpane {{animation: t2c-open-right 1s {SPRING} .28s both; transform-origin: left center;}}
</style>
"""
# Played when the finished model replaces the loading skeleton.
PREVIEW_IN_CSS = f"""
<style>
@keyframes t2c-model-in {{
  0% {{opacity: 0; transform: scale(.985);}}
  100% {{opacity: 1; transform: none; filter: none;}}
}}
.st-key-previewpane {{animation: t2c-model-in .9s {SPRING} both;}}
</style>
"""

DEFAULT_PRINT_CFG = {"printer": next(iter(print_check.PRINTERS)), "material": "PLA", "infill": 0.2}


# --------------------------------------------------------------------------- #
# Small rendering helpers
# --------------------------------------------------------------------------- #
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


def plain(text: str) -> str:
    """Strip emojis (e.g. from chats saved by older versions) to keep the UI minimal."""
    text = _EMOJI.sub("", text).replace("mark spots with .", "mark spots on the model with the pen.")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def card(label: str, value: str, sub: str = "", cls: str = "", wide: bool = False) -> str:
    return (f'<div class="card {cls} {"wide" if wide else ""}"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="val">{value}</div><div class="sub">{html.escape(sub)}</div></div>')


def show_metrics(m: dict) -> None:
    x, y, z = m["bbox_mm"]
    n = m["num_solids"]
    if m["is_valid"] and n == 1:
        geo = card("Geometry", "One solid piece", "watertight and ready to export or print", "good")
    elif m["is_valid"]:
        geo = card("Geometry", f"{n} separate pieces", "parts don't touch — ask in the chat to join them", "bad")
    else:
        geo = card("Geometry", "Broken surface", "the shape has gaps — ask in the chat to fix it", "bad")
    holes = m.get("holes") or []
    rounds = m.get("rounds") or []
    feat = ", ".join(f"{h['n']}× ⌀{h['d']:g}" for h in holes) or "none"
    feat_sub = ("outer ⌀ " + ", ".join(f"{r['d']:g}" for r in rounds)) if rounds else "round holes / bores detected"
    cards = [
        card("Size (width × depth × height)", f"{x:g} × {y:g} × {z:g} mm", "X × Y × Z", wide=True),
        card("Holes", feat, feat_sub),
        card("Volume", f"{m['volume_mm3'] / 1000:,.2f} cm³", f"{m['volume_mm3']:,.0f} mm³"),
        geo.replace('class="card ', 'class="card wide ', 1),
    ]
    st.markdown(f'<div class="cards">{"".join(cards)}</div>', unsafe_allow_html=True)


def svg_data_uri(path: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def drawing_preview(out_dir: Path) -> None:
    tiles = []
    for name, title in (("iso", "Isometric · 3D"), ("top", "Top · looking down (X–Y)"),
                        ("front", "Front · width × height (X–Z)"), ("side", "Side · depth × height (Y–Z)")):
        svg = out_dir / f"view_{name}.svg"
        if svg.exists():
            tiles.append(f'<div class="card"><div class="lbl">{title}</div>'
                         f'<img style="width:100%;margin-top:8px" src="{svg_data_uri(svg)}"/></div>')
    if tiles:
        st.markdown(f'<div class="cards">{"".join(tiles)}</div>', unsafe_allow_html=True)
    else:
        st.info("No drawing views could be generated for this part.")


def print_report(f: dict) -> None:
    pm = st.session_state.get("print_cfg") or DEFAULT_PRINT_CFG
    r = print_check.analyze(Path(f["stl_path"]), f["metrics"], print_check.PRINTERS[pm["printer"]],
                            pm["material"], pm["infill"])
    cards = [
        card("Fits printer", "Yes" if r["fits"] else "No", pm["printer"].split(" (")[0], "good" if r["fits"] else "bad"),
        card("Supports", "None needed" if not r["supports"] else "Likely", f"{r['overhang_pct']:g}% steep overhang",
             "good" if not r["supports"] else "bad"),
        card("Filament", f"{r['weight_g']:g} g", f"{r['filament_m']:g} m of 1.75 mm {r['material']}"),
        card("Print time", f"~{r['hours']:g} h", f"{int(pm['infill'] * 100)}% infill · rough estimate"),
    ]
    st.markdown(f'<div class="cards">{"".join(cards)}</div>', unsafe_allow_html=True)
    for w in r["warnings"]:
        st.warning(w)
    if not r["warnings"]:
        st.success("No printability problems detected.")
    if config.SERVER_MODE:
        return   # "open in my slicer" only makes sense when the app runs on your own computer
    if st.button("Open 3MF in my slicer", use_container_width=True,
                 help="Opens model.3mf with the program Windows associates with .3mf (PrusaSlicer, Bambu Studio, Cura...)"):
        try:
            os.startfile(str(Path(f["out_dir"]) / "model.3mf"))  # noqa: S606
        except (OSError, AttributeError) as e:
            st.warning(f"No application is associated with .3mf files ({e}). Download the 3MF and import it in your slicer.")


def share_panel(f: dict) -> None:
    out_dir = Path(f["out_dir"])
    st.caption("Send these to anyone: the ZIP has every format, the HTML opens in any browser with a rotatable 3D model.")
    s1, s2 = st.columns(2)
    s1.download_button("Share bundle (.zip)", share.build_zip(out_dir, f["prompt"], f["metrics"], f["code"]),
                       "fillet_model.zip", "application/zip", use_container_width=True)
    s2.download_button("Viewer page (.html)", share.build_html(out_dir / "model.stl", f["prompt"], f["metrics"]),
                       "fillet_viewer.html", "text/html", use_container_width=True)


def export_panel(f: dict) -> None:
    out_dir = Path(f["out_dir"])
    files = {
        "STEP (universal CAD)": ("model.step", "application/step"),
        "3MF (slicers, keeps mm units)": ("model.3mf", "model/3mf"),
        "STL (3D printing)": ("model.stl", "model/stl"),
        "BREP (OpenCascade)": ("model.brep", "application/octet-stream"),
        "SVG drawing (top view)": ("view_top.svg", "image/svg+xml"),
        "CadQuery script (.py)": ("model.py", "text/x-python"),
    }
    (out_dir / "model.py").write_text(f["code"], encoding="utf-8")
    available = {k: v for k, v in files.items() if (out_dir / v[0]).exists()}

    choice = st.selectbox("Format", list(available), key="fmt")
    fname, mime = available[choice]
    st.download_button(f"Download {fname}", (out_dir / fname).read_bytes(), fname, mime,
                       use_container_width=True, type="primary")

    if config.SERVER_MODE:
        st.caption("Tip: download the STEP file and open it in FreeCAD, Fusion 360, SolidWorks or Onshape.")
        return   # the buttons below act on the machine running the app, so they are local-only
    st.markdown('<div class="section">Send to your local CAD</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("Open in my CAD app", use_container_width=True,
                 help="Opens model.step with the program Windows associates with STEP files (FreeCAD, Fusion, SolidWorks...)"):
        try:
            os.startfile(str(out_dir / "model.step"))  # noqa: S606 - local single-user app
            st.success("Opened in your default STEP application.")
        except (OSError, AttributeError) as e:
            st.warning(f"No application is associated with .step files ({e}). "
                       "Install FreeCAD/Fusion or use Save to folder below.")
    if c2.button("Show files", use_container_width=True):
        try:
            os.startfile(str(out_dir))  # noqa: S606
        except (OSError, AttributeError):
            st.code(str(out_dir))

    dest = st.text_input("Save all files to folder", value=str(Path.home() / "Downloads" / "Fillet"), key="dest")
    if st.button("Save all (STEP, STL, 3MF, BREP, SVG, .py)", use_container_width=True):
        try:
            target = Path(dest)
            target.mkdir(parents=True, exist_ok=True)
            n = 0
            for p in list(out_dir.glob("model.*")) + list(out_dir.glob("view_*.svg")):
                shutil.copy2(p, target / p.name)
                n += 1
            st.success(f"Saved {n} files to {target}")
        except OSError as e:
            st.error(f"Could not save: {e}")


def library_save_panel(f: dict) -> None:
    ss = st.session_state
    default = ss.get("lib_name") or (f.get("prompt") or "My part")[:48]
    name = st.text_input("Name", value=default, key="lib_name_input")
    saved_id = ss.get("lib_id")
    c1, c2 = st.columns(2)
    if c1.button("Update in library" if saved_id else "Save to library", type="primary", use_container_width=True):
        gen = ss.get("gen")
        ss.lib_id = library.save(f, name, ss.get("chat", []), gen.messages if gen else [], saved_id)
        ss.lib_name = name
        st.toast(f"Saved “{name}” to your library")
        st.rerun()
    if saved_id and c2.button("Save as new copy", use_container_width=True):
        gen = ss.get("gen")
        ss.lib_id = library.save(f, name + " (copy)", ss.get("chat", []), gen.messages if gen else [])
        ss.lib_name = name + " (copy)"
        st.toast("Saved a new copy")
        st.rerun()


# --------------------------------------------------------------------------- #
# State + actions
# --------------------------------------------------------------------------- #
def maker_footer() -> str:
    """About-the-maker footer (edit about.py). Links without a URL are hidden."""
    links = [(label, url) for label, url in (("LinkedIn", about.LINKEDIN), ("GitHub", about.GITHUB),
                                             ("Email", f"mailto:{about.EMAIL}" if about.EMAIL else ""))
             if url]
    link_html = "".join(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{label}<span>&#8599;</span></a>'
                        for label, url in links)
    mail = f'<div class="maker-mail">{html.escape(about.EMAIL)}</div>' if about.EMAIL else ""
    return (f'<div class="maker"><div><div class="maker-k">About the maker</div>'
            f'<div class="maker-n">{html.escape(about.AUTHOR)}</div><div class="maker-r">{html.escape(about.ROLE)}</div>'
            f'<p>{html.escape(about.ABOUT)}</p></div>'
            f'<div class="maker-side"><div class="maker-links">{link_html}</div>{mail}</div></div>'
            f'<div class="foot"><span>{html.escape(about.APP_NAME)} &nbsp;·&nbsp; {html.escape(about.TAGLINE)}</span>'
            f'<span>CadQuery · sandboxed · self-repairing</span></div>')


st.set_page_config(page_title="Fillet · describe it, we'll draft it", layout="wide")
st.markdown(CSS + ui_art.CSS, unsafe_allow_html=True)
ss = st.session_state
ss.setdefault("chat", [])          # [{"role": "user"|"assistant", "content": str, "log": [str]}]
ss.setdefault("viewer_nonce", 0)

# ---- access password (server mode, optional) -------------------------------------------------
if config.APP_PASSWORD and not ss.get("authed"):
    _, gate, _ = st.columns([1, 1.2, 1])
    with gate:
        st.markdown('<div class="hero" style="display:block;border:none;padding-top:90px">'
                    '<div class="kicker"><span class="live"></span>Fillet &nbsp;·&nbsp; private demo</div>'
                    '<h1>Describe it.<br><span class="accent">We&#39;ll draft it.</span></h1></div>',
                    unsafe_allow_html=True)
        pw = st.text_input("Access password", type="password", placeholder="Access password",
                           label_visibility="collapsed")
        if st.button("Enter", type="primary", use_container_width=True) or pw:
            if pw == config.APP_PASSWORD:
                ss.authed = True
                st.rerun()
            elif pw:
                st.error("Wrong password.")
    st.stop()


@st.cache_resource
def _build_slots():
    """Shared by all visitors: limits how many CAD builds run at once (memory on small free hosts)."""
    import threading
    return threading.Semaphore(max(config.MAX_PARALLEL_BUILDS, 1))


@st.cache_resource
def _build_log() -> dict:
    """Shared across all visitors of this server: client key -> recent build timestamps."""
    return {}


def _client_key() -> str:
    try:
        h = st.context.headers
        fwd = h.get("X-Forwarded-For") or h.get("x-forwarded-for") or ""
        return fwd.split(",")[0].strip() or h.get("X-Real-Ip", "") or "local"
    except Exception:  # noqa: BLE001
        return "local"


def build_allowed() -> tuple[bool, int]:
    """Per-visitor limit on builds per hour (each build spends LLM quota). Returns (allowed, minutes_to_wait)."""
    limit = config.MAX_BUILDS_PER_HOUR
    if not limit:
        return True, 0
    now = time.time()
    log = _build_log().setdefault(_client_key(), [])
    log[:] = [t for t in log if now - t < 3600]
    if len(log) >= limit:
        return False, int((3600 - (now - log[0])) // 60) + 1
    log.append(now)
    return True, 0


def reset_workspace() -> None:
    for k in ("final", "gen", "chat", "lib_id", "lib_name", "print_cfg", "build_error", "pending", "confirm_del"):
        ss.pop(k, None)
    ss.chat = []
    ss.viewer_nonce += 1


def open_from_library(model_id: str) -> None:
    data = library.load(model_id)
    reset_workspace()
    f = data["final"]
    gen = CodeGenerator(print_mode=f.get("print_mode", False))
    if data["llm_messages"]:
        gen.messages = data["llm_messages"]
    ss.update(final=f, chat=data["chat"], gen=gen, lib_id=data["id"], lib_name=data["name"], animate=True)


def run_build(text: str, marks_text: str = "") -> bool:
    """Run the pipeline for the first prompt or a chat follow-up. Shows live progress where it is called."""
    f = ss.get("final")
    allowed, wait = build_allowed()
    if not allowed:
        ss.chat.append({"role": "assistant", "content": (
            f"This public demo allows {config.MAX_BUILDS_PER_HOUR} builds per hour per visitor. "
            f"Please try again in about {wait} min, or run Fillet locally for unlimited builds.")})
        return False
    print_mode = f["print_mode"] if f else ss.get("landing_print", False)
    gen = ss.get("gen")
    # A helper kept in the session from before a code update can miss newer methods/fields:
    # rebuild it from the current class and keep its conversation.
    if gen is None or type(gen) is not CodeGenerator or not hasattr(gen, "last_brief"):
        try:
            fresh = CodeGenerator(print_mode=print_mode)
        except RuntimeError as e:   # no API key configured
            ss.chat.append({"role": "assistant", "content": f"I can't reach an AI model yet. {e}"})
            return False
        if gen is not None and getattr(gen, "messages", None):
            fresh.messages = gen.messages
        gen = ss.gen = fresh
    slots = _build_slots()
    if not slots.acquire(blocking=False):
        with st.spinner("Another part is being drafted right now, you're next in line…"):
            slots.acquire()
    try:
        return _run_build_locked(text, marks_text, f, gen, print_mode)
    finally:
        slots.release()


def _run_build_locked(text: str, marks_text: str, f: dict | None, gen, print_mode: bool) -> bool:
    work_dir = Path(tempfile.mkdtemp(prefix="fillet_"))
    # Technical details (model switches, tracebacks) are kept in `log` for debugging but never shown;
    # the user only sees a friendly, changing status line.
    log: list[str] = []
    final, n = None, 0
    busy = False
    with st.status("Designing your part…" if not f else "Applying your change…", expanded=False) as status:
        try:
            for att in run_pipeline(text, work_dir, generator=gen, print_mode=print_mode,
                                    current_code=f["code"] if f else None, marks=marks_text):
                n += 1
                log.extend(gen.events)
                gen.events.clear()
                if att.ok and att.accepted:
                    final = att
                    log.append(f"attempt {n}: accepted")
                elif att.ok:
                    log.append(f"attempt {n}: built {att.result.metrics['bbox_mm']} but needs revision ({att.note})")
                    status.update(label="Checking dimensions and refining the design…")
                else:
                    log.append(f"attempt {n}: {(att.result.error.strip().splitlines() or ['error'])[-1][:300]}")
                    status.update(label="Fixing a problem and trying again…")
        except Exception as e:  # noqa: BLE001 - network / quota errors
            busy = True
            log.append(f"{type(e).__name__}: {str(e)[:300]}")
        status.update(label="Done" if final else "Couldn't build it", state="complete" if final else "error",
                      expanded=False)

    if final:
        res = final.result
        ss.final = {
            "code": final.code, "metrics": res.metrics, "attempts": n,
            "step": res.step_path.read_bytes(), "stl_path": str(res.stl_path),
            "out_dir": str(res.step_path.parent), "prompt": (f or {}).get("prompt", text),
            "print_mode": print_mode, "models": list(gen.used),
        }
        x, y, z = res.metrics["bbox_mm"]
        verb = "Updated the model" if f else "Here's your part"
        holes = res.metrics.get("holes") or []
        hole_txt = (" with " + ", ".join(f"{h['n']}× ⌀{h['d']:g} hole{'s' if h['n'] > 1 else ''}" for h in holes)) \
            if holes else ""
        if getattr(final, "best_effort", False):
            verb = "Here's a first draft" if not f else "Here's my best attempt at that change"
            tail = ("Some details may be simplified or not fully joined yet — tell me what to fix, "
                    "or mark the spot with the pen.")
        else:
            tail = "Check the dimensions and tell me if anything needs fixing — you can also mark spots on the model with the pen."
        summary = f"{verb}: **{x:g} × {y:g} × {z:g} mm**{hole_txt}. " + tail
        ss.viewer_nonce += 1          # fresh viewer = marks cleared
    elif busy:
        summary = "The AI service is busy right now. Please try again in a minute."
    else:
        summary = ("I couldn't apply that change, so I kept the previous model. Try rephrasing it."
                   if f else "I couldn't build a valid model from that. Try adding dimensions or simplifying it.")
    ss.chat.append({"role": "assistant", "content": summary, "log": log,
                    "brief": getattr(gen, "last_brief", "") if final else ""})
    return final is not None


# --------------------------------------------------------------------------- #
# Library: collapsible sidebar on the far right edge
# --------------------------------------------------------------------------- #
# Streamlit's own sidebar can only live on the left, so this is a fixed-position drawer.
DRAWER_CSS = """
<style>
.st-key-libtab {position: fixed; right: 0; top: 38%; z-index: 1000; width: auto !important;}
.st-key-libtab button {writing-mode: vertical-rl; padding: 18px 9px !important; min-height: 0; height: auto;
  border-radius: 10px 0 0 10px !important; border-right: none !important; background: var(--surface) !important;
  box-shadow: -4px 0 18px rgba(0,0,0,.5); letter-spacing: .08em; font-weight: 500;}
.st-key-libtab button * {writing-mode: vertical-rl;}
.st-key-libtab button:hover {transform: translateX(-3px) !important; border-color: var(--ink) !important;}
.st-key-libdrawer {position: fixed; top: 0; right: 0; height: 100vh; width: 330px !important; z-index: 1000;
  background: var(--bg); border-left: 1px solid var(--line); box-shadow: -14px 0 44px rgba(0,0,0,.6);
  padding: 20px 14px 30px; overflow-y: auto; animation: t2c-drawer .45s cubic-bezier(.22, 1, .36, 1) both;}
@keyframes t2c-drawer {from {transform: translateX(100%); opacity: .4;} to {transform: none; opacity: 1;}}
</style>
"""
# while the drawer is open: on wide screens the page makes room for it, otherwise it slides over the page
DRAWER_OPEN_CSS = "<style>@media (min-width: 1500px) {.block-container {padding-right: 350px !important;}}</style>"


def library_drawer() -> None:
    ss.setdefault("lib_open", False)
    is_open = ss.lib_open
    # always emit exactly these two elements + one container so later elements keep their positions
    st.markdown(DRAWER_CSS, unsafe_allow_html=True)
    st.markdown(DRAWER_OPEN_CSS if is_open else "<style></style>", unsafe_allow_html=True)
    with st.container(key="libdrawer" if is_open else "libtab"):
        if not is_open:
            if st.button("Library", key="lib_open_btn", help="Your saved models"):
                ss.lib_open = True
                st.rerun()
            return
        items = library.list_models()
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown(f'<div class="brand" style="font-size:1.15rem">Library</div>'
                    f'<div class="lib-sub">{len(items)} saved model{"s" if len(items) != 1 else ""}</div>',
                    unsafe_allow_html=True)
        if h2.button("Close", key="lib_close_btn", help="Close the library"):
            ss.lib_open = False
            st.rerun()
        if not items:
            st.caption("Saved models appear here. Build a part, then use **Save to library**.")
        for m in items:
            with st.container(border=True):
                c_img, c_txt = st.columns([1, 2.2], vertical_alignment="center")
                iso = Path(m["dir"]) / "view_iso.svg"
                if iso.exists():
                    c_img.markdown(f'<div class="lib-thumb"><img style="width:100%" src="{svg_data_uri(iso)}"/></div>',
                                   unsafe_allow_html=True)
                x, y, z = m["metrics"]["bbox_mm"]
                when = time.strftime("%d %b, %H:%M", time.localtime(m.get("updated", 0)))
                badge = " · print" if m.get("print_mode") else ""
                c_txt.markdown(f'<div class="lib-name">{html.escape(m["name"])}</div>'
                               f'<div class="lib-sub">{x:g} × {y:g} × {z:g} mm{badge} · {when}</div>',
                               unsafe_allow_html=True)
                b1, b2 = st.columns([3, 1])
                if b1.button("Open", key=f"open_{m['id']}", use_container_width=True):
                    open_from_library(m["id"])
                    ss.lib_open = False
                    st.rerun()
                if ss.get("confirm_del") == m["id"]:
                    if b2.button("Sure?", key=f"del_{m['id']}", type="primary", use_container_width=True,
                                 help="Click again to delete permanently"):
                        library.delete(m["id"])
                        ss.pop("confirm_del", None)
                        if ss.get("lib_id") == m["id"]:
                            ss.pop("lib_id", None)
                        st.rerun()
                elif b2.button("Delete", key=f"ask_{m['id']}", use_container_width=True, help="Delete"):
                    ss.confirm_del = m["id"]
                    st.rerun()


# --------------------------------------------------------------------------- #
# Landing page: centred prompt
# --------------------------------------------------------------------------- #
in_workspace = bool(ss.get("final") or ss.get("pending") or ss.chat)
library_drawer()

if not in_workspace:
    _, mid, _ = st.columns([1, 6, 1])
    with mid:
        st.markdown(
            f"""<div class="hero">
              <div>
                <div class="kicker"><span class="live"></span>Fillet &nbsp;·&nbsp; prompt to part</div>
                <h1>Describe it.<br><span class="accent">We'll draft it.</span></h1>
                <p>Plain English in, an editable CAD model out. Rotate it, measure it, mark what's wrong and fix it
                by chat, then print or export it.</p>
                <div class="specs"><span>STEP · STL · 3MF</span><span>self-checking</span><span>chat edits</span></div>
              </div>
              <div>{ui_art.HERO_DRAWING}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="section"><b>01</b>Try an example</div>', unsafe_allow_html=True)
        with st.container(key="examples"):
            cols = st.columns(len(EXAMPLES))
            for col, ex in zip(cols, EXAMPLES):
                if col.button(f"{ex['id']:02d}  {ex['name']}", key=f"ex{ex['id']}", help=ex["prompt"],
                              use_container_width=True):
                    ss["prompt"] = ex["prompt"]

        st.markdown('<div class="section"><b>02</b>Describe your part</div>', unsafe_allow_html=True)
        prompt = st.text_area(
            "Part description", key="prompt", height=110, label_visibility="collapsed",
            placeholder="e.g. a 60x40x10 mm mounting plate with four 5 mm holes 6 mm from each corner and a 20 mm center bore",
        )
        pc1, pc2, pc3, pc4 = st.columns([1.3, 2, 1, 1])
        print_mode = pc1.toggle("3D-print mode", key="landing_print",
                                help="Designs the part for FDM printing (flat base, 1.2 mm walls, few overhangs) "
                                     "and adds a print report + 3MF.")
        if print_mode:
            printer = pc2.selectbox("Printer", list(print_check.PRINTERS), key="printer")
            material = pc3.selectbox("Material", list(print_check.MATERIALS), key="material")
            infill = pc4.slider("Infill %", 5, 100, 20, step=5, key="infill") / 100
        clicked = st.button("Draft it", type="primary")
        if clicked and not prompt.strip():
            st.warning("Describe a part first, or pick an example above.")
        if clicked and prompt.strip():
            # Switch to the workspace immediately (the transition plays), then build there.
            ss.pop("gen", None)
            ss.chat = [{"role": "user", "content": prompt}]
            ss.pending = prompt
            if print_mode:
                ss.print_cfg = {"printer": printer, "material": material, "infill": infill}
            ss.animate = "enter"
            st.rerun()
        st.markdown(maker_footer(), unsafe_allow_html=True)
    st.stop()

# --------------------------------------------------------------------------- #
# Workspace: chat on the left, preview on the right
# --------------------------------------------------------------------------- #
f = ss.get("final")
anim = ss.pop("animate", None)
# Always emit this element (empty when not animating) so later elements keep their positions;
# otherwise Streamlit remounts the 3D viewer on the next rerun.
st.markdown({"enter": TRANSITION_CSS, "model": PREVIEW_IN_CSS}.get(anim, "<style></style>"), unsafe_allow_html=True)

top1, top3 = st.columns([6, 1.1])
with top1:
    pills = ""
    if (f or {}).get("print_mode") or (not f and ss.get("landing_print")):
        pills += '<span class="pill">3D-print mode</span>'
    title = ss.get("lib_name") or (f.get("prompt", "") if f else ss.get("pending", "")) or "new part"
    title = (title[:46] + "…") if len(title) > 47 else title
    st.markdown(f'<span class="brand">Fillet</span><span class="crumb"><b>/</b>{html.escape(title)}</span>'
                f'&nbsp;&nbsp;{pills}', unsafe_allow_html=True)
with top3:
    if st.button("New model", use_container_width=True):
        reset_workspace()
        st.rerun()

left, right = st.columns([2, 3], gap="large")
marks: list[dict] = []

# Right first: the viewer returns the pen marks that the chat needs.
with right:
    with st.container(key="previewpane"):
        if f:
            x, y, z = f["metrics"]["bbox_mm"]
            tab3d, tab2d = st.tabs(["3D preview", "Drawings"])
            with tab3d:
                marks = cad_viewer(Path(f["stl_path"]), model_id=f"{ss.viewer_nonce}:{f['out_dir']}",
                                   dims=f"{x:g} × {y:g} × {z:g} mm", key=f"viewer_{ss.viewer_nonce}")
            with tab2d:
                if not (Path(f["out_dir"]) / "exports.done").exists():
                    with st.spinner("Finishing the drawings…"):
                        sandbox.wait_exports(Path(f["out_dir"]))
                drawing_preview(Path(f["out_dir"]))
            show_metrics(f["metrics"])
            if f["metrics"].get("num_solids", 1) > 1:
                if st.button(f"Join the {f['metrics']['num_solids']} pieces into one solid", type="primary",
                             use_container_width=True):
                    ss.auto_msg = ("The model is made of separate pieces that don't touch. Join everything into ONE "
                                   "solid: move/extend the loose features so they overlap the main body, then union "
                                   "them. Keep all dimensions the same.")
                    st.rerun()
            if f.get("print_mode"):
                st.markdown('<div class="section">3D print report</div>', unsafe_allow_html=True)
                print_report(f)
            with st.expander("Save to library", expanded=not ss.get("lib_id")):
                library_save_panel(f)
            with st.expander("Export"):
                export_panel(f)
            with st.expander("Share"):
                share_panel(f)
        elif ss.get("pending"):
            st.markdown(f'<div class="skeleton">{ui_art.LOADER_DRAWING}<div class="sk-text">Drafting</div>'
                        '<div class="sk-sub">writing CadQuery · building the solid · checking dimensions</div></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="skeleton idle"><div class="sk-text">No model yet</div>'
                        '<div class="sk-sub">Describe the part in the chat to try again.</div></div>',
                        unsafe_allow_html=True)

with left:
    with st.container(key="chatpane"):
        history = st.container(height=600, border=False)
        with history:
            for msg in ss.chat:
                with st.chat_message(msg["role"], avatar=None):
                    st.markdown(plain(msg["content"]))
                    if msg.get("brief"):
                        with st.expander("Design notes"):
                            st.markdown(plain(msg["brief"]))
        if marks:
            st.markdown(f'<div class="marks-note">{len(marks)} mark{"s" if len(marks) > 1 else ""} on the model '
                        f'(#{", #".join(str(m["n"]) for m in marks)}) will be sent with your next message.</div>',
                        unsafe_allow_html=True)
        text = st.chat_input("Describe a fix… e.g. “make the holes 6 mm” or “fix #1”"
                             if f else "Describe your part…", disabled=bool(ss.get("pending")))
        text = text or ss.pop("auto_msg", None)   # one-click fixes (e.g. "Join pieces") arrive as chat messages

    # First build, started from the landing page: runs here so progress streams into the chat
    if ss.get("pending"):
        pending = ss.pop("pending")
        with history:
            with st.chat_message("assistant"):
                ok = run_build(pending)
        if ok:
            ss.animate = "model"
        st.rerun()

    if text:
        marks_text = describe_marks(marks, f["metrics"].get("bed_offset_z", 0.0)) if (marks and f) else ""
        shown = text + (f"\n\n_with {len(marks)} mark{'s' if len(marks) > 1 else ''}_" if marks else "")
        ss.chat.append({"role": "user", "content": shown})
        with history:
            with st.chat_message("user"):
                st.markdown(shown)
            with st.chat_message("assistant"):
                ok = run_build(text, marks_text)
        if ok and not f:
            ss.animate = "model"
        st.rerun()

# ---- about-the-maker footer under the workspace ----
st.markdown(maker_footer(), unsafe_allow_html=True)

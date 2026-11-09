"""Visual personality for the UI: a self-drawing technical drawing, mono typography, drafting-paper texture.

Kept separate from app.py so the page logic stays readable.
"""
from __future__ import annotations

# A front-view L-bracket that draws itself: outline -> hidden holes -> centre line -> dimensions -> a pen mark
# circling one hole (the same pen idea the app uses). Pure SVG + CSS, no images, no emojis.
_DRAWING = """
<svg class="t2c-art {cls}" viewBox="0 0 320 230" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g class="reg" stroke="#3a3936" stroke-width="1" fill="none">
    <path d="M8 22 V8 H22"/><path d="M298 8 H312 V22"/><path d="M8 208 V222 H22"/><path d="M298 222 H312 V208"/>
  </g>
  <path class="ink" d="M60 36 V176 H262 V154 H86 Q82 154 82 150 V36 Z" pathLength="1"/>
  <g class="hidden">
    <path d="M138 154 V176" pathLength="1"/><path d="M150 154 V176" pathLength="1"/>
    <path d="M206 154 V176" pathLength="1"/><path d="M218 154 V176" pathLength="1"/>
    <path d="M60 78 H82" pathLength="1"/><path d="M60 90 H82" pathLength="1"/>
  </g>
  <path class="centre" d="M144 146 V186 M212 146 V186" pathLength="1"/>
  <g class="dim">
    <path d="M60 182 V202 M262 182 V202 M60 196 H262" pathLength="1"/>
    <path d="M60 196 l7 -3 v6 z M262 196 l-7 -3 v6 z" class="head"/>
    <text x="161" y="214">50.0</text>
    <path d="M54 36 H34 M54 176 H34 M40 36 V176" pathLength="1"/>
    <path d="M40 36 l-3 7 h6 z M40 176 l-3 -7 h6 z" class="head"/>
    <text x="26" y="110" transform="rotate(-90 26 110)">40.0</text>
  </g>
  <ellipse class="mark" cx="212" cy="165" rx="21" ry="17" pathLength="1"/>
  <text class="tag" x="236" y="140">#1</text>
</svg>
"""
HERO_DRAWING = _DRAWING.format(cls="hero-art")
LOADER_DRAWING = _DRAWING.format(cls="loader-art")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');
:root {--mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;}

/* drafting-paper texture */
.stApp {background:
  radial-gradient(circle at 1px 1px, rgba(237,235,230,.055) 1px, transparent 0) 0 0 / 24px 24px, var(--bg);}

/* ---------- hero ---------- */
.hero {display: grid; grid-template-columns: 1.15fr 1fr; gap: 28px; align-items: center;
  padding: 36px 0 30px; border-bottom: 1px solid var(--line);}
.kicker {font-family: var(--mono); font-size: .7rem; letter-spacing: .16em; text-transform: uppercase; color: var(--muted);
  display: flex; align-items: center; gap: 10px; margin-bottom: 18px;}
.kicker .live {width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: t2c-pulse 2.4s infinite;}
@keyframes t2c-pulse {0% {box-shadow: 0 0 0 0 rgba(111,160,142,.55);} 70% {box-shadow: 0 0 0 9px rgba(111,160,142,0);}
  100% {box-shadow: 0 0 0 0 rgba(111,160,142,0);}}
.hero h1 {font-size: clamp(2.3rem, 4.4vw, 3.4rem); line-height: 1.02; letter-spacing: -.04em; font-weight: 600; margin: 0; color: var(--ink);}
.hero h1 .accent {color: var(--accent);}
.hero p {margin: 16px 0 0; color: var(--muted); font-size: 1.02rem; max-width: 470px; line-height: 1.55;}
.specs {display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 22px; font-family: var(--mono); font-size: .7rem;
  letter-spacing: .06em; color: var(--muted); text-transform: uppercase;}
.specs span::before {content: "/ "; color: var(--accent);}

/* ---------- the self-drawing drawing ---------- */
.t2c-art {width: 100%; height: auto; overflow: visible;}
.t2c-art .ink {fill: none; stroke: var(--ink); stroke-width: 1.8; stroke-linejoin: round;
  stroke-dasharray: 1; stroke-dashoffset: 1; animation: t2c-draw 1.8s cubic-bezier(.65,0,.35,1) .2s forwards;}
.t2c-art .hidden path {fill: none; stroke: #6b6862; stroke-width: 1.1; stroke-dasharray: .06 .05;
  opacity: 0; animation: t2c-fade .5s ease 1.7s forwards;}
.t2c-art .centre {fill: none; stroke: #4c4a46; stroke-width: .9; stroke-dasharray: .12 .04 .02 .04;
  opacity: 0; animation: t2c-fade .5s ease 1.9s forwards;}
.t2c-art .dim path {fill: none; stroke: var(--accent); stroke-width: 1; stroke-dasharray: 1; stroke-dashoffset: 1;
  animation: t2c-draw .9s ease 2.1s forwards;}
.t2c-art .dim .head {fill: var(--accent); stroke: none; opacity: 0; animation: t2c-fade .3s ease 2.8s forwards;}
.t2c-art text {font-family: var(--mono); font-size: 11px; fill: var(--accent); text-anchor: middle;
  opacity: 0; animation: t2c-fade .4s ease 2.8s forwards;}
.t2c-art .mark {fill: none; stroke: var(--clay); stroke-width: 1.8; stroke-dasharray: 1; stroke-dashoffset: 1;
  animation: t2c-draw .7s cubic-bezier(.65,0,.35,1) 3.2s forwards;}
.t2c-art .tag {fill: var(--clay); text-anchor: start; animation-delay: 3.7s;}
.t2c-art .reg {opacity: .9;}
@keyframes t2c-draw {to {stroke-dashoffset: 0;}}
@keyframes t2c-fade {to {opacity: 1;}}
/* the loader version redraws forever */
.loader-art {max-width: 300px;}
.loader-art .ink {animation: t2c-redraw 3.2s cubic-bezier(.65,0,.35,1) infinite;}
.loader-art .dim path {animation: t2c-redraw 3.2s ease .4s infinite;}
.loader-art .mark {animation: t2c-redraw 3.2s ease .9s infinite;}
.loader-art .hidden path, .loader-art .centre, .loader-art .dim .head, .loader-art text {opacity: .8; animation: none;}
@keyframes t2c-redraw {0% {stroke-dashoffset: 1;} 55% {stroke-dashoffset: 0;} 85% {stroke-dashoffset: 0; opacity: 1;}
  100% {stroke-dashoffset: 0; opacity: 0;}}

/* ---------- technical type ---------- */
.section {font-family: var(--mono); font-size: .68rem; letter-spacing: .16em;}
.section b {color: var(--accent); font-weight: 500; margin-right: 6px;}
.card .lbl {font-family: var(--mono); font-size: .64rem; letter-spacing: .14em;}
.card .val {font-family: var(--mono); font-weight: 500; font-size: 1.12rem; letter-spacing: -.01em;}
.card .sub {font-size: .78rem;}
.card {position: relative;}
.card::after {content: ""; position: absolute; top: 8px; right: 8px; width: 6px; height: 6px;
  border-top: 1px solid var(--line); border-right: 1px solid var(--line);}
.pill {font-family: var(--mono); font-size: .68rem; letter-spacing: .04em;}
.brand {font-weight: 600;}
.crumb {font-family: var(--mono); font-size: .8rem; color: var(--muted); margin-left: 10px;}
.crumb b {color: var(--accent); font-weight: 400; margin-right: 6px;}
.st-key-libtab button {font-family: var(--mono) !important; font-size: .72rem !important; text-transform: uppercase;}
.lib-sub {font-family: var(--mono); font-size: .66rem;}
button[data-baseweb="tab"] p {font-family: var(--mono); font-size: .76rem !important; letter-spacing: .06em; text-transform: uppercase;}

/* example buttons: numbered spec chips */
.st-key-examples button {justify-content: flex-start; text-align: left;}
.st-key-examples button p {font-size: .86rem;}

/* primary action */
div[data-testid="stButton"] button[kind="primary"] p::after {content: "  \\2192"; font-family: var(--mono);}

/* ---------- chat: role labels instead of avatars ---------- */
[data-testid="stChatMessage"] {flex-direction: column; gap: 2px; align-items: stretch; text-align: left;}
[data-testid="stChatMessage"] > div, [data-testid="stChatMessageContent"] {width: 100%; text-align: left;}
[data-testid="stChatMessageContent"] p {text-align: left;}
[data-testid="stChatMessage"] [data-testid="stExpander"] {width: 100%;}
[data-testid="stChatMessage"]::before {content: "DRAFTER"; font-family: var(--mono); font-size: .6rem;
  letter-spacing: .18em; color: var(--accent);}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])::before {content: "YOU"; color: var(--muted);}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {border-left: 2px solid var(--line);
  background: transparent; border-radius: 0; padding: .3rem .9rem;}
[data-testid="stChatInput"] textarea {font-family: var(--mono) !important; font-size: .86rem !important;}

/* ---------- loader + footer ---------- */
.sk-text {font-family: var(--mono); font-size: .78rem; font-weight: 400; letter-spacing: .18em; text-transform: uppercase;
  color: var(--accent);}
.sk-text::after {content: "_"; animation: t2c-caret 1s steps(1) infinite;}
@keyframes t2c-caret {50% {opacity: 0;}}
.sk-sub {font-family: var(--mono); font-size: .7rem;}
.foot {margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; justify-content: space-between;
  font-family: var(--mono); font-size: .64rem; letter-spacing: .14em; text-transform: uppercase; color: #55524c;}
/* ---------- about the maker ---------- */
.maker {display: grid; grid-template-columns: 1.6fr 1fr; gap: 28px; align-items: end; margin-top: 64px;
  padding: 26px 0 8px; border-top: 1px solid var(--line);}
.maker-k {font-family: var(--mono); font-size: .64rem; letter-spacing: .18em; text-transform: uppercase;
  color: var(--accent); margin-bottom: 10px;}
.maker-n {font-size: 1.35rem; font-weight: 600; letter-spacing: -.02em; color: var(--ink);}
.maker-r {font-family: var(--mono); font-size: .72rem; color: var(--muted); margin-top: 4px;}
.maker p {color: var(--muted); font-size: .92rem; line-height: 1.6; max-width: 560px; margin: 12px 0 0;}
.maker-side {display: flex; flex-direction: column; align-items: flex-end; gap: 10px;}
.maker-links {display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end;}
.maker-links a {font-family: var(--mono); font-size: .74rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--ink) !important; text-decoration: none !important; border: 1px solid var(--line);
  border-radius: 999px; padding: 7px 14px; transition: border-color .15s, color .15s;}
.maker-links a span {color: var(--accent); margin-left: 6px;}
.maker-links a:hover {border-color: var(--accent); color: var(--accent) !important;}
.maker-mail {font-family: var(--mono); font-size: .72rem; color: var(--muted);}
.foot {margin-top: 18px;}
@media (max-width: 760px) {.maker {grid-template-columns: 1fr;} .maker-side {align-items: flex-start;}
  .maker-links {justify-content: flex-start;}}
</style>
"""

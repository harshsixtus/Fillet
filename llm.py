"""LLM wrapper with automatic model failover.

Generates CadQuery code and repairs it. Several models (Groq and/or Mistral) are
tried in order: when one hits a daily quota, is not available on your plan, or
has a bad key, the next one takes over automatically. Exhausted models are
remembered (in .llm_cooldown.json) so they are not retried until their quota
resets.

Configure in .env (everything optional):
    LLM_CHAIN=groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b,mistral:mistral-small-latest
    LLM_PROVIDER=groq        # which provider's models go first when LLM_CHAIN is not set
    LLM_MODEL=...            # force this model to the front of its provider's list
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

try:  # mistralai >= 2.0
    from mistralai.client import Mistral
except ImportError:  # mistralai 1.x
    from mistralai import Mistral

load_dotenv(Path(__file__).resolve().parent / ".env")   # the project .env, wherever the app is started from


def load_streamlit_secrets() -> None:
    """On Streamlit Community Cloud, keys live in the app's Secrets. Root-level secrets normally appear as
    environment variables, but only at startup and only at the top level - so copy them over explicitly
    (also from a [section]), without overriding anything already set. Safe no-op everywhere else."""
    try:
        import streamlit as st
        items = dict(st.secrets)
    except Exception:  # noqa: BLE001 - no secrets file / not running under Streamlit
        return
    flat = {}
    for k, v in items.items():
        if isinstance(v, dict) or hasattr(v, "items"):
            flat.update({kk: vv for kk, vv in dict(v).items() if not isinstance(vv, dict)})
        else:
            flat[k] = v
    for k, v in flat.items():
        if isinstance(v, (str, int, float, bool)) and str(v).strip() and not os.environ.get(k):
            os.environ[k] = str(v).strip()


load_streamlit_secrets()

ROOT = Path(__file__).parent
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system_prompt.txt"
PRINT_ADDENDUM_PATH = ROOT / "prompts" / "print_addendum.txt"
COOLDOWN_FILE = ROOT / ".llm_cooldown.json"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
KEY_ENV = {"groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY"}
DEFAULT_MODELS = {
    "groq": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
}

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Model chain
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Backend:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider} · {self.model}"

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def build_chain() -> list[Backend]:
    """Ordered list of backends to try. Only providers that have a key are used."""
    load_streamlit_secrets()   # secrets edited in the cloud dashboard take effect without a reboot
    spec = os.environ.get("LLM_CHAIN", "").strip()
    chain: list[Backend] = []
    if spec:
        for item in spec.split(","):
            prov, _, model = item.strip().partition(":")
            if prov in KEY_ENV and model:
                chain.append(Backend(prov, model))
    else:
        first = os.environ.get("LLM_PROVIDER", "").lower()
        order = ([first] if first in KEY_ENV else []) + [p for p in KEY_ENV if p != first]
        forced = os.environ.get("LLM_MODEL") or os.environ.get("MISTRAL_MODEL")
        for prov in order:
            models = list(DEFAULT_MODELS[prov])
            if forced and prov == (first or "mistral"):
                models = [forced] + [m for m in models if m != forced]
            chain += [Backend(prov, m) for m in models]
    return [b for b in chain if os.environ.get(KEY_ENV[b.provider])]


CHAIN = build_chain()
PROVIDER = CHAIN[0].provider if CHAIN else "none"
MODEL = CHAIN[0].model if CHAIN else "none"


def _load_cooldowns() -> dict[str, float]:
    try:
        data = json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
        now = time.time()
        return {k: v for k, v in data.items() if v > now}
    except (OSError, ValueError):
        return {}


def _save_cooldown(key: str, seconds: float) -> None:
    data = _load_cooldowns()
    data[key] = time.time() + seconds
    try:
        COOLDOWN_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _short_wait_hint(message: str) -> float | None:
    """Seconds from a per-minute rate-limit hint like 'try again in 1.83s' / '450ms' / '1m2.5s', or None."""
    m = re.search(r"try again in\s+([\d.hms\s]+)", message, re.IGNORECASE)
    if not m:
        return None
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)", m.group(1)):
        total += float(num) * {"ms": 0.001, "h": 3600, "m": 60, "s": 1}[unit]
        found = True
    return total if found else None


def _retry_after_seconds(message: str, default: float = 3600) -> float:
    """Parse 'try again in 3m43.3s' / '1h2m' / '450ms' style hints (+5 s margin); fall back to `default`."""
    hint = _short_wait_hint(message)
    return default if hint is None else hint + 5


def classify(exc: Exception) -> tuple[str, float]:
    """-> (action, cooldown_seconds). 'retry' (short rate limit), 'skip' (switch model and remember),
    'next' (switch model for this request only)."""
    status = getattr(exc, "status_code", None)
    msg = str(exc)
    low = msg.lower()
    if status == 413 or "request too large" in low or "context length" in low or "too many tokens" in low:
        return "next", 0                  # this request is too big for this model; try a bigger one
    if status == 429:
        if "per day" in low or "tpd" in low or "daily" in low or "quota" in low:
            return "skip", _retry_after_seconds(msg)
        return "retry", 0
    if status in (401, 403):
        return "skip", 24 * 3600        # bad key / model not in your tier
    if status in (400, 404) and ("model" in low):
        return "skip", 24 * 3600        # model does not exist / decommissioned
    return "retry", 0


# Known CadQuery failure messages -> the concrete idiom that fixes them (sent back with the traceback).
_FIX_HINTS = [
    (("more than one wire or face is required", "no pending wires", "loft"),
     "loft() needs two or more closed sketches on ONE chain, separated by .workplane(offset=...), with no extrude in "
     "between: cq.Workplane('YZ').rect(12, 18).workplane(offset=120).rect(10, 14).loft(combine=True). "
     "Do not start a new cq.Workplane() between the sections. Easiest: use the helper "
     "h.loft_x([(x, width, height), ...]) or h.loft_z([(z, width, depth), ...]) from `import t2c as h`."),
    (("nth element of an empty list", "empty list", "no objects", "list index out of range"),
     "A selector matched nothing (e.g. .faces('>Z'), .edges(...), .vertices() on a stack without that geometry). "
     "Select on the finished solid, simplify the selector, or build the feature as its own solid "
     "(cq.Workplane('XY').box(...).translate((x, y, z))) and .union() it instead of sketching on a selected face."),
    (("fillets requires that edges be selected", "brep_api: command not done", "fillet", "chamfer"),
     "The fillet/chamfer failed: use a smaller radius (well under half the thinnest wall), select fewer edges with "
     "a BoxSelector or a simple selector like '|Z', fillet before complex unions, or drop that fillet."),
    (("standard_constructionerror", "gp_dir", "null vector", "zero"),
     "A direction or size was zero: check every dimension variable is > 0 and directions are non-zero vectors."),
    (("not valid", "isvalid"),
     "The boolean result is invalid: avoid coincident faces (make overlaps at least 0.1 mm), build simpler pieces "
     "and union them, and call .clean() after booleans."),
    (("timeout",),
     "Too slow: use fewer/simpler features (e.g. fewer array elements, no fillets on many edges)."),
]


def fix_hints(error: str) -> list[str]:
    low = (error or "").lower()
    return [hint for keys, hint in _FIX_HINTS if any(k in low for k in keys)]


def _features(items: list[dict] | None) -> str:
    """[{'d': 5, 'n': 4}] -> '4x diameter 5 mm'"""
    return ", ".join(f"{i['n']}x diameter {i['d']:g} mm" for i in (items or [])) or "none"


def extract_code(text: str) -> str:
    """Return the Python code from an LLM reply, stripping thinking tags and markdown fences."""
    text = _THINK.sub("", text or "")
    blocks = _FENCE.findall(text)
    if blocks:
        with_result = [b for b in blocks if "result" in b]
        pick = with_result[-1] if with_result else max(blocks, key=len)
        return pick.strip() + "\n"
    stripped = re.sub(r"^```(?:python|py)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip() + "\n"


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #
def _run_interruptibly(fn, tick, interval: float = 0.25):
    """Run a blocking call in a daemon thread and call `tick()` while it is in flight. If `tick` raises
    (e.g. the user pressed Stop), the exception propagates at once and the late result is simply discarded."""
    import threading

    box: dict = {}

    def work():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e

    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        tick()
        th.join(interval)
    if "error" in box:
        raise box["error"]
    return box["value"]


class CodeGenerator:
    """Holds one conversation so repair requests see the full history. The history is
    provider-agnostic, so the model can be switched mid-conversation."""

    def __init__(self, print_mode: bool = False, chain: list[Backend] | None = None):
        self.chain = chain if chain is not None else build_chain()
        if not self.chain:
            raise RuntimeError(
                "No AI key found. Locally: put GROQ_API_KEY (and/or MISTRAL_API_KEY) in .env. "
                "On Streamlit Cloud: Manage app > Settings > Secrets, e.g.  GROQ_API_KEY = \"gsk_...\"  "
                "(with quotes), then Save."
            )
        self.current: Backend = self.chain[0]
        self.used: list[str] = []          # labels of models that actually answered
        self.events: list[str] = []        # human-readable switch notices
        self.last_brief: str = ""           # design brief written before the latest code
        self.requests: list[str] = []      # the user's own words (first prompt + chat edits), for verification
        # Called several times a second while waiting for the model; the UI uses it as a heartbeat so a
        # 'Stop' click can interrupt a slow call immediately. None = just wait.
        self.tick = None
        self._clients: dict[str, object] = {}
        system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        if print_mode:
            system += PRINT_ADDENDUM_PATH.read_text(encoding="utf-8")
        self.messages: list[dict] = [{"role": "system", "content": system}]

    # -- compatibility helpers
    @property
    def model(self) -> str:
        return self.current.model

    @property
    def provider(self) -> str:
        return self.current.provider

    def _client(self, b: Backend):
        if b.provider not in self._clients:
            key = os.environ[KEY_ENV[b.provider]]
            if b.provider == "groq":
                from openai import OpenAI  # Groq exposes an OpenAI-compatible API
                self._clients[b.provider] = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
            else:
                self._clients[b.provider] = Mistral(api_key=key)
        return self._clients[b.provider]

    MAX_CHARS = 18000   # keep requests small enough for free-tier per-request limits

    def _payload(self, max_chars: int | None = None) -> list[dict]:
        """System + first request + the most recent turns, alternating roles."""
        max_chars = max_chars or self.MAX_CHARS
        msgs = self.messages
        if sum(len(m["content"]) for m in msgs) <= max_chars or len(msgs) <= 4:
            return msgs
        head = [msgs[0], dict(msgs[1])]
        head[1]["content"] += "\n\n(Some earlier attempts in this conversation are omitted.)"
        budget = max_chars - sum(len(m["content"]) for m in head)
        tail: list[dict] = []
        for m in reversed(msgs[2:]):
            if budget - len(m["content"]) < 0 and len(tail) >= 2:
                break
            tail.insert(0, m)
            budget -= len(m["content"])
        while tail and tail[0]["role"] != "assistant":   # keep user/assistant alternation
            tail.pop(0)
        return head + tail

    def _call(self, b: Backend, small: bool = False):
        """small=True: a reduced request for models whose free tier rejects big ones ("request too large")."""
        client = self._client(b)
        max_tokens = 2500 if small else (8192 if "gpt-oss" in b.model else 4096)
        messages = self._payload(9000 if small else None)
        kwargs = {"max_tokens": max_tokens}
        if b.provider == "groq":
            if "gpt-oss" in b.model:
                kwargs["reasoning_effort"] = "low" if small else os.environ.get("LLM_REASONING", "medium")
            request = lambda: client.chat.completions.create(  # noqa: E731
                model=b.model, messages=messages, temperature=0.2, **kwargs)
        else:
            request = lambda: client.chat.complete(model=b.model, messages=messages, temperature=0.2, **kwargs)  # noqa: E731
        tick = getattr(self, "tick", None)
        if tick is None:
            return request()
        return _run_interruptibly(request, tick)

    def _chat_with_failover(self, short_retries: int = 3):
        """Try each model in the chain; short (per-minute) rate limits are retried with backoff,
        daily quotas / unavailable models are skipped and remembered."""
        cooldowns = _load_cooldowns()
        reasons: list[str] = []
        for b in self.chain:
            if b.key in cooldowns:
                reasons.append(f"{b.label}: cooling down")
                continue
            small = False
            for attempt in range(short_retries + 1):
                try:
                    resp = self._call(b, small=small)
                    if b != self.current:
                        self.events.append(f"Switched to {b.label}")
                    self.current = b
                    if b.label not in self.used:
                        self.used.append(b.label)
                    return resp
                except Exception as e:  # noqa: BLE001
                    action, cool = classify(e)
                    last = f"{type(e).__name__}: {str(e)[:160]}"
                    if action == "retry" and attempt < short_retries:
                        # wait exactly as long as the provider asks ("try again in 1.8s"), not a blind backoff
                        hinted = _short_wait_hint(str(e))
                        time.sleep(min(hinted + 0.3, 20) if hinted is not None else min(2 ** (attempt + 1), 20))
                        continue
                    if action == "next" and not small:
                        small = True          # same model, smaller request (shorter history, fewer output tokens)
                        continue
                    if action == "skip":
                        _save_cooldown(b.key, cool)
                    elif action == "next":
                        pass
                    else:
                        _save_cooldown(b.key, 60)   # keeps failing: rest it for a minute
                    reasons.append(f"{b.label}: {last}")
                    self.events.append(f"{b.label} unavailable, trying the next model")
                    break
        raise RuntimeError("All configured models failed:\n- " + "\n- ".join(reasons))

    def _complete_text(self) -> str:
        resp = self._chat_with_failover()
        text = resp.choices[0].message.content
        if isinstance(text, list):  # content chunks
            text = "".join(getattr(c, "text", "") for c in text)
        text = _THINK.sub("", text or "").strip()
        self.messages.append({"role": "assistant", "content": text})
        return text

    def _complete(self) -> str:
        return extract_code(self._complete_text())

    # A short design brief before any code makes vague requests ("a toothbrush") come out realistic:
    # the model first decides real-world dimensions, every feature and the construction method.
    BRIEF = (
        "Before writing any code, write a short DESIGN BRIEF as a mechanical/product designer (plain text, "
        "max 170 words, no code):\n"
        "1. What the real object looks like and its realistic overall size in mm (use typical real-world values "
        "for anything not specified, and keep every dimension the user gave).\n"
        "2. Every feature that makes it recognisable, with dimensions and position (e.g. for a toothbrush: tapered "
        "handle, thinner neck, head, a grid of bristle tufts).\n"
        "3. The CadQuery construction plan, step by step (sketches, extrude/loft/sweep/revolve, arrays, booleans, "
        "fillets), keeping it one solid."
    )
    REVISE_BRIEF = (
        "Before writing code, write a short CHANGE BRIEF (plain text, max 120 words, no code): what is wrong or "
        "missing compared with the request (and with the real object, if it is an everyday object), the exact "
        "changes with dimensions, and how to build them in CadQuery."
    )

    def _brief_then_code(self, request: str, brief_prompt: str, code_prompt: str) -> str:
        """Brief and code in ONE reply (one round trip instead of two): the brief as plain text, then the full
        script in a ```python block. Falls back to a second request if the reply has no usable code."""
        self.messages.append({"role": "user", "content": (
            f"{request}\n\n{brief_prompt}\n\nThen, directly below the brief, {code_prompt[0].lower()}{code_prompt[1:]} "
            "Put the script in a single ```python code block.")})
        reply = self._complete_text()
        fence = reply.find("```")
        self.last_brief = (reply[:fence] if fence >= 0 else "").strip()
        code = extract_code(reply) if fence >= 0 else ""
        if "result" in code and "\n" in code.strip():
            return code
        if not self.last_brief:
            self.last_brief = reply.strip()
        self.messages.append({"role": "user", "content": code_prompt})   # fallback: ask for the code alone
        return self._complete()

    def generate(self, user_prompt: str) -> str:
        self.requests.append(user_prompt)
        return self._brief_then_code(
            user_prompt, self.BRIEF,
            "Now write the complete CadQuery script that implements this brief faithfully. "
            "Code only, assign the final solid to `result`.",
        )

    def revise(self, request: str, current_code: str, marks: str = "") -> str:
        """Chat follow-up: modify the current model."""
        self.requests.append(request)
        content = (
            "Modify the current model according to this request:\n"
            f"{request}\n\n"
            + (f"The user marked these spots on the 3D preview (coordinates are in the same mm frame as "
               f"the script):\n{marks}\n\n" if marks else "")
            + "Current script:\n```python\n" + current_code.strip() + "\n```"
        )
        return self._brief_then_code(
            content, self.REVISE_BRIEF,
            "Now return the complete updated CadQuery script implementing the change brief. Keep everything that "
            "was not asked to change. Code only, assign the final solid to `result`.",
        )

    def repair(self, error: str, attempt: int = 1) -> str:
        hints = fix_hints(error)
        if attempt >= 2:
            hints.append(
                "This has failed more than once: rebuild it with the robust helper toolkit (`import t2c as h`): "
                "h.box / h.cylinder / h.loft_x / h.loft_z / h.revolve_z / h.pin_grid for each feature, then "
                "result = h.union(...), and only h.fillet (never raw .fillet). A correct, slightly simpler part is "
                "better than an error.")
        self.messages.append({
            "role": "user",
            "content": (
                "The code above failed with this error:\n\n"
                f"{error}\n\n"
                + ("How to fix this kind of error:\n- " + "\n- ".join(hints) + "\n\n" if hints else "")
                + "Fix it. Return the complete corrected CadQuery script only, assigning the final solid to `result`."
            ),
        })
        return self._complete()

    def check(self, metrics: dict) -> str | None:
        """Self-check: show the model the measured geometry. Returns None if it
        says the part matches the request, otherwise the revised code."""
        x, y, z = metrics["bbox_mm"]
        self.messages.append({
            "role": "user",
            "content": (
                "The code ran. Measured result: bounding box "
                f"X={x} mm, Y={y} mm, Z={z} mm; volume={metrics['volume_mm3']} mm^3; "
                f"solids={metrics['num_solids']}; "
                f"round holes found: {_features(metrics.get('holes'))}; "
                f"outer cylinders: {_features(metrics.get('rounds'))}.\n"
                "Check it rigorously, one item at a time: (1) the overall extents: 'height', 'tall' or 'vertical' "
                "means the Z size, 'length' means X, 'width' means Y; a part described as having a vertical "
                "leg/wall must extend that far in Z, not lie flat; (2) hole counts and diameters; "
                "(3) wall thicknesses and other features. Compare against EVERY dimension and feature in my original description "
                "and in any later change requests (overall size, hole counts/diameters, wall thicknesses, orientation). "
                "If everything is consistent, reply with exactly the single word OK. "
                "Otherwise reply with the complete corrected CadQuery script only."
            ),
        })
        resp = self._chat_with_failover()
        text = resp.choices[0].message.content
        if isinstance(text, list):
            text = "".join(getattr(c, "text", "") for c in text)
        text = _THINK.sub("", text or "")
        self.messages.append({"role": "assistant", "content": text})
        if text.strip().strip(".!`").upper() == "OK" or (
                len(text.strip()) < 40 and "result" not in text):
            return None
        code = extract_code(text)
        return code if "result" in code else None

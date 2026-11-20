"""Run a chat model over the benchmark and write predictions JSONL.

Uses only the Python standard library. Two backends are supported:

- ``ollama``: a local Ollama server (the setup used in the paper);
- ``openai``: any OpenAI-compatible ``/v1/chat/completions`` endpoint, such as
  vLLM, LM Studio, llama.cpp server, or a hosted API. The key is read from an
  environment variable and is never written to disk.

Only the episode transcript is sent to the model. Reference labels never leave
the scorer. Runs are resumable: episodes already answered in the output file
are skipped.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from .episodes import ACTIONS, model_inputs, user_message
from .prompts import ACTION_SCHEMA, CONDITIONS

PAPER_OPTIONS = {"temperature": 0.0, "num_ctx": 4096, "num_predict": 350, "seed": 17}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _post(url, body, headers=None, timeout=600):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def call_ollama(model, system, user, base_url="http://localhost:11434"):
    body = {"model": model, "stream": False, "format": ACTION_SCHEMA,
            "options": PAPER_OPTIONS,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    if model.startswith("qwen3"):
        body["think"] = False
    data = _post(f"{base_url.rstrip('/')}/api/chat", body)
    return data["message"]["content"]


def call_openai(model, system, user, base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY", temperature=0.0, max_tokens=350):
    headers = {}
    key = os.environ.get(api_key_env)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    data = _post(f"{base_url.rstrip('/')}/chat/completions", body, headers)
    return data["choices"][0]["message"]["content"]


def parse_output(raw):
    """Return (parsed, error). Mirrors the paper's parser."""
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        obj = json.loads(text[: text.rfind("}") + 1] if "}" in text else text)
        action = str(obj.get("action", "")).strip().upper()
        conf = float(obj.get("confidence", float("nan")))
        reason = str(obj.get("reason", ""))
        if action not in ACTIONS:
            return None, "invalid_action"
        conf = min(max(conf, 0.0), 1.0)
        return {"action": action, "confidence": conf, "reason": reason}, None
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as e:
        return None, f"parse_error: {e}"


def run(model, out_path, backend="ollama", condition="uncertainty", split="test",
        base_url=None, api_key_env="OPENAI_API_KEY", workers=4, limit=0, log=print):
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {sorted(CONDITIONS)}")
    system = CONDITIONS[condition]
    if backend == "ollama":
        call = lambda u: call_ollama(model, system, u, base_url or "http://localhost:11434")
    elif backend == "openai":
        call = lambda u: call_openai(model, system, u,
                                     base_url or "https://api.openai.com/v1", api_key_env)
    else:
        raise ValueError("backend must be 'ollama' or 'openai'")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("action") in ACTIONS:
                done.add(rec["episode_id"])
    todo = [e for e in model_inputs(split) if e["episode_id"] not in done]
    if limit:
        todo = todo[:limit]
    lock, counter = Lock(), {"n": 0}
    log(f"{model} / {condition} / {split}: {len(todo)} to run, {len(done)} already done")

    def one(ep):
        user = user_message(ep["transcript"])
        rec = {"episode_id": ep["episode_id"], "model": model, "condition": condition,
               "prompt_sha256": hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16],
               "started_at": _now()}
        parsed, err, raw = None, None, None
        for attempt in range(3):
            try:
                raw = call(user)
                parsed, err = parse_output(raw)
                if parsed:
                    break
            except (urllib.error.URLError, TimeoutError, KeyError, OSError) as e:
                err = f"request_error: {e}"
                time.sleep(2 * (attempt + 1))
        rec.update({"finished_at": _now(), "raw_output": raw, "error": err,
                    **(parsed or {"action": None, "confidence": None, "reason": None})})
        with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            counter["n"] += 1
            if counter["n"] % 25 == 0 or counter["n"] == len(todo):
                log(f"  {counter['n']}/{len(todo)}")
        return rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    return out_path

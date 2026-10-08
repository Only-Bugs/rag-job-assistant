"""
Prompt eval harness — run every generation task over fixture JDs x profiles,
save outputs + rendered prompts + checks, and diff two runs side by side.

Usage (from project root, Ollama running):
    sandbox/bin/python scripts/eval_prompts.py                     # full matrix
    sandbox/bin/python scripts/eval_prompts.py --profiles data_dev --jds fullstack_atlassian
    sandbox/bin/python scripts/eval_prompts.py --compare eval_runs/A eval_runs/B

Profiles are copied into a temp user dir per run, so the real Chroma store and
profile_docs are never written to. Output goes to eval_runs/<timestamp>/ (git-ignored).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

FIXTURES = ROOT / "tests" / "fixtures" / "eval"
RUNS_DIR = ROOT / "eval_runs"
DOC_SUFFIXES = {".pdf", ".txt", ".md"}

from resumate.evaluation.checks import TASKS, BLOCKED_MARKER, run_checks  # noqa: E402


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------
def _profile_text(profile_dir: Path) -> str:
    """Everything the candidate has claimed: settings JSON + resume doc text."""
    parts = []
    settings = profile_dir / "profile_settings.json"
    if settings.exists():
        parts.append(settings.read_text(encoding="utf-8"))
    for f in sorted((profile_dir / "profile_docs").glob("*")):
        if f.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            parts.append("\n".join(p.extract_text() or "" for p in PdfReader(str(f)).pages))
        elif f.suffix.lower() in {".txt", ".md"}:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _stage_profile(src: Path) -> Path:
    """Copy a profile (settings + docs) into a fresh temp user dir. Read-only on src."""
    tmp = Path(tempfile.mkdtemp(prefix="rm_eval_"))
    (tmp / "profile_docs").mkdir()
    (tmp / "chroma_db").mkdir()
    shutil.copy2(src / "profile_settings.json", tmp / "profile_settings.json")
    for f in (src / "profile_docs").glob("*"):
        if f.is_file() and f.suffix.lower() in DOC_SUFFIXES:
            shutil.copy2(f, tmp / "profile_docs" / f.name)
    return tmp


# ---------------------------------------------------------------------------
# Prompt recorder — wraps whichever LLM entry point generation.py uses.
# ---------------------------------------------------------------------------
class PromptRecorder:
    # (module, attribute) pairs that may hold the LLM entry point, old and new pipelines.
    ENTRY_POINTS = (
        ("resumate.services.generation", "stream_prompt"),
        ("resumate.services.generation", "chat_stream"),
        ("resumate.services.tasks", "chat_stream"),
    )

    def __init__(self):
        self.calls: list[dict] = []
        self._orig: list[tuple[object, str, object]] = []

    def install(self):
        import importlib
        for mod_name, attr in self.ENTRY_POINTS:
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            fn = getattr(mod, attr, None)
            if fn is None:
                continue
            self._orig.append((mod, attr, fn))
            setattr(mod, attr, self._wrap(fn))

    def uninstall(self):
        for mod, attr, fn in self._orig:
            setattr(mod, attr, fn)
        self._orig.clear()

    def _wrap(self, fn):
        recorder = self

        def wrapped(*args, **kwargs):
            text_parts = [a for a in args if isinstance(a, str)]
            for a in args:
                if isinstance(a, list):  # chat messages
                    text_parts += [m.get("content", "") for m in a if isinstance(m, dict)]
            prompt = "\n\n----- next part -----\n\n".join(text_parts)
            call = {"task": kwargs.get("task_name", "?"), "prompt": prompt,
                    "prompt_chars": len(prompt), "prompt_tokens_est": len(prompt) // 4, "ttft_s": None}
            recorder.calls.append(call)
            t0 = time.perf_counter()
            for piece in fn(*args, **kwargs):
                if call["ttft_s"] is None:
                    call["ttft_s"] = round(time.perf_counter() - t0, 2)
                yield piece

        return wrapped


# ---------------------------------------------------------------------------
# One generation run
# ---------------------------------------------------------------------------
def run_one(jd_text: str, user_dir: Path) -> dict:
    from resumate.services.generation import generate_application_package

    t0 = time.perf_counter()
    outputs: dict[str, str] = {}
    first_token: dict[str, float] = {}
    done_at: dict[str, float] = {}
    meta: dict = {}
    for name, val in generate_application_package(jd_text, user_data_dir=user_dir):
        t = time.perf_counter() - t0
        if name == "token":
            first_token.setdefault(val["task"], t)
        elif name in TASKS:
            outputs[name] = val
            done_at[name] = t
        elif name == "blocked":
            meta["blocked"] = val
        elif name == "_meta":
            meta.update({k: v for k, v in val.items() if k != "context"})
    total = time.perf_counter() - t0
    # TTFT per task = first token minus the end of the previous task (or pipeline start).
    ttft, prev = {}, 0.0
    for task in sorted(first_token, key=first_token.get):
        ttft[task] = round(first_token[task] - prev, 2)
        prev = done_at.get(task, prev)
    return {"outputs": outputs, "ttft_s": ttft, "done_s": {k: round(v, 1) for k, v in done_at.items()},
            "total_s": round(total, 1), "meta": meta}


def _guard_blocked(result: dict) -> bool:
    meta = result.get("meta", {})
    if "domain_ok" in meta:
        return not meta["domain_ok"]
    return BLOCKED_MARKER in result["outputs"].get("skills", "")


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------
def run_matrix(profiles: list[str], jds: list[str], label: str) -> Path:
    from resumate.models.llm import LLM_NUM_CTX, get_current_model

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    run_dir = RUNS_DIR / (datetime.now().strftime("%Y%m%d_%H%M%S") + (f"_{label}" if label else ""))
    run_dir.mkdir(parents=True)
    summary = {"model": get_current_model(), "num_ctx": LLM_NUM_CTX, "label": label, "rows": []}

    for prof in profiles:
        src = ROOT / manifest["profiles"][prof]["path"]
        if not (src / "profile_settings.json").exists():
            print(f"!! skipping profile {prof}: {src} not found")
            continue
        evidence = _profile_text(src)
        for jd in jds:
            jd_text = (FIXTURES / "jds" / f"{jd}.txt").read_text(encoding="utf-8")
            out_dir = run_dir / prof / jd
            (out_dir / "prompts").mkdir(parents=True)
            user_dir = _stage_profile(src)
            rec = PromptRecorder()
            rec.install()
            print(f"== {prof} / {jd}", flush=True)
            try:
                result = run_one(jd_text, user_dir)
            except Exception as exc:  # keep going; record the failure
                result = {"outputs": {}, "ttft_s": {}, "done_s": {}, "total_s": None,
                          "meta": {}, "error": f"{type(exc).__name__}: {exc}"}
                print(f"   ERROR {result['error']}", flush=True)
            finally:
                rec.uninstall()
                shutil.rmtree(user_dir, ignore_errors=True)

            for i, call in enumerate(rec.calls):
                (out_dir / "prompts" / f"{i:02d}_{call['task']}.txt").write_text(call["prompt"], encoding="utf-8")
            prompt_est, model_ttft = {}, {}
            for call in rec.calls:
                task = call["task"].removeprefix("gen_").split(":")[0]
                prompt_est[task] = max(prompt_est.get(task, 0), call["prompt_tokens_est"])
                if call["ttft_s"] is not None:
                    model_ttft.setdefault(task, []).append(call["ttft_s"])

            expected_ok = manifest["jds"][jd]["expect_domain_ok"].get(prof)
            blocked = _guard_blocked(result)
            checks = {}
            for task in TASKS:
                text = result["outputs"].get(task, "")
                (out_dir / f"{task}.txt").write_text(text, encoding="utf-8")
                if blocked and not text:
                    # Correctly skipped by the guard: nothing to check.
                    checks[task] = {"skipped": "blocked by domain guard", "failures": 0}
                    continue
                checks[task] = run_checks(task, text, profile_evidence=evidence, jd_text=jd_text,
                                          prompt_tokens_est=prompt_est.get(task), num_ctx=LLM_NUM_CTX)
            row = {
                "profile": prof, "jd": jd,
                "guard_expected_ok": expected_ok, "guard_blocked": blocked,
                "guard_correct": (expected_ok is None) or (expected_ok != blocked),
                "total_s": result["total_s"], "ttft_s": result["ttft_s"], "done_s": result["done_s"],
                # Model TTFT of each task's first call, and the mean over all its calls.
                "model_ttft_first_s": {t: v[0] for t, v in model_ttft.items()},
                "model_ttft_mean_s": {t: round(sum(v) / len(v), 2) for t, v in model_ttft.items()},
                "llm_calls": len(rec.calls),
                "failures": {t: checks[t]["failures"] for t in TASKS},
                "error": result.get("error"),
            }
            (out_dir / "checks.json").write_text(json.dumps({"row": row, "checks": checks, "meta": result["meta"]}, indent=2))
            summary["rows"].append(row)
            print(f"   total={row['total_s']}s ttft={row['ttft_s']} guard_ok={row['guard_correct']} "
                  f"failures={row['failures']}", flush=True)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (run_dir / "summary.md").write_text(_summary_md(summary, run_dir))
    print(f"\nWrote {run_dir}")
    return run_dir


def _summary_md(summary: dict, run_dir: Path) -> str:
    lines = [f"# Eval run `{run_dir.name}`", "",
             f"Model `{summary['model']}`, num_ctx {summary['num_ctx']}", "",
             "| Profile | JD | Guard | Total s | Visible TTFT c/e/s/a | Model TTFT first (mean) c/e/s/a | Calls | Failures c/e/s/a |",
             "|---|---|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        guard = ("✓" if r["guard_correct"] else "✗") + (" blocked" if r["guard_blocked"] else " ok")
        tt = " / ".join(str(r["ttft_s"].get(t, "–")) for t in TASKS)
        mf, mm = r.get("model_ttft_first_s", {}), r.get("model_ttft_mean_s", {})
        mt = " / ".join(f"{mf[t]} ({mm[t]})" if t in mf else "–" for t in TASKS)
        fl = " / ".join(str(r["failures"].get(t, "–")) for t in TASKS)
        lines.append(f"| {r['profile']} | {r['jd']} | {guard} | {r['total_s']} | {tt} | {mt} | {r['llm_calls']} | {fl} |")
    rows = summary["rows"]
    if rows:
        lines += ["", f"**Guard correct:** {sum(r['guard_correct'] for r in rows)}/{len(rows)}  ",
                  f"**Total check failures:** {sum(sum(r['failures'].values()) for r in rows)}"]
    lines += ["", "Per-task details: `<profile>/<jd>/checks.json`; rendered prompts in `prompts/`."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Compare two runs
# ---------------------------------------------------------------------------
def compare(a: Path, b: Path) -> Path:
    sa = json.loads((a / "summary.json").read_text())
    sb = json.loads((b / "summary.json").read_text())
    rows_b = {(r["profile"], r["jd"]): r for r in sb["rows"]}
    out = b / f"compare_vs_{a.name}.html"
    esc = html.escape
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Eval compare</title>",
        "<style>body{font:14px/1.5 system-ui,sans-serif;margin:24px;max-width:1500px}"
        "table{border-collapse:collapse;width:100%;margin:8px 0 24px}td,th{border:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}"
        "pre{white-space:pre-wrap;margin:0;font:13px/1.5 ui-monospace,monospace}.bad{color:#b42318}.good{color:#067647}"
        "h2{margin-top:36px;border-top:2px solid #ccc;padding-top:12px}</style>",
        f"<h1>{esc(a.name)} &rarr; {esc(b.name)}</h1>",
        f"<p>Before: <code>{esc(sa['model'])}</code> &middot; After: <code>{esc(sb['model'])}</code></p>",
        "<table><tr><th>Profile / JD</th><th>Guard before &rarr; after</th><th>Total s</th><th>Failures (cover/emails/skills/ats)</th></tr>",
    ]
    for ra in sa["rows"]:
        key = (ra["profile"], ra["jd"])
        rb = rows_b.get(key)
        if not rb:
            continue
        fa = sum(ra["failures"].values()); fb = sum(rb["failures"].values())
        cls = "good" if fb < fa else "bad" if fb > fa else ""
        parts.append(
            f"<tr><td>{esc(key[0])} / {esc(key[1])}</td>"
            f"<td>{'✓' if ra['guard_correct'] else '✗'} &rarr; {'✓' if rb['guard_correct'] else '✗'}</td>"
            f"<td>{ra['total_s']} &rarr; {rb['total_s']}</td>"
            f"<td class='{cls}'>{'/'.join(str(ra['failures'][t]) for t in TASKS)} &rarr; "
            f"{'/'.join(str(rb['failures'][t]) for t in TASKS)}</td></tr>")
    parts.append("</table>")
    for ra in sa["rows"]:
        key = (ra["profile"], ra["jd"])
        if key not in rows_b:
            continue
        parts.append(f"<h2>{esc(key[0])} / {esc(key[1])}</h2>")
        ca = json.loads((a / key[0] / key[1] / "checks.json").read_text())["checks"]
        cb = json.loads((b / key[0] / key[1] / "checks.json").read_text())["checks"]
        for task in TASKS:
            ta = (a / key[0] / key[1] / f"{task}.txt").read_text(encoding="utf-8")
            tb = (b / key[0] / key[1] / f"{task}.txt").read_text(encoding="utf-8")
            def _issues(c):
                return "; ".join(f"{k}: {v}" for k, v in c.items() if isinstance(v, list) and v) or "none"
            parts.append(f"<h3>{task}</h3><table><tr><th>Before</th><th>After</th></tr>"
                         f"<tr><td class='bad'>{esc(_issues(ca[task]))}</td><td class='bad'>{esc(_issues(cb[task]))}</td></tr>"
                         f"<tr><td><pre>{esc(ta)}</pre></td><td><pre>{esc(tb)}</pre></td></tr></table>")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {out}")
    return out


def main():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", default=",".join(manifest["profiles"]))
    ap.add_argument("--jds", default=",".join(manifest["jds"]))
    ap.add_argument("--label", default="", help="suffix for the run folder, e.g. 'baseline'")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.compare:
        compare(Path(args.compare[0]), Path(args.compare[1]))
        return
    from resumate.models.embeddings import get_embeddings
    get_embeddings()  # load once up front so the first row's timing is fair
    run_matrix(args.profiles.split(","), args.jds.split(","), args.label)


if __name__ == "__main__":
    main()

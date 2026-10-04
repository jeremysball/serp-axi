"""Spike (throwaway): Q5, reCAPTCHA v2 audio route with local Whisper, on Google's own demo page.

Usage: .venv/bin/python q5_audio.py <out.jsonl> <tries>     (one subprocess per try, SIGKILL at 120s)
Child: q5_audio.py --one
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

DEMO = "https://www.google.com/recaptcha/api2/demo"
HARD_KILL_S = 120
GAP_S = 30


def checked(anchor):
    return anchor.locator("#recaptcha-anchor").get_attribute("aria-checked") == "true"


def one():
    from camoufox.sync_api import Camoufox
    from faster_whisper import WhisperModel

    rec = {"steps": []}
    t0 = time.monotonic()
    with Camoufox(headless=True, humanize=True) as browser:
        page = browser.new_page()
        page.goto(DEMO, wait_until="load", timeout=30000)
        anchor = page.frame_locator("iframe[title='reCAPTCHA']")
        anchor.locator("#recaptcha-anchor").click(timeout=15000)
        page.wait_for_timeout(3000)
        if checked(anchor):
            rec.update(outcome="passed_no_challenge")
            return finish(rec, t0)
        bframe = page.frame_locator("iframe[title*='challenge']")
        bframe.locator("#recaptcha-audio-button").click(timeout=15000)
        page.wait_for_timeout(3000)
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        for round_ in range(3):  # reCAPTCHA sometimes asks for more than one clip
            if bframe.locator(".rc-doscaptcha-header").count():
                rec.update(outcome="refused", why=bframe.locator(".rc-doscaptcha-body").inner_text()[:160])
                return finish(rec, t0)
            src = bframe.locator("#audio-source").get_attribute("src", timeout=15000)
            with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
                f.write(urllib.request.urlopen(src, timeout=30).read())
                f.flush()
                segs, _ = model.transcribe(f.name, language="en", beam_size=5)
                text = " ".join(s.text for s in segs)
            answer = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
            rec["steps"].append({"round": round_, "transcript": text.strip(), "answer": answer})
            bframe.locator("#audio-response").fill(answer)
            bframe.locator("#recaptcha-verify-button").click()
            page.wait_for_timeout(4000)
            if checked(anchor):
                rec.update(outcome="solved")
                return finish(rec, t0)
            err = bframe.locator(".rc-audiochallenge-error-message")
            rec["steps"][-1]["error"] = err.inner_text()[:120] if err.count() else ""
        rec.update(outcome="failed")
    return finish(rec, t0)


def finish(rec, t0):
    rec["ms"] = int((time.monotonic() - t0) * 1000)
    print(json.dumps(rec))


def drive(out_path, tries):
    with open(out_path, "a") as out:
        for i in range(int(tries)):
            if i:
                time.sleep(GAP_S)
            p = subprocess.Popen([sys.executable, __file__, "--one"], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=HARD_KILL_S)
                lines = [l for l in stdout.splitlines() if l.startswith("{")]
                rec = json.loads(lines[-1]) if p.returncode == 0 and lines else {
                    "outcome": "error", "why": (stderr.strip().splitlines() or ["no stderr"])[-1][:200]}
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
                rec = {"outcome": "hang", "why": f">{HARD_KILL_S}s"}
            rec.update(try_=i, ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(i, rec["outcome"], rec.get("why", ""), [s.get("answer") for s in rec.get("steps", [])], flush=True)


if __name__ == "__main__":
    one() if sys.argv[1] == "--one" else drive(sys.argv[1], sys.argv[2])

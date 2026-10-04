import json, sys
from camoufox.sync_api import Camoufox
url = sys.argv[1]
with Camoufox(headless=True, humanize=True) as b:
    p = b.new_page(); p.goto(url, wait_until="domcontentloaded", timeout=30000); p.wait_for_timeout(12000)
    t = p.evaluate("() => { document.querySelectorAll('script,style,noscript').forEach(e => e.remove()); return document.body.innerText }")
    print(json.dumps({"url": url, "title": p.title(), "chars": len(t), "text": " ".join(t.split())[:400]}))

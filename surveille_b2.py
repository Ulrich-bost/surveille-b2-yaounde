
import json
import os
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://kbw-personal-services.butlerapp2.de/demo#/courses?fcourses=yaounde_deutsch_b2"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
BASELINE = Path("baseline.json")
DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")

JS_STATE = """
el => {
  const out = [];
  let n = el;
  for (let i = 0; i < 3 && n; i++, n = n.parentElement) {
    const s = getComputedStyle(n);
    out.push([n.className, n.getAttribute('aria-disabled'),
              n.hasAttribute('disabled'), s.color, s.opacity,
              s.pointerEvents].join('|'));
  }
  return out.join(' > ');
}
"""


def notify(msg):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC manquant")
        return
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Examen B2 Yaounde", "Priority": "high"},
                  timeout=15)


def snapshot(page):
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.get_by_text("Sélectionnez un événement").first.click()
    page.wait_for_timeout(1000)
    items = page.get_by_text(DATE_RE)
    result = {}
    for i in range(items.count()):
        el = items.nth(i)
        text = " ".join(el.inner_text().split())
        result[text] = el.evaluate(JS_STATE)
    return result


def main():
    debug = len(sys.argv) > 1 and sys.argv[1] == "debug"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        state = snapshot(page)
        browser.close()

    print(f"{len(state)} dates trouvées")
    if debug:
        for k, v in state.items():
            print(k, "\n   ", v)
        notify(f"Test OK : {len(state)} dates vues sur la page.")
        return

    if not BASELINE.exists():
        BASELINE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        notify(f"Surveillance démarrée ({len(state)} dates vues).")
        return

    old = json.loads(BASELINE.read_text())
    if state != old:
        notify("Les réservations B2 Yaoundé semblent ouvertes ! Va vite sur le site.")
        BASELINE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        print("CHANGEMENT DÉTECTÉ")
    else:
        print("Rien de nouveau")


if __name__ == "__main__":
    main()
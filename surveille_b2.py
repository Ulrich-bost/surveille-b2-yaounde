import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "https://kbw-personal-services.butlerapp2.de/demo"
URL_LISTE = BASE + "#/bookcart"
URL_COURS = BASE + "#/courses?fcourses=yaounde_deutsch_b2&wsc_1months=2026_12"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
BASELINE = Path("baseline.json")
DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
TEXTES = [
    re.compile(r"Veranstaltung.{0,20}(auswählen|wählen)", re.I),
    re.compile(r"(auswählen|wählen)", re.I),
    re.compile(r"Sélectionnez un événement", re.I),
    re.compile(r"Select an event", re.I),
]
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


def safe(f, *args):
    try:
        return f(*args)
    except Exception as e:
        print("Erreur :", e)
        return None


def dates_visibles(page):
    return page.get_by_text(DATE_RE).count()


def ouvrir_liste(page):
    for motif in TEXTES:
        try:
            page.get_by_text(motif).last.click(timeout=4000)
            page.wait_for_timeout(1000)
            if dates_visibles(page):
                return True
        except Exception:
            pass
    menus = page.locator("select, [role=combobox], [class*=select]")
    for i in range(menus.count()):
        try:
            menus.nth(i).click(timeout=3000)
            page.wait_for_timeout(1000)
            if dates_visibles(page):
                return True
        except Exception:
            pass
    return False


def etat_liste(page):
    page.goto(URL_LISTE, wait_until="networkidle")
    page.wait_for_timeout(3000)
    if not dates_visibles(page) and not ouvrir_liste(page):
        Path("page.txt").write_text(page.inner_text("body"))
        page.screenshot(path="page.png", full_page=True)
        raise RuntimeError("Liste des dates introuvable")
    items = page.get_by_text(DATE_RE)
    result = {}
    for i in range(items.count()):
        el = items.nth(i)
        text = " ".join(el.inner_text().split())
        result[text] = el.evaluate(JS_STATE)
    return result


def elements_cours(page):
    els = page.locator("a, button, [role=button], input[type=button], input[type=submit]")
    res = []
    for i in range(els.count()):
        el = els.nth(i)
        try:
            if not el.is_visible():
                continue
            t = " ".join(el.inner_text().split())
            if not t:
                t = (el.get_attribute("value") or el.get_attribute("aria-label")
                     or el.get_attribute("title") or "")
            href = el.get_attribute("href") or ""
            off = "" if el.is_enabled() else "|inactif"
            res.append(f"{t[:80]}|{href[:120]}{off}")
        except Exception:
            pass
    return sorted(res)


def etat_cours(page, debug, minimum):
    page.goto(URL_COURS, wait_until="networkidle")
    page.wait_for_timeout(4000)
    res = elements_cours(page)
    if len(res) < minimum:
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(5000)
        res = elements_cours(page)
    if debug:
        print("=== TEXTE DE LA PAGE DES COURS")
        print(page.inner_text("body")[:1500])
    return res


def main():
    debug = len(sys.argv) > 1 and sys.argv[1] == "debug"
    old = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    if old is not None and (not isinstance(old.get("cours"), list) or "liste" not in old):
        old = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="de-DE")
        liste = safe(etat_liste, page)
        page.close()
        page = browser.new_page(locale="de-DE")
        cours = safe(etat_cours, page, debug, len(old["cours"]) if old else 0)
        browser.close()

    if old:
        if liste is None:
            liste = old["liste"]
        if cours is None:
            cours = old["cours"]
    new = {"liste": liste or {}, "cours": cours or []}

    print(f"{len(new['liste'])} dates dans la liste, "
          f"{len(new['cours'])} éléments cliquables sur la page des cours")
    for e in new["cours"]:
        print("  -", e)

    if debug:
        notify(f"Test OK : {len(new['liste'])} dates dans la liste, "
               f"{len(new['cours'])} éléments cliquables sur la page des cours.")
        return

    if old is None:
        BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=1))
        notify(f"Surveillance mise à jour ({len(new['liste'])} dates, "
               f"{len(new['cours'])} éléments).")
        return

    ajoutes = list((Counter(new["cours"]) - Counter(old["cours"])).elements())
    msgs = []
    if ajoutes:
        noms = "; ".join((a.split("|")[0] or a)[:40] for a in ajoutes[:3])
        msgs.append(f"Nouveau sur la page des cours : {noms}.")
    if new["liste"] != old["liste"]:
        msgs.append("La liste des dates a changé.")

    if msgs:
        notify(" ".join(msgs) + " Va vite sur le site !")
        print("CHANGEMENT DÉTECTÉ")
    if new != old:
        BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=1))
    elif not msgs:
        print("Rien de nouveau")


if __name__ == "__main__":
    main()

"""Met a jour le numero de version de l'appli (index.html, service worker) d'apres le contenu des fichiers.

Le numero change des qu'un fichier de l'appli change : plus de telephone qui garde un ancien fichier.
Usage : python tools/bump_version.py   (sans effet si rien n'a change)
"""
import hashlib
import pathlib
import re

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
FILES = ["app.js", "live.js", "compose.js", "style.css", "sw.js", "manifest.webmanifest"]


def main():
    h = hashlib.sha256()
    for f in FILES:
        txt = (DOCS / f).read_text(encoding="utf-8")
        if f == "sw.js":  # le numero lui-meme ne compte pas
            txt = re.sub(r'const V = "pf-[^"]+";', "", txt)
        h.update(txt.encode("utf-8"))
    v = h.hexdigest()[:8]
    index = DOCS / "index.html"
    html = index.read_text(encoding="utf-8")
    new_html = re.sub(r"\?v=[0-9a-z]+", f"?v={v}", html)
    sw = DOCS / "sw.js"
    swt = sw.read_text(encoding="utf-8")
    new_sw = re.sub(r'const V = "pf-[^"]+";', f'const V = "pf-{v}";', swt)
    changed = new_html != html or new_sw != swt
    index.write_text(new_html, encoding="utf-8")
    sw.write_text(new_sw, encoding="utf-8")
    print(f"version {v}" + (" (mise a jour)" if changed else " (inchangee)"))


if __name__ == "__main__":
    main()

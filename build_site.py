"""
Genera un sitio estático de agregación de noticias a partir de feeds RSS.
Muestra SOLO título + copete corto + link a la fuente original.
Nunca copia el artículo completo (evita problemas de derechos de autor
y cumple las políticas de las redes publicitarias).

No requiere paquetes externos: usa solo la librería estándar de Python.
"""
import json
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.json"
OUT_DIR = ROOT / "site"
MAX_ITEMS_PER_FEED = 8
SUMMARY_MAX_CHARS = 180
REQUEST_TIMEOUT = 15

# ---- Configuración editable ----
SITE_NAME = "Portal Todo Noticias"
GA_MEASUREMENT_ID = "G-XXXXXXXXXX"      # reemplazar por tu ID de Google Analytics 4
ADSENSE_CLIENT_ID = "ca-pub-XXXXXXXXXXXXXXXX"  # reemplazar por tu ID de AdSense
# ---------------------------------


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def truncate(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def fetch_feed_items(feed_url: str):
    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (NewsAggregatorBot/1.0)"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = resp.read()
    root = ET.fromstring(data)

    items = []
    # RSS 2.0
    for item in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
        title = strip_tags(item.findtext("title", default=""))
        link = (item.findtext("link", default="") or "").strip()
        desc = strip_tags(item.findtext("description", default=""))
        pub = item.findtext("pubDate", default="")
        if title and link:
            items.append({"title": title, "link": link, "summary": truncate(desc, SUMMARY_MAX_CHARS), "pub": pub})

    # Atom fallback
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:MAX_ITEMS_PER_FEED]:
            title = strip_tags(entry.findtext("a:title", default="", namespaces=ns))
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            summary = strip_tags(entry.findtext("a:summary", default="", namespaces=ns))
            pub = entry.findtext("a:updated", default="", namespaces=ns)
            if title and link:
                items.append({"title": title, "link": link, "summary": truncate(summary, SUMMARY_MAX_CHARS), "pub": pub})

    return items


def build_category(name: str, sources: list) -> list:
    all_items = []
    for src in sources:
        try:
            items = fetch_feed_items(src["url"])
            for it in items:
                it["source"] = src["name"]
            all_items.extend(items)
        except Exception as e:
            print(f"[WARN] Fallo el feed {src['name']} ({src['url']}): {e}")
    return all_items


AD_SLOT_HTML = """
<div class="ad-slot" data-ad-format="auto">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{client}"
       data-ad-slot="0000000000"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>
""".strip()


def render_article(item: dict) -> str:
    return f"""
    <article class="card">
      <h3><a href="{html.escape(item['link'])}" target="_blank" rel="noopener nofollow">{html.escape(item['title'])}</a></h3>
      <p class="summary">{html.escape(item['summary'])}</p>
      <div class="meta">Fuente: {html.escape(item['source'])}</div>
    </article>
    """.strip()


def render_page(title: str, categories: dict, active: str) -> str:
    nav_items = "".join(
        f'<a href="{"index.html" if c == "todas" else c + ".html"}" class="{"active" if c == active else ""}">{c.capitalize()}</a>'
        for c in ["todas", "regional", "nacional", "internacional"]
    )

    sections = []
    for cat_name, items in categories.items():
        if not items:
            continue
        cards = "".join(render_article(it) for it in items)
        sections.append(f'<section class="category"><h2>{cat_name.capitalize()}</h2><div class="grid">{cards}</div></section>')
        sections.append(AD_SLOT_HTML.format(client=ADSENSE_CLIENT_ID))

    body = "\n".join(sections) if sections else "<p>No hay noticias disponibles en este momento.</p>"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - {SITE_NAME}</title>
<meta name="description" content="Agregador automático de noticias regionales, nacionales e internacionales.">
<link rel="stylesheet" href="style.css">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_MEASUREMENT_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA_MEASUREMENT_ID}');
</script>
</head>
<body>
<header class="site-header">
  <h1>{SITE_NAME}</h1>
  <p class="tagline">Noticias regionales, nacionales e internacionales, actualizadas automáticamente.</p>
  <nav>{nav_items}</nav>
</header>
{AD_SLOT_HTML.format(client=ADSENSE_CLIENT_ID)}
<main>
{body}
</main>
<footer class="site-footer">
  <p>Contenido agregado automáticamente a partir de fuentes públicas. Cada nota enlaza a la fuente original.</p>
  <p>Última actualización: {updated}</p>
</footer>
</body>
</html>"""


def main():
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(exist_ok=True)

    css_src = Path(__file__).resolve().parent / "style_template.css"
    (OUT_DIR / "style.css").write_text(css_src.read_text(encoding="utf-8"), encoding="utf-8")

    categories = {}
    for cat_name, sources in feeds.items():
        print(f"Procesando categoría: {cat_name}")
        categories[cat_name] = build_category(cat_name, sources)

    # Página "todas" (index)
    (OUT_DIR / "index.html").write_text(render_page("Inicio", categories, "todas"), encoding="utf-8")

    # Páginas por categoría
    for cat_name in categories:
        single = {cat_name: categories[cat_name]}
        (OUT_DIR / f"{cat_name}.html").write_text(render_page(cat_name.capitalize(), single, cat_name), encoding="utf-8")

    print("Sitio generado en", OUT_DIR)


if __name__ == "__main__":
    main()

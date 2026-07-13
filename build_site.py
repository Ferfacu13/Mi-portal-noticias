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

ROOT = Path(__file__).resolve().parent
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


DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga_es(dt: datetime) -> str:
    return f"{DIAS_ES[dt.weekday()]} {dt.day} de {MESES_ES[dt.month - 1]} de {dt.year}"


def truncate(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "a": "http://www.w3.org/2005/Atom",
}

IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_image_rss(item) -> str:
    """Busca una imagen destacada en un <item> de RSS 2.0, probando varias
    convenciones comunes en orden de confiabilidad."""
    enclosure = item.find("enclosure")
    if enclosure is not None:
        url = enclosure.get("url", "")
        type_ = enclosure.get("type", "")
        if url and (type_.startswith("image") or re.search(r"\.(jpg|jpeg|png|webp|gif)", url, re.IGNORECASE)):
            return url

    media_content = item.find("media:content", NS)
    if media_content is not None and media_content.get("url"):
        return media_content.get("url")

    media_thumb = item.find("media:thumbnail", NS)
    if media_thumb is not None and media_thumb.get("url"):
        return media_thumb.get("url")

    content_encoded = item.findtext("content:encoded", default="", namespaces=NS)
    if content_encoded:
        m = IMG_TAG_RE.search(content_encoded)
        if m:
            return m.group(1)

    desc = item.findtext("description", default="")
    if desc:
        m = IMG_TAG_RE.search(desc)
        if m:
            return m.group(1)

    return ""


def extract_image_atom(entry) -> str:
    media_content = entry.find("media:content", NS)
    if media_content is not None and media_content.get("url"):
        return media_content.get("url")

    media_thumb = entry.find("media:thumbnail", NS)
    if media_thumb is not None and media_thumb.get("url"):
        return media_thumb.get("url")

    for link_el in entry.findall("a:link", NS):
        if link_el.get("rel") == "enclosure" and (link_el.get("type", "").startswith("image")):
            return link_el.get("href", "")

    summary = entry.findtext("a:summary", default="", namespaces=NS) or entry.findtext("a:content", default="", namespaces=NS)
    if summary:
        m = IMG_TAG_RE.search(summary)
        if m:
            return m.group(1)

    return ""


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
        image = extract_image_rss(item)
        if title and link:
            items.append({
                "title": title, "link": link,
                "summary": truncate(desc, SUMMARY_MAX_CHARS),
                "pub": pub, "image": image,
            })

    # Atom fallback
    if not items:
        for entry in root.findall(".//a:entry", NS)[:MAX_ITEMS_PER_FEED]:
            title = strip_tags(entry.findtext("a:title", default="", namespaces=NS))
            link_el = entry.find("a:link", NS)
            link = link_el.get("href") if link_el is not None else ""
            summary = strip_tags(entry.findtext("a:summary", default="", namespaces=NS))
            pub = entry.findtext("a:updated", default="", namespaces=NS)
            image = extract_image_atom(entry)
            if title and link:
                items.append({
                    "title": title, "link": link,
                    "summary": truncate(summary, SUMMARY_MAX_CHARS),
                    "pub": pub, "image": image,
                })

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


CATEGORY_META = {
    "regional": {"label": "Regional", "class": "cat-regional"},
    "nacional": {"label": "Nacional", "class": "cat-nacional"},
    "internacional": {"label": "Internacional", "class": "cat-internacional"},
}


def render_article(item: dict, cat_name: str) -> str:
    cat = CATEGORY_META.get(cat_name, {"label": cat_name.capitalize(), "class": "cat-regional"})
    if item.get("image"):
        media_html = f'<img src="{html.escape(item["image"])}" alt="" loading="lazy" onerror="this.parentElement.classList.add(\'no-img\'); this.remove();">'
    else:
        media_html = ""
    media_class = "card-media" if item.get("image") else "card-media no-img"

    return f"""
    <article class="card">
      <div class="{media_class}">
        {media_html}
        <span class="badge {cat['class']}">{cat['label']}</span>
      </div>
      <div class="card-body">
        <h3><a href="{html.escape(item['link'])}" target="_blank" rel="noopener nofollow">{html.escape(item['title'])}</a></h3>
        <p class="summary">{html.escape(item['summary'])}</p>
        <div class="meta">
          <span class="source">{html.escape(item['source'])}</span>
          <a class="read-more" href="{html.escape(item['link'])}" target="_blank" rel="noopener nofollow">Leer nota completa →</a>
        </div>
      </div>
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
        cards = "".join(render_article(it, cat_name) for it in items)
        icon = {"regional": "📍", "nacional": "🇦🇷", "internacional": "🌎"}.get(cat_name, "📰")
        sections.append(
            f'<section class="category"><div class="category-head">'
            f'<h2><span class="cat-icon">{icon}</span>{cat_name.capitalize()}</h2>'
            f'<span class="category-line"></span></div>'
            f'<div class="grid">{cards}</div></section>'
        )
        sections.append(AD_SLOT_HTML.format(client=ADSENSE_CLIENT_ID))

    body = "\n".join(sections) if sections else '<p class="empty-state">No hay noticias disponibles en este momento. Volvé a intentarlo en unos minutos.</p>'
    now = datetime.now(timezone.utc)
    updated = now.strftime("%d/%m/%Y %H:%M UTC")
    updated_long = fecha_larga_es(now)

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
<div class="topbar">
  <span>{updated_long}</span>
  <span class="topbar-live"><span class="dot"></span> Actualizado {updated}</span>
</div>
<header class="site-header">
  <h1>{SITE_NAME}</h1>
  <p class="tagline">Noticias regionales, nacionales e internacionales, actualizadas automáticamente cada hora.</p>
  <nav>{nav_items}</nav>
</header>
{AD_SLOT_HTML.format(client=ADSENSE_CLIENT_ID)}
<main>
{body}
</main>
<footer class="site-footer">
  <p>{SITE_NAME} agrega titulares de fuentes públicas y siempre enlaza a la nota original — no reproducimos el artículo completo.</p>
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

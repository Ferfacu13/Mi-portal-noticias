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
ADS_FILE = ROOT / "ads.json"
OUT_DIR = ROOT / "site"
MAX_ITEMS_PER_FEED = 8
SUMMARY_MAX_CHARS = 180
REQUEST_TIMEOUT = 15

# ---- Configuración editable ----
SITE_NAME = "Confluye"
SITE_TAGLINE = "Toda la noticia, en un solo lugar."
GA_MEASUREMENT_ID = "G-XXXXXXXXXX"      # reemplazar por tu ID de Google Analytics 4
ADSENSE_CLIENT_ID = "ca-pub-5796284292656567"  # tu ID real de AdSense
# ---------------------------------

LOGO_SVG = """<svg class="logo-mark" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M4 36C13 36 13 12 24 12C35 12 35 36 44 36" stroke="#fff" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <circle cx="24" cy="12" r="4.5" fill="#fff"/>
</svg>"""

FOOTER_LINKS_HTML = (
    '<nav class="footer-links">'
    '<a href="aviso-legal.html">Aviso legal y derechos de autor</a>'
    '<a href="privacidad.html">Política de privacidad</a>'
    '<a href="preguntas-frecuentes.html">Preguntas frecuentes</a>'
    '<a href="pauta-publicitaria.html">Pautá con nosotros</a>'
    '</nav>'
)

# ---- Datos editables de la propuesta comercial ----
CONTACTO_PUBLICIDAD_EMAIL = "publicidad@confluye.com.ar"  # reemplazar por tu casilla real
CONTACTO_PUBLICIDAD_WHATSAPP = ""  # opcional: ej. "https://wa.me/549XXXXXXXXXX"
# ---------------------------------------------------


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


META_TAG_RE = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
CONTENT_ATTR_RE = re.compile(r'content=["\']([^"\']+)["\']', re.IGNORECASE)


def fetch_og_image(article_url: str) -> str:
    """Respaldo para feeds que no traen imagen: entra a la nota original y
    busca la imagen destacada que el propio medio define para redes sociales
    (og:image / twitter:image). Solo lee el principio del documento (donde
    vive el <head>) para no descargar la página entera."""
    try:
        req = urllib.request.Request(article_url, headers={"User-Agent": "Mozilla/5.0 (NewsAggregatorBot/1.0)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read(300_000)
        text = data.decode("utf-8", errors="ignore")
        for tag in META_TAG_RE.findall(text):
            if "og:image" in tag or "twitter:image" in tag:
                m = CONTENT_ATTR_RE.search(tag)
                if m and m.group(1).startswith("http"):
                    return m.group(1)
    except Exception:
        pass
    return ""


def build_category(name: str, sources: list) -> list:
    all_items = []
    for src in sources:
        try:
            items = fetch_feed_items(src["url"])
            for it in items:
                it["source"] = src["name"]
                if not it.get("image"):
                    it["image"] = fetch_og_image(it["link"])
            all_items.extend(items)
        except Exception as e:
            print(f"[WARN] Fallo el feed {src['name']} ({src['url']}): {e}")
    return all_items


AD_SLOT_HTML = """
<div class="ad-slot" data-ad-format="auto">
  <span class="ad-label">Publicidad</span>
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{client}"
       data-ad-slot="{slot}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>
""".strip()


def load_ads_config() -> list:
    try:
        data = json.loads(ADS_FILE.read_text(encoding="utf-8"))
        return data.get("placements", [])
    except FileNotFoundError:
        return []


def ads_for(ads_config: list, position: str, page_id: str, side: str = None) -> list:
    """Filtra las pautas que corresponden a esta posición y a esta pestaña."""
    result = []
    for p in ads_config:
        if p.get("position") != position:
            continue
        if position == "sidebar" and side is not None and p.get("side", "right") != side:
            continue
        pages = p.get("pages", ["*"])
        if "*" in pages or page_id in pages:
            result.append(p)
    return result


def render_ad(placement: dict) -> str:
    return AD_SLOT_HTML.format(client=ADSENSE_CLIENT_ID, slot=placement.get("slot", "0000000000"))


CATEGORY_META = {
    "regional": {"label": "Regional", "class": "cat-regional", "icon": "📍"},
    "nacional": {"label": "Nacional", "class": "cat-nacional", "icon": "🇦🇷"},
    "economia": {"label": "Economía", "class": "cat-economia", "icon": "💵"},
    "deportes": {"label": "Deportes", "class": "cat-deportes", "icon": "🏆"},
    "internacional": {"label": "Internacional", "class": "cat-internacional", "icon": "🌎"},
}


def render_article(item: dict, cat_name: str) -> str:
    cat = CATEGORY_META.get(cat_name, {"label": cat_name.capitalize(), "class": "cat-regional", "icon": "📰"})
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


def render_static_page(title: str, body_html: str, all_cats: list, meta_desc: str) -> str:
    """Páginas institucionales (legal, privacidad, FAQ): mismo header/nav/footer
    que el resto del sitio, pero sin grilla de noticias ni pauta publicitaria."""
    nav_categories = ["todas"] + all_cats
    nav_items = "".join(
        f'<a href="{"index.html" if c == "todas" else c + ".html"}">'
        f'{"Todas" if c == "todas" else CATEGORY_META.get(c, {"label": c.capitalize()})["label"]}</a>'
        for c in nav_categories
    )
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - {SITE_NAME}</title>
<meta name="description" content="{meta_desc}">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="site-header">
  <div class="brand">
    {LOGO_SVG}
    <h1>{SITE_NAME}</h1>
  </div>
  <p class="tagline">{SITE_TAGLINE}</p>
  <nav>{nav_items}</nav>
</header>
<main class="static-page">
{body_html}
</main>
<footer class="site-footer">
  {FOOTER_LINKS_HTML}
  <p>{SITE_NAME} agrega titulares de fuentes públicas y siempre enlaza a la nota original — no reproducimos el artículo completo.</p>
  <p>Última actualización: {updated}</p>
</footer>
</body>
</html>"""


def render_aviso_legal() -> str:
    return f"""
    <article class="legal">
      <h1>Aviso legal y derechos de autor</h1>
      <p>Este aviso regula el uso del sitio {SITE_NAME} (en adelante, "el Sitio").</p>

      <h2>1. Qué es {SITE_NAME}</h2>
      <p>{SITE_NAME} es un agregador automático de noticias: recopila títulos y copetes
      breves publicados en los canales RSS públicos de distintos medios de comunicación,
      y enlaza siempre a la nota original en el sitio del medio que la publicó.</p>

      <h2>2. Propiedad del contenido de terceros</h2>
      <p>Los títulos, copetes, imágenes y todo otro contenido mostrado que provenga de
      un medio de tercero le pertenecen a ese medio o a sus autores. {SITE_NAME} no
      reclama ninguna titularidad sobre ese contenido, no lo aloja de forma completa y
      en todos los casos identifica la fuente y enlaza directamente a la nota original.</p>
      <p>La reproducción se limita al título y a un copete breve (fair use / derecho de
      cita), conforme al artículo 10 de la Ley 11.723 de Propiedad Intelectual de la
      República Argentina, que permite la reproducción de fragmentos breves con fines
      informativos siempre que se cite la fuente.</p>

      <h2>3. Solicitud de baja de contenido</h2>
      <p>Si sos titular de un medio y preferís que tu contenido no aparezca en
      {SITE_NAME}, o si detectás un error en cómo mostramos tu material, escribinos a
      <strong>legal@confluye.com.ar</strong> (reemplazar por tu casilla real) indicando
      la URL de la nota en cuestión. Vamos a dar de baja el contenido a la brevedad.</p>

      <h2>4. Enlaces externos</h2>
      <p>El Sitio contiene enlaces a sitios de terceros. {SITE_NAME} no controla ni se
      responsabiliza por el contenido, disponibilidad o políticas de esos sitios.</p>

      <h2>5. Limitación de responsabilidad</h2>
      <p>El Sitio se ofrece "tal cual". {SITE_NAME} no garantiza la exactitud,
      actualidad o disponibilidad permanente del contenido agregado, dado que depende
      de la disponibilidad de los canales RSS de terceros.</p>

      <h2>6. Legislación aplicable</h2>
      <p>Este aviso se rige por las leyes de la República Argentina.</p>
    </article>
    """.strip()


def render_privacidad() -> str:
    return f"""
    <article class="legal">
      <h1>Política de privacidad</h1>
      <p>Última revisión: {fecha_larga_es(datetime.now(timezone.utc))}.</p>

      <h2>1. Datos que recolectamos</h2>
      <p>{SITE_NAME} no requiere registro ni cuenta de usuario, por lo que no
      recolectamos datos personales de forma directa. Utilizamos:</p>
      <ul>
        <li><strong>Google Analytics</strong>: estadísticas anónimas de visitas
        (páginas vistas, ubicación aproximada, dispositivo) para entender cómo se usa
        el Sitio.</li>
        <li><strong>Google AdSense</strong>: puede utilizar cookies para mostrar
        publicidad, incluyendo anuncios personalizados según tu actividad de
        navegación.</li>
      </ul>

      <h2>2. Cookies</h2>
      <p>Podés desactivar las cookies publicitarias personalizadas desde la
      <a href="https://adssettings.google.com/" target="_blank" rel="noopener">
      configuración de anuncios de Google</a>, o bloquear cookies directamente desde
      la configuración de tu navegador.</p>

      <h2>3. Menores de edad</h2>
      <p>El Sitio no está dirigido a menores de 13 años y no recolectamos a sabiendas
      información de menores.</p>

      <h2>4. Cambios en esta política</h2>
      <p>Podemos actualizar esta política ocasionalmente. La fecha de "última
      revisión" al inicio de esta página indica la versión vigente.</p>

      <h2>5. Contacto</h2>
      <p>Ante cualquier consulta sobre esta política, escribinos a
      <strong>privacidad@confluye.com.ar</strong> (reemplazar por tu casilla real).</p>
    </article>
    """.strip()


def render_faq() -> str:
    preguntas = [
        ("¿Qué es Confluye?",
         f"{SITE_NAME} es un portal que reúne, en un solo lugar, los titulares de "
         "distintos medios regionales, nacionales e internacionales, organizados por "
         "categoría: Regional, Nacional, Economía, Deportes e Internacional."),
        ("¿Por qué no puedo leer la nota completa acá?",
         "Porque no la copiamos. Mostramos el título y un copete breve, y siempre "
         "enlazamos a la nota completa en el sitio del medio que la publicó. Así "
         "respetamos los derechos de autor de cada fuente y le damos el tráfico a "
         "quien hizo el trabajo periodístico."),
        ("¿Cada cuánto se actualizan las noticias?",
         "El sitio se regenera automáticamente una vez por hora, las 24 horas."),
        ("¿De dónde salen las noticias?",
         "De los canales RSS públicos que cada medio publica. La lista completa de "
         "fuentes por categoría está en nuestro aviso legal."),
        ("Soy un medio y quiero que mis notas aparezcan en Confluye, ¿cómo hago?",
         "Escribinos a contacto@confluye.com.ar (reemplazar por tu casilla real) con "
         "el link a tu feed RSS público."),
        ("Encontré un error o quiero pedir que bajen una nota, ¿qué hago?",
         "Escribinos a legal@confluye.com.ar indicando la URL de la nota en "
         "cuestión y lo resolvemos a la brevedad."),
        ("¿Cómo hago publicidad en Confluye?",
         "Escribinos a publicidad@confluye.com.ar (reemplazar por tu casilla real) "
         "contándonos qué tipo de campaña tenés en mente."),
    ]
    items = "".join(
        f'<details class="faq-item"><summary>{q}</summary><p>{a}</p></details>'
        for q, a in preguntas
    )
    return f"""
    <article class="legal">
      <h1>Preguntas frecuentes</h1>
      {items}
    </article>
    """.strip()


def render_pauta_publicitaria() -> str:
    contacto_html = f'<a href="mailto:{CONTACTO_PUBLICIDAD_EMAIL}">{CONTACTO_PUBLICIDAD_EMAIL}</a>'
    if CONTACTO_PUBLICIDAD_WHATSAPP:
        contacto_html += (
            f' &nbsp;|&nbsp; <a href="{CONTACTO_PUBLICIDAD_WHATSAPP}" target="_blank" '
            f'rel="noopener">WhatsApp</a>'
        )

    return f"""
    <article class="legal pauta">
      <h1>Pautá con nosotros</h1>
      <p>{SITE_NAME} reúne en un solo lugar las noticias regionales, nacionales,
      de economía, deportes e internacionales que la gente lee todos los días.
      Si tu marca o negocio quiere llegar a esa audiencia, tenés varios formatos
      para elegir.</p>

      <h2>Formatos disponibles</h2>
      <ul>
        <li><strong>Banner superior</strong>: debajo del encabezado, visible en
        cualquier sección que elijas.</li>
        <li><strong>Banner entre noticias (in-feed)</strong>: integrado entre las
        tarjetas de noticias, con buena visibilidad sin resultar invasivo.</li>
        <li><strong>Banner lateral (sidebar)</strong>: acompaña la lectura en
        columna izquierda o derecha, en desktop.</li>
        <li><strong>Mención patrocinada en el newsletter</strong>: recomendación
        directa a nuestra base de suscriptores por email.</li>
      </ul>

      <h2>¿Por qué pautar acá?</h2>
      <ul>
        <li>Audiencia segmentada por categoría (por ejemplo, podés pautar solo
        en la sección Deportes si tu producto es de ese rubro).</li>
        <li>Contenido que se actualiza todo el día, sin costo de producción de tu parte.</li>
        <li>Contacto directo con quien administra el sitio: sin intermediarios
        ni mínimos de inversión imposibles para una pyme o negocio local.</li>
      </ul>

      <h2>Cómo arrancar</h2>
      <p>Escribinos contándonos tu rubro, el formato que te interesa y el
      tiempo de campaña que tenés en mente, y te mandamos una propuesta a medida:</p>
      <p class="pauta-contacto">{contacto_html}</p>

      <h2>Preguntas frecuentes sobre publicidad</h2>
      <details class="faq-item">
        <summary>¿Cuál es la inversión mínima?</summary>
        <p>Depende del formato y la duración. Contanos tu presupuesto y vemos
        qué opción se ajusta mejor.</p>
      </details>
      <details class="faq-item">
        <summary>¿Puedo pautar solo en una sección (por ejemplo, Deportes)?</summary>
        <p>Sí, los espacios se pueden configurar por sección.</p>
      </details>
      <details class="faq-item">
        <summary>¿Con cuánta anticipación tengo que reservar el espacio?</summary>
        <p>Cuanto antes nos escribas, mejor podemos coordinar fechas, pero
        consultanos igual aunque sea para la semana que viene.</p>
      </details>
    </article>
    """.strip()


def render_page(title: str, categories: dict, active: str, all_cats: list, ads_config: list) -> str:
    nav_categories = ["todas"] + all_cats
    nav_items = "".join(
        f'<a href="{"index.html" if c == "todas" else c + ".html"}" class="{"active" if c == active else ""}">'
        f'{"Todas" if c == "todas" else CATEGORY_META.get(c, {"label": c.capitalize()})["label"]}</a>'
        for c in nav_categories
    )

    in_feed_ads = [render_ad(p) for p in ads_for(ads_config, "in-feed", active)]

    sections = []
    for cat_name, items in categories.items():
        if not items:
            continue
        cards = "".join(render_article(it, cat_name) for it in items)
        meta = CATEGORY_META.get(cat_name, {"label": cat_name.capitalize(), "icon": "📰"})
        sections.append(
            f'<section class="category"><div class="category-head">'
            f'<h2><span class="cat-icon">{meta["icon"]}</span>{meta["label"]}</h2>'
            f'<span class="category-line"></span></div>'
            f'<div class="grid">{cards}</div></section>'
        )
        sections.extend(in_feed_ads)

    body = "\n".join(sections) if sections else '<p class="empty-state">No hay noticias disponibles en este momento. Volvé a intentarlo en unos minutos.</p>'
    now = datetime.now(timezone.utc)
    updated = now.strftime("%d/%m/%Y %H:%M UTC")
    updated_long = fecha_larga_es(now)

    top_ads = "".join(render_ad(p) for p in ads_for(ads_config, "top", active))
    left_ads = [render_ad(p) for p in ads_for(ads_config, "sidebar", active, side="left")]
    right_ads = [render_ad(p) for p in ads_for(ads_config, "sidebar", active, side="right")]

    aside_left = f'<aside class="sidebar sidebar-left">{"".join(left_ads)}</aside>' if left_ads else ""
    aside_right = f'<aside class="sidebar sidebar-right">{"".join(right_ads)}</aside>' if right_ads else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - {SITE_NAME}</title>
<meta name="description" content="Noticias regionales, nacionales, economía, deportes e internacionales, actualizadas automáticamente.">
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
  <div class="brand">
    {LOGO_SVG}
    <h1>{SITE_NAME}</h1>
  </div>
  <p class="tagline">{SITE_TAGLINE}</p>
  <nav>{nav_items}</nav>
</header>
{top_ads}
<div class="page-layout">
{aside_left}
<main>
{body}
</main>
{aside_right}
</div>
<footer class="site-footer">
  {FOOTER_LINKS_HTML}
  <p>{SITE_NAME} agrega titulares de fuentes públicas y siempre enlaza a la nota original — no reproducimos el artículo completo.</p>
  <p>Última actualización: {updated}</p>
</footer>
</body>
</html>"""


def main():
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    ads_config = load_ads_config()
    OUT_DIR.mkdir(exist_ok=True)

    css_src = Path(__file__).resolve().parent / "style_template.css"
    (OUT_DIR / "style.css").write_text(css_src.read_text(encoding="utf-8"), encoding="utf-8")

    categories = {}
    for cat_name, sources in feeds.items():
        print(f"Procesando categoría: {cat_name}")
        categories[cat_name] = build_category(cat_name, sources)

    all_cats = list(feeds.keys())

    # Página "todas" (index)
    (OUT_DIR / "index.html").write_text(
        render_page("Inicio", categories, "todas", all_cats, ads_config), encoding="utf-8"
    )

    # Páginas por categoría
    for cat_name in categories:
        single = {cat_name: categories[cat_name]}
        label = CATEGORY_META.get(cat_name, {"label": cat_name.capitalize()})["label"]
        (OUT_DIR / f"{cat_name}.html").write_text(
            render_page(label, single, cat_name, all_cats, ads_config), encoding="utf-8"
        )

    # Páginas institucionales
    (OUT_DIR / "aviso-legal.html").write_text(
        render_static_page("Aviso legal", render_aviso_legal(), all_cats,
                            "Aviso legal, derechos de autor y condiciones de uso de " + SITE_NAME),
        encoding="utf-8",
    )
    (OUT_DIR / "privacidad.html").write_text(
        render_static_page("Política de privacidad", render_privacidad(), all_cats,
                            "Política de privacidad y cookies de " + SITE_NAME),
        encoding="utf-8",
    )
    (OUT_DIR / "preguntas-frecuentes.html").write_text(
        render_static_page("Preguntas frecuentes", render_faq(), all_cats,
                            "Preguntas frecuentes sobre " + SITE_NAME),
        encoding="utf-8",
    )
    (OUT_DIR / "pauta-publicitaria.html").write_text(
        render_static_page("Pautá con nosotros", render_pauta_publicitaria(), all_cats,
                            "Espacios publicitarios y patrocinios en " + SITE_NAME),
        encoding="utf-8",
    )

    # ads.txt: obligatorio para que AdSense confirme quién puede vender
    # publicidad en el dominio. Se arma solo con tu ID real de AdSense.
    pub_id = ADSENSE_CLIENT_ID.replace("ca-pub-", "pub-")
    (OUT_DIR / "ads.txt").write_text(
        f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8"
    )

    print("Sitio generado en", OUT_DIR)


if __name__ == "__main__":
    main()

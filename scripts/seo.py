"""Static metadata and sitemap; never changes the site's noindex policy."""
from html import escape
import ipaddress
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from property_data import MARKETS
from property_views import facts, location, media_address, price

SITE_NAME = "Юлия Ларюшкина — недвижимость в Рязани"
MAIN = {
    "": ("Юлия Ларюшкина — агент по недвижимости в Рязани", "Покупка и продажа квартир в Рязани. Обсудите с Юлией Ларюшкиной район, бюджет и следующие шаги."),
    "catalog/": ("Объекты недвижимости — Юлия Ларюшкина", "Каталог объектов Юлии Ларюшкиной. Посмотрите предложения или обсудите поиск подходящей недвижимости."),
    "about/": ("О Юлии Ларюшкиной — агенте по недвижимости в Рязани", "Знакомство с Юлией Ларюшкиной: покупка и продажа квартир в Рязани, внимание Советскому району и этапы работы с клиентом."),
    "contacts/": ("Контакты Юлии Ларюшкиной — недвижимость в Рязани", "Телефон Юлии Ларюшкиной для обсуждения покупки или продажи недвижимости в Рязани."),
}


def normalize_public_url(value):
    if not isinstance(value, str) or not value or re.search(r"[\s\\\x00-\x1f]", value):
        raise ValueError("public_url: нужен публичный HTTPS-адрес сайта")
    parts = urlsplit(value)
    host = parts.hostname or ""
    if (parts.scheme != "https" or not host or parts.username or parts.password
            or parts.port not in (None, 443) or parts.query or parts.fragment
            or host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host):
        raise ValueError("public_url: HTTPS, без localhost, учётных данных, query и fragment")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("public_url: укажите публичное доменное имя, не IP-адрес")
    path = unquote(parts.path)
    if "\\" in path or any(part in (".", "..") for part in path.split("/")):
        raise ValueError("public_url: недопустимый путь")
    path = "/" + "/".join(part for part in path.split("/") if part)
    path = path.rstrip("/") + "/"
    return urlunsplit(("https", host.lower(), quote(path, safe="/-._~"), "", ""))


def public_site_url():
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "site.toml").read_text(encoding="utf-8"))
    return normalize_public_url(config.get("public_url"))


def absolute(public_url, route):
    # Routes are paths relative to the site, not to the host: keep the prefix.
    return public_url + quote(route.lstrip("/"), safe="/-._~")


def object_metadata(record):
    if record["status"] in ("sold", "withdrawn"):
        message = "Объект продан" if record["status"] == "sold" else "Объявление снято с публикации"
        return message + " — Юлия Ларюшкина", message + ". Посмотрите актуальные предложения или свяжитесь с Юлией.", None
    details = [record["title"], location(record)]
    if "market" in record:
        details.append(MARKETS[record["market"]])
    details.append(price(record))
    # Only filled core facts, without invented features or excerpts from free text.
    core = dict(record, features={})
    details.extend(f"{label}: {value}" for label, value in facts(core, plot_in_sotkas=True))
    image = None
    if record["photos"]:
        photo = record["photos"][record["cover"]]
        image = (media_address(record, photo["path"], "/").lstrip("/"), photo["alt"])
    return record["title"] + " — Юлия Ларюшкина", ". ".join(part for part in details if part) + ".", image


def metadata(public_url, route, title, description, image=None):
    canonical = absolute(public_url, route)
    def meta(key, value, attr="property"):
        return f'<meta {attr}="{key}" content="{escape(value, quote=True)}">'
    tags = [f'<link rel="canonical" href="{escape(canonical, quote=True)}">',
            meta("og:type", "website"), meta("og:locale", "ru_RU"),
            meta("og:site_name", SITE_NAME), meta("og:title", title),
            meta("og:description", description), meta("og:url", canonical),
            meta("twitter:card", "summary", "name"),
            meta("twitter:title", title, "name"), meta("twitter:description", description, "name")]
    if image:
        image_url = absolute(public_url, image[0])
        tags += [meta("og:image", image_url), meta("og:image:alt", image[1]),
                 meta("twitter:image", image_url, "name"), meta("twitter:image:alt", image[1], "name")]
    if route == "":
        structured = {"@context": "https://schema.org", "@type": "WebSite", "url": canonical,
                      "name": SITE_NAME, "inLanguage": "ru"}
        # Do not let a future text edit terminate the script element.
        encoded = json.dumps(structured, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        tags.append(f'<script type="application/ld+json">{encoded}</script>')
    return dict(title=escape(title), description=escape(description, quote=True), seo_tags="\n    ".join(tags))


def write_sitemap(output, public_url, records):
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}urlset")
    routes = list(MAIN)
    routes += [f'objects/{record["slug"]}/' for record in records
               if record["status"] == "active" and record["ever_published"] and not record["_fixture"]]
    for route in routes:
        entry = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(entry, f"{{{namespace}}}loc").text = absolute(public_url, route)
    ET.ElementTree(root).write(output / "sitemap.xml", encoding="utf-8", xml_declaration=True)

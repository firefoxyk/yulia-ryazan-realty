"""Small static builder. Python is needed only on the developer's machine."""
import argparse
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import sys
from string import Template
import tomllib
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Also support the existing importlib-based checks and browser utilities.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from property_data import load_catalog
from property_views import card, section, object_page, publish_media
from catalog_views import controls
DIST = ROOT / "dist"
PAGES = (
    ("", "Главная", "Юлия Ларюшкина — агент по недвижимости в Рязани. Покупка и продажа квартир."),
    ("catalog/", "Каталог", "Каталог недвижимости. Объявления готовятся к публикации."),
    ("about/", "Обо мне", "Юлия Ларюшкина: покупка и продажа квартир, новостройки и вторичный рынок в Рязани."),
    ("contacts/", "Контакты", "Связаться с Юлией Ларюшкиной по вопросам недвижимости в Рязани."),
)


def normalize_base(value):
    parts = value.strip("/").split("/") if value.strip("/") else []
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise ValueError("Базовый путь должен быть / или путём вида /yulia-ryazan-realty/.")
    return "/" + "/".join(parts) + ("/" if parts else "")


def settings(base=None, no_demo=False):
    config = tomllib.loads((ROOT / "site.toml").read_text(encoding="utf-8"))
    return normalize_base(base if base is not None else config["base_path"]), config["include_demo"] and not no_demo


def contacts():
    data = tomllib.loads((ROOT / "src/data/contacts.toml").read_text(encoding="utf-8"))
    number = data["phone_number"]
    if not re.fullmatch(r"\+[1-9]\d{6,14}", number) or re.sub(r"\D", "", data["phone_display"]) != number[1:]:
        raise ValueError("Некорректный номер телефона в src/data/contacts.toml")
    return dict(phone_href=f"tel:{number}", phone_display=escape(data["phone_display"]), full_name=escape(data["full_name"]))


def retry_windows_lock(operation, path, error):
    """A short Windows sharing lock must not break a rapid rebuild."""
    if getattr(error, "winerror", None) not in (32, 33):
        raise error
    for delay in (0.1, 0.2, 0.4, 0.8, 1.6):
        time.sleep(delay)
        try:
            operation(path)
            return
        except OSError as retry_error:
            if getattr(retry_error, "winerror", None) not in (32, 33):
                raise
            error = retry_error
    raise error


def build(base, include_demo, output=DIST, *, test_data=False, preliminary=False):
    # Keep the existing publication flag; it excludes development content only.
    if preliminary:
        include_demo = False
        test_data = False
    contact_values = contacts()
    records = load_catalog(test_data=test_data and include_demo)
    active = [record for record in records if record["status"] == "active"]
    output = output.resolve()
    # Only generated directories explicitly owned by this project may be replaced.
    if output != DIST and not (output.parent.parent == ROOT and output.parent.name.startswith(".check-")):
        raise ValueError("Недопустимая папка сборки")
    if output.exists():
        shutil.rmtree(output, onexc=retry_windows_lock)
    output.mkdir(parents=True)
    shutil.copytree(ROOT / "public", output, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".gitkeep"))
    layout = Template((ROOT / "src/templates/layout.html").read_text(encoding="utf-8"))
    pages = [(route, title, description, ROOT / "src/pages" / route / "index.html") for route, title, description in PAGES]
    if include_demo:
        pages.append(("objects/demo/", "Демонстрационная страница объекта", "Демонстрационный объект. Не является объявлением.", ROOT / "src/demo/routing-example.html"))
    def render(path, **values):
        return Template((ROOT / path).read_text(encoding="utf-8")).substitute(base=base, **values)

    legacy_demo = include_demo and not active and not test_data
    demo_cards = render("src/demo/card.html") if include_demo else ""
    demo_section = render("src/demo/collection.html", demo_cards=demo_cards) if legacy_demo else ""
    catalog_active = sorted(active, key=lambda record: record["id"])
    property_cards = "".join(card(record, base, plot_in_sotkas=True) for record in catalog_active) + (demo_cards if legacy_demo else "")
    if catalog_active:
        shutil.copyfile(ROOT / "src/assets/catalog.js", output / "assets/catalog.js")
    featured_cards = "".join(card(record, base) for record in active if record["featured"])
    property_section = section(featured_cards, base=base, synthetic=all(record["_fixture"] for record in active if record["featured"])) if featured_cards else demo_section
    if any(not record["_fixture"] for record in active):
        hero_description = "Посмотрите актуальные предложения в Рязани. А если подходящего варианта пока нет — расскажите мне, что вы ищете."
    elif active:
        hero_description = "В каталоге сейчас тестовые примеры, не реальные объявления. Расскажите мне, что вы ищете, — обсудим ваш запрос."
    else:
        hero_description = "Актуальные объекты пока не опубликованы. Расскажите мне, что вы ищете, — обсудим район, бюджет и важные для вас условия."
    photo_available = (ROOT / "public/images/yulia-laryushkina.jpg").is_file()
    portrait_content = (
        f'<img src="{base}images/yulia-laryushkina.jpg" alt="Юлия Ларюшкина, агент по недвижимости в Рязани" width="900" height="1125" fetchpriority="high" decoding="async">'
        if photo_available else render("src/templates/portrait-placeholder.html")
    )
    portrait = render("src/templates/portrait.html", portrait_class="portrait-photo" if photo_available else "portrait-art", portrait_content=portrait_content)
    if include_demo:
        shutil.copyfile(ROOT / "src/demo/property-placeholder.svg", output / "assets/demo-property.svg")
    publish_media(records, output)
    for record in records:
        if record["status"] == "draft" or not record["ever_published"]:
            continue
        title, page_content = object_page(record, base, **{key: contact_values[key] for key in ("phone_href", "phone_display")})
        pages.append((f'objects/{record["slug"]}/', title, "Информация об объекте недвижимости.", page_content))
    values = dict(
        portrait=portrait,
        demo_cards=demo_cards,
        demo_section=demo_section,
        property_cards=property_cards,
        property_section=property_section,
        hero_description=hero_description,
        **controls(catalog_active, base),
        catalog_intro='<p class="lead" data-demo="catalog-intro">Тестовые примеры, не реальные объявления.</p>' if test_data and include_demo else ('<p class="lead" data-demo="catalog-intro">Демонстрационный объект. Не является объявлением о продаже.</p>' if legacy_demo else ""),
        catalog_empty="" if property_cards else f'<div class="empty-state"><h2>Пока здесь нет опубликованных объектов.</h2><p>Расскажите Юлии, какую недвижимость вы ищете, — она поможет разобраться с вашим запросом.</p><a class="text-link" href="{base}contacts/">Связаться с Юлией ↗</a></div>',
        **contact_values,
    )
    for route, title, description, source in pages:
        navigation = "\n".join(
            f'<a href="{base}{path}"' + (' aria-current="page"' if path == route else '') + f'>{"Объекты" if path == "catalog/" else label}</a>'
            for path, label, _ in PAGES
        )
        content = Template(source.read_text(encoding="utf-8")).substitute(base=base, **values) if isinstance(source, Path) else source
        target = output / route / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(layout.substitute(
            title=escape(title), description=escape(description, quote=True),
            base=base, navigation=navigation, content=content, **contact_values,
            demo_banner='<div class="preview-banner" data-demo="banner">Демонстрационный режим · объекты не являются объявлениями</div>' if include_demo else "",
        ), encoding="utf-8")
    # GitHub Pages must serve assets without Jekyll processing.
    (output / ".nojekyll").touch()
    print(f"Собрано {len(pages)} страниц; base_path={base}; папка: {output}")


class PreviewHandler(SimpleHTTPRequestHandler):
    """Mount dist at its configured prefix; never fall back to index.html."""
    def __init__(self, *args, base="/", **kwargs):
        self.base = base
        super().__init__(*args, **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if self.base != "/" and not path.startswith(self.base):
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        path = urlsplit(self.path).path
        if self.base != "/" and not path.startswith(self.base):
            self.send_error(404)
            return
        super().do_HEAD()

    def translate_path(self, path):
        return super().translate_path("/" + path[len(self.base):])


def preview_server(base, output=DIST, port=8000):
    handler = partial(PreviewHandler, directory=str(output), base=base)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "dev", "preview"))
    parser.add_argument("--base-path", help="Overrides site.toml, e.g. /yulia-ryazan-realty/")
    parser.add_argument("--no-demo", action="store_true")
    parser.add_argument("--test-data", action="store_true", help="Include isolated synthetic properties (requires demo enabled)")
    parser.add_argument("--preliminary", action="store_true", help="Force demo and test data off; does not change noindex")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    base, demo = settings(args.base_path, args.no_demo)
    if args.command in ("build", "dev"):
        try:
            build(base, demo, test_data=args.test_data, preliminary=args.preliminary)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    if args.command in ("dev", "preview"):
        if not (DIST / "index.html").exists():
            parser.error("Сначала выполните build.")
        with preview_server(base, port=args.port) as server:
            print(f"http://127.0.0.1:{args.port}{base} (Ctrl+C — остановить)", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()

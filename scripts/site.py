"""Small static builder. Python is needed only on the developer's machine."""
import argparse
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
from string import Template
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PAGES = (
    ("", "Главная", "Персональный сайт брокера Юлии Ларюшкиной в Рязани."),
    ("catalog/", "Каталог", "Каталог недвижимости. Объявления готовятся к публикации."),
    ("about/", "Обо мне", "Информация о Юлии Ларюшкиной готовится к публикации."),
    ("contacts/", "Контакты", "Контакты Юлии Ларюшкиной будут добавлены позже."),
)


def normalize_base(value):
    parts = value.strip("/").split("/") if value.strip("/") else []
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise ValueError("Базовый путь должен быть / или путём вида /yulia-ryazan-realty/.")
    return "/" + "/".join(parts) + ("/" if parts else "")


def settings(base=None, no_demo=False):
    config = tomllib.loads((ROOT / "site.toml").read_text(encoding="utf-8"))
    return normalize_base(base if base is not None else config["base_path"]), config["include_demo"] and not no_demo


def build(base, include_demo, output=DIST):
    output = output.resolve()
    # Only generated directories explicitly owned by this project may be replaced.
    if output != DIST and not (output.parent.parent == ROOT and output.parent.name.startswith(".check-")):
        raise ValueError("Недопустимая папка сборки")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copytree(ROOT / "public", output, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".gitkeep"))
    layout = Template((ROOT / "src/templates/layout.html").read_text(encoding="utf-8"))
    pages = [(route, title, description, ROOT / "src/pages" / route / "index.html") for route, title, description in PAGES]
    if include_demo:
        pages.append(("objects/demo/", "Демонстрационная страница объекта", "Технический пример. Не является объявлением.", ROOT / "src/demo/routing-example.html"))
    for route, title, description, source in pages:
        navigation = "\n".join(
            f'<a href="{base}{path}"' + (' aria-current="page"' if path == route else '') + f'>{label}</a>'
            for path, label, _ in PAGES
        )
        demo_link = f'<p><a href="{base}objects/demo/">Демонстрационная страница объекта (не объявление)</a></p>' if include_demo else ""
        content = Template(source.read_text(encoding="utf-8")).substitute(base=base, demo_link=demo_link)
        target = output / route / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(layout.substitute(title=escape(title), description=escape(description, quote=True), base=base, navigation=navigation, content=content), encoding="utf-8")
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
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    base, demo = settings(args.base_path, args.no_demo)
    if args.command in ("build", "dev"):
        build(base, demo)
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

"""Audit the exact, deliberately small preliminary Pages artifact."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

import importlib.util

spec = importlib.util.spec_from_file_location("site_builder", Path(__file__).with_name("site.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

BASE = "/yulia-ryazan-realty/"
PAGES = {"index.html", "catalog/index.html", "about/index.html", "contacts/index.html"}
FILES = PAGES | {"assets/styles.css", "images/yulia-laryushkina.jpg", ".nojekyll"}


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.ids = set()
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        self.urls.extend(attrs[key] for key in ("href", "src") if key in attrs)
        if tag == "meta" and attrs.get("name") == "robots":
            self.noindex = {value.strip() for value in attrs.get("content", "").split(",")} == {"noindex", "nofollow"}


def audit(output=builder.DIST):
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    assert actual == FILES, f"Unexpected publication files: extra={actual - FILES}; missing={FILES - actual}"
    assert not any(p.is_symlink() for p in output.rglob("*")), "Links in publication artifact"
    parsed = {}
    for relative in PAGES:
        html = (output / relative).read_text(encoding="utf-8")
        for marker in ('data-demo=', 'data-review=', 'objects/', 'property-media/', 'test-apartment', '${', 'Предварительная версия', 'для согласования', 'подтвердить с Юлией', 'перед полноценным запуском'):
            assert marker not in html, (relative, marker)
        page = Document()
        page.feed(html)
        assert page.noindex, (relative, "Missing noindex, nofollow")
        parsed[relative] = page
    for relative, page in parsed.items():
        assert builder.contacts()["phone_href"] in page.urls
        for link in page.urls:
            if builder.contacts()["max_url"] and link == builder.contacts()["max_url"]:
                continue
            parts = urlsplit(link)
            if parts.scheme == "tel":
                assert link == builder.contacts()["phone_href"], (relative, link)
                continue
            assert not parts.scheme and not parts.netloc and not parts.query, (relative, link)
            if not parts.path:
                assert unquote(parts.fragment) in page.ids, (relative, link)
                continue
            assert parts.path.startswith(BASE), (relative, link)
            target = unquote(parts.path[len(BASE):])
            assert ".." not in target.split("/"), link
            if not target or target.endswith("/"):
                target += "index.html"
            assert target in FILES, (relative, link)
            if parts.fragment:
                assert target in parsed and unquote(parts.fragment) in parsed[target].ids, link
    assert 'id="properties-title"' not in (output / "index.html").read_text(encoding="utf-8")
    assert "Пока здесь нет опубликованных объектов." in (output / "catalog/index.html").read_text(encoding="utf-8")
    assert (output / "images/yulia-laryushkina.jpg").read_bytes() == (builder.ROOT / "public/images/yulia-laryushkina.jpg").read_bytes()
    print("OK: preliminary artifact; exactly 4 HTML pages, CSS, Julia photo, .nojekyll; no demo/test/private files or editorial notices; links, phone, noindex/nofollow verified")


if __name__ == "__main__":
    audit()

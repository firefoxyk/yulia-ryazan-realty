"""Integration checks for static routing and local links, without dependencies."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, build_opener

# Local checks must not send loopback traffic to a system HTTP proxy.
urlopen = build_opener(ProxyHandler({})).open

# 'site' is also a Python standard module; load our builder unambiguously.
import importlib.util

spec = importlib.util.spec_from_file_location("site_builder", Path(__file__).with_name("site.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        self.urls.extend(attrs[key] for key in ("href", "src") if key in attrs)


def verify(base, demo, output):
    records = builder.load_catalog()
    active = [record for record in records if record["status"] == "active"]
    builder.build(base, demo, output)
    expected = {"index.html", "catalog/index.html", "about/index.html", "contacts/index.html"}
    if demo:
        expected.add("objects/demo/index.html")
    expected.update(f'objects/{record["slug"]}/index.html' for record in records if record["ever_published"] and record["status"] != "draft")
    assert {str(p.relative_to(output)).replace("\\", "/") for p in output.rglob("*.html")} == expected
    with builder.preview_server(base, output, port=0) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            for relative in sorted(expected):
                route = relative.removesuffix("index.html")
                url = origin + base + route
                # Separate requests also exercise direct loads and page refreshes.
                for _ in range(2):
                    with urlopen(url) as response:
                        assert response.status == 200
                        html = response.read().decode("utf-8")
                assert '<html lang="ru">' in html
                assert 'name="viewport"' in html
                assert "${" not in html
                assert "област" not in html.lower(), (relative, "Unconfirmed service area")
                contact = builder.contacts()
                assert f'href="{contact["phone_href"]}"' in html
                assert contact["phone_display"] in html
                if not demo:
                    for marker in ('data-demo=', 'objects/demo/', 'demo-property.svg', '8 400 000', 'после согласования', 'Место для фотографии'):
                        assert marker not in html, (relative, marker)
                parsed = Links()
                parsed.feed(html)
                for link in parsed.urls:
                    if urlsplit(link).scheme == "tel":
                        assert link == contact["phone_href"], (relative, link)
                        continue
                    if contact["max_url"] and link == contact["max_url"]:
                        continue  # Validate rendering only; never send messages or open a messenger.
                    if link.startswith("#"):
                        assert link[1:] in parsed.ids
                        continue
                    path = urlsplit(link).path
                    assert path.startswith(base), (url, link)
                    with urlopen(urljoin(url, link)) as response:
                        assert response.status == 200
            assert (output / "assets/demo-property.svg").exists() == demo
            for relative in ("index.html", "about/index.html"):
                page_html = (output / relative).read_text(encoding="utf-8")
                photo_exists = (builder.ROOT / "public/images/yulia-laryushkina.jpg").is_file()
                assert (f'src="{base}images/yulia-laryushkina.jpg"' in page_html) == photo_exists
                if photo_exists:
                    assert 'alt="Юлия Ларюшкина, агент по недвижимости в Рязани"' in page_html
                    assert 'class="portrait-arch"' not in page_html
                    assert (output / "images/yulia-laryushkina.jpg").read_bytes() == (builder.ROOT / "public/images/yulia-laryushkina.jpg").read_bytes()
            home_html = (output / "index.html").read_text(encoding="utf-8")
            expected_sections = ['id="hero-title"']
            if (demo and not active) or any(record["featured"] for record in active):
                expected_sections.append('id="properties-title"')
                assert '<h2 id="properties-title">Актуальные предложения</h2>' in home_html
            else:
                assert 'id="properties-title"' not in home_html
            expected_sections.extend(('id="services-title"', 'id="intro-title"', 'id="contact-title"'))
            positions = [home_html.index(marker) for marker in expected_sections]
            assert positions == sorted(positions), "Unexpected home section order"
            for material in ("Покупателям", "Собственникам", "Обсудить покупку", "Обсудить продажу", "Советскому району"):
                assert material in home_html, (demo, material)
            assert "Новоселье" in (output / "about/index.html").read_text(encoding="utf-8")
            contact_html = (output / "contacts/index.html").read_text(encoding="utf-8")
            assert "wa.me" not in contact_html and "t.me/" not in contact_html
            assert ('>Написать в MAX</a>' in contact_html) == bool(builder.contacts()["max_url"])
            if demo and not active:
                assert 'data-demo="property-card"' in (output / "index.html").read_text(encoding="utf-8")
                assert 'data-demo="property-card"' in (output / "catalog/index.html").read_text(encoding="utf-8")
            missing = [base + "missing/"]
            if not demo:
                missing.append(base + "objects/demo/")
                assert "Демонстрационная" not in (output / "catalog/index.html").read_text(encoding="utf-8")
            if base != "/":
                missing.append("/catalog/")
            for path in missing:
                try:
                    urlopen(origin + path)
                except HTTPError as error:
                    assert error.code == 404
                else:
                    raise AssertionError(f"Expected 404: {path}")
        finally:
            server.shutdown()
            worker.join()
    print(f"OK: прямые адреса, повторные запросы, ссылки, CSS, 404; base={base}; demo={demo}")


if __name__ == "__main__":
    with TemporaryDirectory(prefix=".check-", dir=builder.ROOT) as temporary:
        output = Path(temporary) / "dist"
        verify("/", True, output)
        verify("/yulia-ryazan-realty/", True, output)
        # Rebuild the same output to ensure a disabled demo leaves no stale page.
        verify("/yulia-ryazan-realty/", False, output)
        verify("/", False, output)
        shutil.rmtree(temporary, onexc=builder.retry_windows_lock)
    subprocess.run([sys.executable, "-X", "utf8", str(builder.ROOT / "scripts/check_properties.py")], check=True)
    subprocess.run([sys.executable, "-X", "utf8", str(builder.ROOT / "scripts/check_catalog.py")], check=True)
    subprocess.run([sys.executable, "-X", "utf8", str(builder.ROOT / "scripts/check_gallery.py")], check=True)
    subprocess.run([sys.executable, "-X", "utf8", str(builder.ROOT / "scripts/check_client_journeys.py")], check=True)
    print("Все проверки пройдены.")

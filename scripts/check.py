"""Integration checks for static routing and local links, without dependencies."""
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

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
    builder.build(base, demo, output)
    expected = {"index.html", "catalog/index.html", "about/index.html", "contacts/index.html"}
    if demo:
        expected.add("objects/demo/index.html")
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
                parsed = Links()
                parsed.feed(html)
                for link in parsed.urls:
                    if link.startswith("#"):
                        assert link[1:] in parsed.ids
                        continue
                    path = urlsplit(link).path
                    assert path.startswith(base), (url, link)
                    with urlopen(urljoin(url, link)) as response:
                        assert response.status == 200
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
    print("Все проверки пройдены.")

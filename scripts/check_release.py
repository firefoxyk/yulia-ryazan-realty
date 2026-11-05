"""Audit the publication artifact against validated public sources."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, unquote
from xml.etree import ElementTree as ET
import importlib.util

spec = importlib.util.spec_from_file_location("release_builder", Path(__file__).with_name("site.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
BASE = "/yulia-ryazan-realty/"
MAIN_PAGES = {"index.html", "catalog/index.html", "about/index.html", "contacts/index.html"}
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.urls = []; self.ids = set(); self.canonical = []; self.metadata = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical.append(attrs.get("href"))
            return
        if tag == "meta":
            key = attrs.get("property", attrs.get("name"))
            if key:
                require(key not in self.metadata, f"Duplicate metadata: {key}")
                self.metadata[key] = attrs.get("content")
        if "id" in attrs:
            self.ids.add(attrs["id"])
        self.urls.extend(attrs[key] for key in ("href", "src") if key in attrs)


def manifest(records):
    """Only declared pages and actually used media; no recursive allowance."""
    pages = set(MAIN_PAGES)
    sources = {"assets/styles.css": builder.ROOT / "public/assets/styles.css"}
    photo = builder.ROOT / "public/images/yulia-laryushkina.jpg"
    if photo.is_file():
        sources["images/yulia-laryushkina.jpg"] = photo
    if any(r["status"] == "active" for r in records):
        for name in ("catalog.js", "object.js"):
            sources["assets/" + name] = builder.ROOT / "src/assets" / name
    for record in records:
        require(not record["_fixture"], "Fixture record is not allowed")
        require(record["status"] != "draft", "Public draft record is not allowed")
        if record["ever_published"]:
            pages.add(f'objects/{record["slug"]}/index.html')
        if record["status"] != "active":
            continue
        paths = {photo["path"] for photo in record["photos"]}
        if "floor_plan" in record:
            paths.add(record["floor_plan"])
        for path in paths:
            sources[f'property-media/public/{record["id"]}/{path}'] = record["_media_root"] / path
    return pages, sources


def comparable(path):
    if path.suffix in (".html", ".css", ".js", ".xml"):
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return path.read_bytes()


def audit(output=builder.DIST, base=None):
    output = Path(output).absolute()
    base = builder.normalize_base(BASE if base is None else base)
    require(output.is_dir() and not output.is_symlink() and not output.is_junction(), "Missing or linked artifact directory")
    records = builder.load_catalog(test_data=False)
    pages, sources = manifest(records)
    files = pages | sources.keys() | {"sitemap.xml", ".nojekyll"}
    directories = {p.as_posix() for name in files for p in Path(name).parents if p != Path(".")}
    entries = list(output.rglob("*"))
    for path in [output] + entries:
        require(not path.is_symlink() and not path.is_junction(), "Links/junctions in artifact")
        if path != output and path.is_dir():
            require(path.relative_to(output).as_posix() in directories, "Unexpected artifact directory")
    actual = {p.relative_to(output).as_posix() for p in entries if p.is_file()}
    require(actual == files, f"Unexpected publication files: extra={actual-files}; missing={files-actual}")
    for relative, source in sources.items():
        require(comparable(output / relative) == comparable(source), f"Resource differs from source: {relative}")

    contact = builder.contacts()
    public_url = builder.seo.public_site_url()
    active = [r for r in records if r["status"] == "active"]
    by_page = {f'objects/{r["slug"]}/index.html': r for r in records if r["ever_published"]}
    external = {contact["max_url"]} if contact["max_url"] else set()
    external.update(r[key] for r in active for key in ("video_url", "tour_url") if key in r)
    parsed = {}
    for relative in pages:
        html = (output / relative).read_text(encoding="utf-8")
        for marker in ('data-demo=', 'data-review=', '${', 'property-media/test/', 'objects/demo/', 'assets/demo-property.svg',
                       'Предварительная версия', 'для согласования', 'подтвердить с Юлией', 'перед полноценным запуском'):
            require(marker not in html, f"Development marker in {relative}")
        page = Document(html)
        require(page.metadata.get("robots") == "noindex, nofollow", f"Missing noindex/nofollow: {relative}")
        canonical = builder.seo.absolute(public_url, relative.removesuffix("index.html"))
        require(page.canonical == [canonical] and page.metadata.get("og:url") == canonical, f"Wrong canonical/OG URL: {relative}")
        record = by_page.get(relative)
        image = builder.seo.object_metadata(record)[2] if record else (("images/yulia-laryushkina.jpg", "") if "images/yulia-laryushkina.jpg" in sources else None)
        expected_image = builder.seo.absolute(public_url, image[0]) if image else None
        require(page.metadata.get("og:image") == expected_image, f"Wrong OG image: {relative}")
        require(contact["phone_href"] in page.urls, f"Missing phone: {relative}")
        if record and record["status"] in ("sold", "withdrawn"):
            # Old fields are deliberately unavailable to this independent minimal view.
            minimal = {key: record[key] for key in ("id", "slug", "status", "ever_published", "_fixture")}
            _, expected = builder.object_page(minimal, base, contact["phone_href"], contact["phone_display"], contact["max_url"])
            main = html.split('<main id="content" tabindex="-1">', 1)[1].split('</main>', 1)[0]
            require(main == expected, f"Unexpected inactive page content: {relative}")
        parsed[relative] = page
    for relative, page in parsed.items():
        for link in page.urls:
            if link in external or link == contact["phone_href"]:
                continue
            parts = urlsplit(link)
            require(not parts.scheme and not parts.netloc and not parts.query, f"Unapproved external/query link: {relative}")
            path = unquote(parts.path)
            require("\\" not in path and ".." not in path.split("/"), "Unsafe local link")
            if not path:
                require(unquote(parts.fragment) in page.ids, "Missing local anchor")
                continue
            require(path.startswith(base), f"Wrong link base: {relative}")
            target = path[len(base):]
            if not target or target.endswith("/"):
                target += "index.html"
            require(target in files, f"Missing link target: {relative}: {target}")
            if parts.fragment:
                require(target in parsed and unquote(parts.fragment) in parsed[target].ids, "Missing target anchor")

    sitemap = ET.parse(output / "sitemap.xml").getroot()
    require(sitemap.tag == f"{{{NS}}}urlset", "Invalid sitemap namespace")
    locations = [e.text for e in sitemap.findall(f"{{{NS}}}url/{{{NS}}}loc")]
    routes = list(builder.seo.MAIN) + [f'objects/{r["slug"]}/' for r in active if r["ever_published"]]
    require(len(locations) == len(routes) and set(locations) == {builder.seo.absolute(public_url, r) for r in routes}, "Unexpected sitemap URLs")

    # Rebuild only in a temporary generated directory, never in the audited output.
    # Exact comparison also catches altered inline JSON, metadata and stale HTML.
    with TemporaryDirectory(prefix=".check-release-reference-", dir=builder.ROOT) as directory:
        directory = Path(directory)
        require(directory.resolve().parent == builder.ROOT and directory.name.startswith(".check-release-reference-"), "Unsafe reference directory")
        try:
            reference = directory / "dist"
            builder.build(base, False, reference, preliminary=True)
            for relative in files:
                require(comparable(output / relative) == comparable(reference / relative), f"Artifact content mismatch: {relative}")
        finally:
            shutil.rmtree(directory, onexc=builder.retry_windows_lock)
    print(f"OK: publication audit; {len(pages)} pages, {len(sources)} approved resources; links, content, statuses, sitemap, metadata and noindex verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", default=BASE)
    parser.add_argument("--output", type=Path, default=builder.DIST)
    args = parser.parse_args()
    audit(args.output, args.base_path)

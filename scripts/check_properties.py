"""Meaningful regression tests for property data, publication and HTML safety."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
import tomllib
import unittest
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import property_data as data
import property_views as views

spec = importlib.util.spec_from_file_location("site_builder_properties", ROOT / "scripts/site.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
FIXTURES = ROOT / "tests/fixtures"
MEDIA = FIXTURES / "media"
DIRECT = build_opener(ProxyHandler({})).open


def fixture(name="apartment"):
    return tomllib.loads((FIXTURES / "properties" / f"{name}.toml").read_text(encoding="utf-8"))


class ResourceLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.urls.extend(values[key] for key in ("src", "href") if key in values)


class PropertyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix=".check-properties-", dir=ROOT)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "dist"

    def tearDown(self):
        assert self.directory.resolve().parent == ROOT and self.directory.name.startswith(".check-properties-")
        shutil.rmtree(self.directory, onexc=builder.retry_windows_lock)
        self.temporary.cleanup()

    def assert_invalid(self, raw, field, fixture_mode=True):
        with self.assertRaises(data.PropertyError) as caught:
            data.validate(raw, Path("broken-property.toml"), MEDIA, fixture_mode)
        self.assertIn("broken-property.toml", str(caught.exception))
        self.assertIn(field, str(caught.exception))

    def test_required_and_unknown_fields(self):
        for field in ("id", "slug", "status", "ever_published", "title", "type", "city", "description"):
            with self.subTest(field=field):
                raw = fixture()
                del raw[field]
                self.assert_invalid(raw, field)
        raw = fixture()
        raw["owner_phone"] = "SYNTHETIC-FORBIDDEN-FIELD"
        self.assert_invalid(raw, "owner_phone")

    def test_enumerations_and_strict_numeric_values(self):
        invalid = (
            ("type", "office"), ("market", "unknown"), ("status", "unknown"),
            ("type", []), ("market", []), ("status", []),
            ("price", -1), ("price", True), ("price", 4.2), ("price", float("inf")),
            ("area_m2", 0), ("area_m2", float("nan")), ("area_m2", -2),
            ("rooms", -1), ("rooms", 1.5), ("rooms", False),
            ("floor", 20), ("floors", 0), ("featured", "yes"),
            ("published_at", "2026-02-30"), ("currency", "USD"), ("cover", 8),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                raw = fixture()
                raw[field] = value
                self.assert_invalid(raw, field)

    def test_type_specific_and_optional_fields(self):
        land = data.validate(fixture("land"), "land.toml", MEDIA, True)
        self.assertNotIn("price", land)
        self.assertEqual(land["photos"], [])
        html = views.card(land, "/")
        self.assertIn("Цена по запросу", html)
        self.assertIn("Фотографии пока нет", html)
        self.assertNotIn("<dt>Этаж</dt>", html)
        self.assertNotIn("<dt>Комнаты</dt>", html)
        for field, value in (("floor", 1), ("market", "primary"), ("plot_unit", "acre")):
            raw = fixture("land")
            raw[field] = value
            self.assert_invalid(raw, field)
        apartment = fixture()
        for field in ("area_m2", "rooms", "floor", "floors", "price", "photos", "cover", "floor_plan", "features"):
            apartment.pop(field, None)
        minimal = data.validate(apartment, "optional.toml", MEDIA, True)
        self.assertNotIn('class="property-facts"', views.card(minimal, "/"))
        raw = fixture("house")
        del raw["plot_unit"]
        self.assert_invalid(raw, "plot_unit")

    def test_media_paths_files_and_safe_svg(self):
        for path in ("../outside.svg", "/outside.svg", "C:/outside.jpg", "shared/../../x.svg",
                     "shared\\room-a.svg", "https://example.test/a.jpg", "missing.jpg", "shared/room-a.svg?x=1"):
            with self.subTest(path=path):
                raw = fixture()
                raw["photos"][0]["path"] = path
                self.assert_invalid(raw, "photos[0].path")
        unsafe = self.directory / "unsafe.svg"
        unsafe.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', encoding="utf-8")
        with self.assertRaisesRegex(data.PropertyError, "photos"):
            data.image_file("unsafe.svg", self.directory, "unsafe.toml", "photos[0].path")
        invalid_image = self.directory / "invalid.jpg"
        invalid_image.write_text("not an image", encoding="utf-8")
        with self.assertRaisesRegex(data.PropertyError, "JPEG"):
            data.image_file("invalid.jpg", self.directory, "image.toml", "photos[0].path")

    def test_symlink_escape(self):
        media = self.directory / "media"
        media.mkdir()
        outside = self.directory / "outside.svg"
        outside.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        link = media / "linked.svg"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"OS does not allow symlink creation: {error}")
        with self.assertRaisesRegex(data.PropertyError, "за пределы"):
            data.image_file("linked.svg", media, "linked.toml", "photos[0].path")

    def test_text_and_url_safety(self):
        raw = fixture()
        raw["title"] = '<script>alert("title")</script>'
        raw["description"] = '<img src=x onerror=alert(1)>\nLiteral ${base} & text'
        raw["photos"][0]["alt"] = '" onload="alert(1)'
        raw["video_url"] = 'https://example.test/video?a=1&b=2'
        record = data.validate(raw, "text.toml", MEDIA, True)
        _, html = views.object_page(record, "/", "tel:+79657127848", "PHONE")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('Literal ${base} &amp; text', html)
        self.assertIn("a=1&amp;b=2", html)
        self.assertIn("alt=", html)
        for value in ("javascript:alert(1)", "//example.test/", "http://example.test/", "https://user:pass@example.test/", "https://example.test/\nattack"):
            raw = fixture()
            raw["tour_url"] = value
            self.assert_invalid(raw, "tour_url")

    def test_duplicates_and_reserved_urls(self):
        first = data.validate(fixture(), "first.toml", MEDIA, True)
        for field in ("id", "slug"):
            second = deepcopy(first)
            second["_source"] = "second.toml"
            other = "slug" if field == "id" else "id"
            second[other] = "another-value"
            with self.assertRaises(data.PropertyError) as caught:
                data.unique([first, second])
            self.assertIn("second.toml", str(caught.exception))
            self.assertIn("first.toml", str(caught.exception))
            self.assertIn(field, str(caught.exception))
        for slug in ("demo", "../escape", "With Space", "UPPER"):
            raw = fixture()
            raw["slug"] = slug
            self.assert_invalid(raw, "slug")

    def test_draft_policy_and_old_draft_ambiguity(self):
        self.assert_invalid(fixture("draft"), "status", fixture_mode=False)
        raw = fixture("draft")
        raw["ever_published"] = True
        self.assert_invalid(raw, "status")
        raw = fixture()
        raw["ever_published"] = False
        self.assert_invalid(raw, "ever_published")

    def test_loader_reports_file_syntax_and_collisions(self):
        records = self.directory / "records"
        records.mkdir()
        original = (FIXTURES / "properties/apartment.toml").read_text(encoding="utf-8")
        first = records / "first.toml"
        second = records / "second.toml"
        first.write_text(original, encoding="utf-8")
        second.write_text(original.replace('slug = "test-apartment"', 'slug = "other-apartment"'), encoding="utf-8")
        with self.assertRaisesRegex(data.PropertyError, "second.toml.*id"):
            data.load_directory(records, MEDIA)
        second.write_text(original.replace('id = "test-apartment"', 'id = "other-apartment"'), encoding="utf-8")
        with self.assertRaisesRegex(data.PropertyError, "second.toml.*slug"):
            data.load_directory(records, MEDIA)
        second.write_text("invalid TOML [", encoding="utf-8")
        with self.assertRaisesRegex(data.PropertyError, "second.toml.*TOML"):
            data.load_directory(records, MEDIA)

    def test_statuses_home_selection_and_resource_isolation(self):
        builder.build("/", True, self.output, test_data=True)
        catalog = (self.output / "catalog/index.html").read_text(encoding="utf-8")
        home = (self.output / "index.html").read_text(encoding="utf-8")
        for slug in ("test-apartment", "test-house", "test-land"):
            self.assertIn(f'/objects/{slug}/', catalog)
            self.assertTrue((self.output / f"objects/{slug}/index.html").exists())
        self.assertIn("/objects/test-apartment/", home)
        self.assertIn("/objects/test-land/", home)
        self.assertNotIn("/objects/test-house/", home)
        for slug, message in (("test-sold", "Объект продан"), ("test-withdrawn", "Объявление снято")):
            self.assertNotIn(f"/objects/{slug}/", catalog)
            self.assertNotIn(f"/objects/{slug}/", home)
            html = (self.output / f"objects/{slug}/index.html").read_text(encoding="utf-8")
            self.assertIn(message, html)
            self.assertIn('href="/catalog/"', html)
            self.assertIn('href="/contacts/"', html)
            self.assertNotIn("OLD-", html)
            self.assertNotIn("property-media", html)
        all_html = "".join(path.read_text(encoding="utf-8") for path in self.output.rglob("*.html"))
        self.assertNotIn("SYNTHETIC-DRAFT", all_html)
        self.assertNotIn("SYNTHETIC-PRIVATE", all_html)
        self.assertFalse((self.output / "objects/test-draft").exists())
        self.assertFalse(list(self.output.rglob("*.toml")))
        for name in ("old-only.svg", "draft-only.svg"):
            self.assertFalse(list(self.output.rglob(name)))

    def test_photos_order_cover_and_links(self):
        record = data.validate(fixture(), "apartment.toml", MEDIA, True)
        self.assertEqual([photo["path"] for photo in record["photos"]], ["shared/room-a.svg", "shared/room-b.svg"])
        self.assertEqual(record["cover"], 1)
        self.assertIn("room-b.svg", views.photo_html(record, "/prefix/"))
        _, html = views.object_page(record, "/prefix/", "tel:+79657127848", "PHONE")
        first_link = html.index('href="/prefix/property-media/test/test-apartment/shared/room-a.svg"')
        second_link = html.index('href="/prefix/property-media/test/test-apartment/shared/room-b.svg"')
        self.assertLess(first_link, second_link)
        self.assertIn("Главная фотография: вторая в списке", html)

    def test_real_pipeline_stable_slug_and_validation_before_overwrite(self):
        public_data = self.directory / "records"
        public_data.mkdir()
        source = public_data / "one.toml"
        original = (FIXTURES / "properties/apartment.toml").read_text(encoding="utf-8")
        source.write_text(original, encoding="utf-8")
        with patch.object(data, "DATA", public_data), patch.object(data, "MEDIA", MEDIA):
            builder.build("/", False, self.output)
            target = self.output / "objects/test-apartment/index.html"
            self.assertTrue(target.exists())
            source.write_text(original.replace("Тестовая квартира", "Другое название").replace("4200000", "4500000"), encoding="utf-8")
            builder.build("/", False, self.output)
            self.assertTrue(target.exists())
            self.assertIn("Другое название", target.read_text(encoding="utf-8"))
            self.assertIn("4 500 000", target.read_text(encoding="utf-8"))
            self.assertTrue((self.output / "property-media/public/test-apartment/shared/room-b.svg").exists())
            previous = target.read_bytes()
            source.write_text(original.replace("price = 4200000", "price = -1"), encoding="utf-8")
            with self.assertRaises(data.PropertyError) as caught:
                builder.build("/", False, self.output)
            self.assertIn("one.toml", str(caught.exception))
            self.assertIn("price", str(caught.exception))
            self.assertEqual(target.read_bytes(), previous)

    def test_never_published_inactive_record_has_no_page(self):
        raw = fixture("withdrawn")
        raw["ever_published"] = False
        record = data.validate(raw, "never-published.toml", MEDIA, True)
        with patch.object(builder, "load_catalog", return_value=[record]):
            builder.build("/", False, self.output)
        self.assertFalse((self.output / "objects/test-withdrawn").exists())

    def test_test_data_requires_explicit_flag_and_demo(self):
        builder.build("/", True, self.output)
        self.assertFalse((self.output / "objects/test-apartment").exists())
        self.assertFalse((self.output / "property-media/test").exists())
        builder.build("/", True, self.output, test_data=True)
        builder.build("/", False, self.output, test_data=True)
        self.assertFalse((self.output / "objects/test-apartment").exists())
        self.assertFalse((self.output / "objects/demo").exists())
        self.assertFalse((self.output / "property-media").exists())
        self.assertTrue((self.output / "images/yulia-laryushkina.jpg").exists())

    def test_http_root_subfolder_all_pages_and_media(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            with self.subTest(base=base):
                builder.build(base, True, self.output, test_data=True)
                with builder.preview_server(base, self.output, port=0) as server:
                    thread = Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    origin = f"http://127.0.0.1:{server.server_port}"
                    try:
                        for path in self.output.rglob("*.html"):
                            route = path.relative_to(self.output).as_posix().removesuffix("index.html")
                            url = origin + base + route
                            for _ in range(2):
                                with DIRECT(url, timeout=5) as response:
                                    self.assertEqual(response.status, 200)
                                    html = response.read().decode("utf-8")
                            parsed = ResourceLinks()
                            parsed.feed(html)
                            for link in parsed.urls:
                                if link.startswith(("tel:", "https:", "#")):
                                    continue
                                self.assertTrue(link.startswith(base), (route, link))
                                with DIRECT(origin + link, timeout=5) as response:
                                    self.assertEqual(response.status, 200)
                                    response.read()
                    finally:
                        server.shutdown()
                        thread.join()

    def test_preliminary_forces_synthetic_content_off_without_editorial_notices(self):
        from check_release import audit
        # Even conflicting development flags cannot enable fixtures in this mode.
        builder.build("/yulia-ryazan-realty/", True, self.output, test_data=True, preliminary=True)
        audit(self.output)

    def test_home_copy_distinguishes_empty_synthetic_and_public_inventory(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            with self.subTest(base=base):
                builder.build(base, False, self.output)
                home = (self.output / "index.html").read_text(encoding="utf-8")
                self.assertIn("Актуальные объекты пока не опубликованы", home)
                self.assertNotIn("Посмотрите актуальные предложения", home)
                self.assertNotIn('id="properties-title"', home)
                self.assertIn("Пока здесь нет опубликованных объектов.", (self.output / "catalog/index.html").read_text(encoding="utf-8"))
                builder.build(base, True, self.output, test_data=True)
                home = (self.output / "index.html").read_text(encoding="utf-8")
                self.assertIn("В каталоге сейчас тестовые примеры", home)
                self.assertNotIn("Посмотрите актуальные предложения", home)
                self.assertIn(f'href="{base}catalog/">Посмотреть все предложения', home)
                record = data.validate(fixture(), "public-example.toml", MEDIA, False)
                # A public active record without a home feature still makes the catalog nonempty.
                record["featured"] = False
                with patch.object(builder, "load_catalog", return_value=[record]):
                    builder.build(base, False, self.output)
                home = (self.output / "index.html").read_text(encoding="utf-8")
                self.assertIn("Посмотрите актуальные предложения в Рязани", home)
                self.assertNotIn("Актуальные объекты пока не опубликованы", home)
                self.assertNotIn('id="properties-title"', home)

    def assert_no_editorial_notices(self):
        for path in self.output.rglob("*.html"):
            html = path.read_text(encoding="utf-8")
            for marker in ("Предварительная версия", "для согласования", "подтвердить с Юлией", "перед полноценным запуском", "для обсуждения дизайна", 'data-review=', '${about_preview}', 'Место для фотографии'):
                self.assertNotIn(marker, html, (path, marker))
            self.assertIn('content="noindex, nofollow"', html)

    def test_no_editorial_notices_in_public_demo_and_test_modes(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            for demo, test_data, preliminary in ((True, False, False), (True, True, False), (False, False, False), (True, True, True)):
                with self.subTest(base=base, demo=demo, test_data=test_data, preliminary=preliminary):
                    builder.build(base, demo, self.output, test_data=test_data, preliminary=preliminary)
                    self.assert_no_editorial_notices()
                    home = (self.output / "index.html").read_text(encoding="utf-8")
                    if demo and not preliminary:
                        self.assertIn('data-demo="banner"', home)
                        self.assertIn("объекты не являются объявлениями", home)
                        self.assertIn('data-demo="property-card"' if not test_data else 'data-demo="fixture"', home)
                    else:
                        self.assertNotIn('class="preview-banner"', home)
                        self.assertIn("Пока здесь нет опубликованных объектов.", (self.output / "catalog/index.html").read_text(encoding="utf-8"))

    def test_public_active_and_inactive_pages_keep_visitor_messages(self):
        records = [record for record in data.load_catalog(True) if record["status"] != "draft"]
        for record in records:
            record["_fixture"] = False
        with patch.object(builder, "load_catalog", return_value=records):
            builder.build("/", False, self.output)
        self.assert_no_editorial_notices()
        for path in self.output.rglob("*.html"):
            self.assertNotIn('data-demo=', path.read_text(encoding="utf-8"))
        self.assertIn("Объект продан", (self.output / "objects/test-sold/index.html").read_text(encoding="utf-8"))
        self.assertIn("Объявление снято с публикации", (self.output / "objects/test-withdrawn/index.html").read_text(encoding="utf-8"))
        self.assertIn("Это предложение больше недоступно.", (self.output / "objects/test-sold/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

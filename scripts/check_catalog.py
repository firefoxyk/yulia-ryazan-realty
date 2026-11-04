"""Catalog generation regression checks; browser behavior has a separate check."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import check_properties as shared

builder, data = shared.builder, shared.data


class CatalogMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.options = {}
        self.current_select = None
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.current_select = attrs.get("name")
            self.options[self.current_select] = []
        if tag == "option" and self.current_select:
            self.options[self.current_select].append(attrs.get("value"))
        if "data-property-id" in attrs:
            self.ids.append(attrs["data-property-id"])

    def handle_endtag(self, tag):
        if tag == "select":
            self.current_select = None


def metadata(html):
    return json.loads(html.split('id="catalog-data">', 1)[1].split('</script>', 1)[0])


class CatalogTests(unittest.TestCase):
    setUp = shared.PropertyTests.setUp
    tearDown = shared.PropertyTests.tearDown

    def build_records(self, records, base="/"):
        with patch.object(builder, "load_catalog", return_value=records):
            builder.build(base, False, self.output)
        return (self.output / "catalog/index.html").read_text(encoding="utf-8")

    def test_options_appear_and_disappear_with_active_types_and_markets(self):
        records = data.load_catalog(True)
        public = [record for record in records if record["status"] == "active" and record["type"] != "land"]
        html = self.build_records(public)
        self.assertEqual(CatalogMarkup(html).options["type"], ["", "apartment", "house"])
        land = next(record for record in records if record.get("type") == "land" and record["status"] == "active")
        html = self.build_records(public + [land])
        self.assertIn("land", CatalogMarkup(html).options["type"])
        land = deepcopy(land)
        land["status"] = "withdrawn"
        html = self.build_records(public + [land])
        self.assertNotIn("land", CatalogMarkup(html).options["type"])
        primary = [record for record in public if record.get("market") == "primary"]
        html = self.build_records(primary)
        self.assertEqual(CatalogMarkup(html).options["market"], ["", "primary"])

    def test_only_active_metadata_and_minimal_fields_with_normalized_plot_units(self):
        builder.build("/", True, self.output, test_data=True)
        html = (self.output / "catalog/index.html").read_text(encoding="utf-8")
        rows = metadata(html)
        active = [record for record in data.load_catalog(True) if record["status"] == "active"]
        self.assertEqual({row["id"] for row in rows}, {record["id"] for record in active})
        self.assertEqual(CatalogMarkup(html).ids, sorted(row["id"] for row in rows))
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["test-land"]["plot_sotkas"], 15)
        self.assertEqual(by_id["test-land-priced"]["plot_sotkas"], 10)
        self.assertEqual(by_id["test-house"]["plot_sotkas"], 8)
        self.assertEqual(by_id["test-house-no-price"]["plot_sotkas"], 5)
        self.assertNotIn("price", by_id["test-land"])
        self.assertNotIn("rooms", by_id["test-house-no-price"])
        allowed = {"id", "type", "market", "price", "location", "rooms", "area_m2", "plot_sotkas", "published_at"}
        self.assertTrue(all(row.keys() <= allowed for row in rows))
        self.assertIn('id="catalog-filters" class="catalog-filters" hidden', html)
        self.assertIn("<noscript>", html)

    def test_no_dates_do_not_pretend_to_have_newest_sort(self):
        records = data.load_catalog(True)
        records = [record for record in records if record["status"] == "active"]
        for record in records:
            record.pop("published_at", None)
        html = self.build_records(records)
        self.assertNotIn("newest", CatalogMarkup(html).options["sort"])
        self.assertIn("без сортировки по новизне", html)

    def test_plot_units_precision_and_missing_values_without_mutating_records(self):
        cases = ((500, "m2", 5, "5 сот."), (805.3, "m2", 8.053, "8,053 сот."),
                 (1012.345, "m2", 10.12345, "10,12345 сот."), (1, "m2", .01, "0,01 сот."),
                 (8.25, "sotka", 8.25, "8,25 сот."), (.15025, "ha", 15.025, "15,025 сот."))
        for value, unit, converted, label in cases:
            with self.subTest(value=value, unit=unit):
                raw = shared.fixture("land")
                raw.update(plot_area=value, plot_unit=unit)
                record = data.validate(raw, "units.toml", shared.MEDIA, True)
                before = deepcopy(record)
                html = self.build_records([record])
                self.assertEqual(metadata(html)[0]["plot_sotkas"], converted)
                self.assertIn(label, html)
                self.assertIn("Площадь участка, сотки", html)
                self.assertIn("От, сот.", html)
                self.assertIn("До, сот.", html)
                self.assertEqual(record, before)
        record.pop("plot_area")
        record.pop("plot_unit")
        html = self.build_records([record])
        self.assertNotIn("plot_sotkas", metadata(html)[0])
        self.assertNotIn("<dt>Участок</dt>", html)

    def test_plot_conversion_is_scoped_to_catalog_cards(self):
        builder.build("/", True, self.output, test_data=True)
        self.assertIn("15 сот.", (self.output / "catalog/index.html").read_text(encoding="utf-8"))
        self.assertIn("0.15 га", (self.output / "index.html").read_text(encoding="utf-8"))
        self.assertIn("15 сот.", (self.output / "objects/test-land/index.html").read_text(encoding="utf-8"))

    def test_json_cannot_escape_script_element(self):
        record = next(record for record in data.load_catalog(True) if record["status"] == "active")
        record["city"] = '</script><script>alert("bad")</script>&'
        html = self.build_records([record])
        self.assertEqual(metadata(html)[0]["location"].split(" ")[0], record["city"])
        self.assertNotIn('<script>alert("bad")</script>', html)

    def test_root_subfolder_and_rebuild_remove_catalog_script_and_test_resources(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            builder.build(base, True, self.output, test_data=True)
            html = (self.output / "catalog/index.html").read_text(encoding="utf-8")
            self.assertIn(f'src="{base}assets/catalog.js"', html)
            self.assertTrue((self.output / "assets/catalog.js").exists())
            builder.build(base, True, self.output)
            self.assertFalse((self.output / "assets/catalog.js").exists())
            self.assertNotIn("catalog-data", (self.output / "catalog/index.html").read_text(encoding="utf-8"))
            builder.build(base, True, self.output, test_data=True, preliminary=True)
            html = (self.output / "catalog/index.html").read_text(encoding="utf-8")
            self.assertIn("Пока здесь нет опубликованных объектов.", html)
            self.assertNotIn('id="catalog-filters"', html)
            self.assertNotIn('id="catalog-no-results"', html)
            self.assertFalse((self.output / "assets/catalog.js").exists())
            self.assertFalse((self.output / "property-media").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""SEO regression checks; isolated records never become real public listings."""
from copy import deepcopy
from html.parser import HTMLParser
import json
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

import check_properties as shared
import seo

builder = shared.builder
NS = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


class Head(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.metas = {}; self.canonicals = []; self.title = ''; self.json = ''; self.in_title = False; self.in_json = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self.in_title = True
        if tag == 'meta': self.metas[attrs.get('property', attrs.get('name'))] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical': self.canonicals.append(attrs['href'])
        if tag == 'script' and attrs.get('type') == 'application/ld+json': self.in_json = True

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if tag == 'script': self.in_json = False

    def handle_data(self, text):
        if self.in_title: self.title += text
        if self.in_json: self.json += text


class SeoTests(unittest.TestCase):
    setUp = shared.PropertyTests.setUp
    tearDown = shared.PropertyTests.tearDown

    def page(self, route=''):
        return Head((self.output / route / 'index.html').read_text(encoding='utf-8'))

    def locations(self):
        root = ET.parse(self.output / 'sitemap.xml').getroot()
        self.assertEqual(root.tag, '{'+NS['s']+'}urlset')
        self.assertFalse(root.findall('.//s:lastmod', NS))
        return [node.text for node in root.findall('s:url/s:loc', NS)]

    def test_main_metadata_domain_and_prefix_are_independent_of_local_base(self):
        for public in ('https://firefoxyk.github.io/yulia-ryazan-realty/', 'https://realty.example.test/', 'https://realty.example.test/new-prefix/'):
            for base in ('/', '/yulia-ryazan-realty/'):
                with patch.object(seo, 'public_site_url', return_value=public):
                    builder.build(base, False, self.output)
                titles = []
                for route in seo.MAIN:
                    page = self.page(route)
                    titles.append(page.title)
                    self.assertEqual(page.canonicals, [public+route])
                    self.assertEqual(page.metas['og:url'], public+route)
                    self.assertEqual(page.metas['og:title'], page.title)
                    self.assertEqual(page.metas['og:description'], page.metas['description'])
                    self.assertEqual(page.metas['og:image'], public+'images/yulia-laryushkina.jpg')
                    self.assertEqual(page.metas['robots'], 'noindex, nofollow')
                    self.assertTrue(page.metas['description'])
                self.assertEqual(len(set(titles)), 4)
                self.assertEqual(set(self.locations()), {public+route for route in seo.MAIN})
                website = json.loads(self.page().json)
                self.assertEqual(website, {'@context':'https://schema.org', '@type':'WebSite', 'url':public, 'name':seo.SITE_NAME, 'inLanguage':'ru'})
                self.assertFalse((self.output/'robots.txt').exists())

    def test_public_url_validation_and_normalization(self):
        self.assertEqual(seo.normalize_public_url('https://EXAMPLE.test//new//prefix'), 'https://example.test/new/prefix/')
        for value in ('http://example.test/', 'https://localhost/', 'https://127.0.0.1/', 'https://[::1]/', 'https://example.test:8443/', 'https://user:pass@example.test/', 'https://example.test/?q=x', 'https://example.test/#x', 'https://example.test/../x', 'https://example.test/%2e%2e/x', None, ''):
            with self.subTest(value=value), self.assertRaises(ValueError): seo.normalize_public_url(value)

    def test_fixture_objects_use_cover_and_only_filled_facts(self):
        for base in ('/', '/yulia-ryazan-realty/'):
            builder.build(base, True, self.output, test_data=True)
            page = self.page('objects/test-apartment')
            self.assertIn('Тестовая квартира', page.title)
            self.assertIn('Тестовый город', page.metas['description'])
            self.assertIn('Первичный рынок', page.metas['description'])
            self.assertIn('4\xa0200\xa0000', page.metas['description'])
            self.assertIn('54.5 м²', page.metas['description'])
            self.assertTrue(page.metas['og:image'].endswith('/property-media/test/test-apartment/shared/room-b.svg'))
            self.assertEqual(page.metas['og:image:alt'], 'Тестовая нейтральная иллюстрация B')
            no_price = self.page('objects/test-house-no-price')
            self.assertIn('Цена по запросу', no_price.metas['description'])
            self.assertNotIn('og:image', no_price.metas)
            self.assertEqual(len(self.locations()), 4)
            builder.build(base, False, self.output)
            self.assertFalse((self.output/'objects/test-apartment').exists())
            self.assertFalse((self.output/'property-media').exists())

    def test_sitemap_public_active_only_and_stable_unavailable_pages(self):
        records = shared.data.load_catalog(True)
        for record in records: record['_fixture'] = False
        original = deepcopy(records)
        for base in ('/', '/yulia-ryazan-realty/'):
            with patch.object(builder, 'load_catalog', return_value=records): builder.build(base, False, self.output)
            public = seo.public_site_url()
            expected = {public+route for route in seo.MAIN} | {public+f'objects/{r["slug"]}/' for r in records if r['status']=='active'}
            self.assertEqual(set(self.locations()), expected)
            for slug in ('test-sold','test-withdrawn'):
                page = self.page('objects/'+slug)
                self.assertEqual(page.canonicals, [public+'objects/'+slug+'/'])
                self.assertNotIn('og:image', page.metas)
                self.assertNotIn('OLD-', page.title+page.metas['description'])
                self.assertEqual(page.metas['robots'], 'noindex, nofollow')
            self.assertFalse((self.output/'objects/test-draft').exists())
        self.assertEqual(original, records)
        record = deepcopy(next(r for r in records if r['status']=='active'))
        old_slug = record['slug']
        record['title'] = 'Другое название < & "'
        record['description'] = 'Другое описание'
        record.pop('price', None)
        record.pop('market', None)
        record.pop('area_m2', None)
        record['photos'] = []; record['cover'] = None
        with patch.object(builder, 'load_catalog', return_value=[record]): builder.build('/', False, self.output)
        page = self.page('objects/'+old_slug)
        self.assertIn(record['title'], page.title)
        self.assertNotIn('og:image', page.metas)
        self.assertNotIn('Первичный рынок', page.metas['description'])
        self.assertNotIn('Площадь:', page.metas['description'])
        self.assertIn(seo.absolute(public, 'objects/'+old_slug+'/'), self.locations())


if __name__ == '__main__':
    unittest.main(verbosity=2)

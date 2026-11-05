"""Publication audit tests: all ordinary-looking records live only in temp dirs."""
from contextlib import ExitStack
import hashlib
import importlib.util
from pathlib import Path
import shutil
from threading import Thread
import unittest
from unittest.mock import patch

import check_properties as shared

spec = importlib.util.spec_from_file_location('release_audit_tests', Path(__file__).with_name('check_release.py'))
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        shared.PropertyTests.setUp(self)
        self.records = self.directory/'records'; self.records.mkdir()
        self.media = self.directory/'media'
        shutil.copytree(shared.MEDIA, self.media)
        self.patches = ExitStack()
        self.patches.enter_context(patch.object(shared.data, 'DATA', self.records))
        self.patches.enter_context(patch.object(shared.data, 'MEDIA', self.media))

    def tearDown(self):
        self.patches.close()
        shared.PropertyTests.tearDown(self)

    def add(self, name):
        # Copy existing synthetic examples into an isolated normal-source directory.
        # They are never written to src/data/properties or the real dist.
        source = shared.FIXTURES/'properties'/f'{name}.toml'
        (self.records/source.name).write_bytes(source.read_bytes())

    def build(self, base='/'):
        shared.builder.build(base, False, self.output, preliminary=True)

    def check(self, base='/'):
        release.audit(self.output, base)

    def test_empty_publication_root_and_subfolder_read_only(self):
        for base in ('/', '/yulia-ryazan-realty/'):
            self.build(base)
            before = {p.relative_to(self.output):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.rglob('*') if p.is_file()}
            self.check(base)
            after = {p.relative_to(self.output):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((self.output/'assets/catalog.js').exists())

    def test_active_featured_commercial_photos_plan_and_http(self):
        self.add('apartment'); self.add('commercial')
        for base in ('/', '/yulia-ryazan-realty/'):
            self.build(base); self.check(base)
            pages, sources = release.manifest(shared.data.load_catalog())
            self.assertEqual(len(pages), 6)
            self.assertEqual(len([name for name in sources if name.startswith('property-media/')]), 5)
            self.assertIn('data-property-id="test-z-commercial"', (self.output/'index.html').read_text(encoding='utf-8'))
            self.assertIn('id="properties-title"', (self.output/'index.html').read_text(encoding='utf-8'))
            with shared.builder.preview_server(base, self.output, port=0) as server:
                thread = Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    for relative in pages | sources.keys() | {'sitemap.xml'}:
                        with shared.DIRECT(f'http://127.0.0.1:{server.server_port}'+base+relative) as response:
                            self.assertEqual(response.status, 200); response.read()
                finally:
                    server.shutdown(); thread.join()

    def test_inactive_pages_no_old_data_media_or_sitemap_entries(self):
        self.add('sold'); self.add('withdrawn')
        for base in ('/', '/yulia-ryazan-realty/'):
            self.build(base); self.check(base)
            self.assertFalse((self.output/'property-media').exists())
            for slug in ('test-sold','test-withdrawn'):
                html = (self.output/f'objects/{slug}/index.html').read_text(encoding='utf-8')
                self.assertNotIn('OLD-', html)
                self.assertNotIn(slug, (self.output/'sitemap.xml').read_text(encoding='utf-8'))
            target = self.output/'objects/test-sold/index.html'
            target.write_text(target.read_text(encoding='utf-8').replace('</main>', '<p>OLD-DATA</p></main>'),encoding='utf-8')
            with self.assertRaises(AssertionError): self.check(base)

    def test_extra_files_fake_page_and_test_resource_are_rejected(self):
        self.add('apartment')
        for name in ('.env', 'owners.csv', 'objects/fake/index.html', 'property-media/test/injected.svg', 'assets/unused.svg'):
            with self.subTest(name=name):
                self.build()
                target = self.output/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text('SYNTHETIC-UNAPPROVED',encoding='utf-8')
                with self.assertRaises(AssertionError): self.check()

    def test_changed_html_json_resources_and_sitemap_are_rejected(self):
        self.add('apartment')
        mutations = (
            ('index.html', lambda s:s.replace('noindex, nofollow','index, follow')),
            ('objects/test-apartment/index.html', lambda s:s.replace('rel="canonical" href="https://','rel="canonical" href="https://localhost/')),
            ('catalog/index.html', lambda s:s.replace('"id": "test-apartment"','"id": "fake-object"')),
            ('about/index.html', lambda s:s+'<!-- SYNTHETIC-UNAPPROVED -->'),
            ('sitemap.xml', lambda s:s.replace('</urlset>', '<url><loc>https://localhost/private/</loc></url></urlset>')),
            ('property-media/public/test-apartment/shared/room-b.svg', lambda s:s+'\n<!-- unapproved -->'),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                self.build(); target = self.output/name
                before = target.read_text(encoding='utf-8'); changed = mutate(before)
                self.assertNotEqual(before,changed)
                target.write_text(changed,encoding='utf-8')
                with self.assertRaises(AssertionError): self.check()
        self.build()
        (self.output/'property-media/public/test-apartment/shared/room-a.svg').unlink()
        with self.assertRaises(AssertionError): self.check()

    def test_explicit_external_materials_are_allowed_but_injected_links_are_not(self):
        self.add('apartment')
        path = self.records/'apartment.toml'
        # Insert before [features], so the URL belongs to the record's root table.
        path.write_text(path.read_text(encoding='utf-8').replace('[features]', 'video_url = "https://example.test/video?a=1&b=2"\n\n[features]'),encoding='utf-8')
        self.build(); self.check()
        target = self.output/'objects/test-apartment/index.html'
        target.write_text(target.read_text(encoding='utf-8').replace('</main>','<a href="https://unapproved.example.test/">Injected</a></main>'),encoding='utf-8')
        with self.assertRaises(AssertionError): self.check()

    def test_development_build_and_public_draft_cannot_pass(self):
        shared.builder.build('/',True,self.output,test_data=True)
        with self.assertRaises(AssertionError): self.check()
        self.build()
        self.add('draft')
        with self.assertRaises(shared.data.PropertyError): self.build()
        with self.assertRaises(shared.data.PropertyError): self.check()


if __name__ == '__main__':
    unittest.main(verbosity=2)

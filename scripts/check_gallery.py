"""Regression checks for generated object pages and gallery resource isolation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import check_properties as shared
from gallery_views import gallery

builder, data, views = shared.builder, shared.data, shared.views


class GalleryTests(unittest.TestCase):
    setUp = shared.PropertyTests.setUp
    tearDown = shared.PropertyTests.tearDown

    def test_cover_static_links_order_and_image_variants(self):
        record = data.validate(shared.fixture(), "photos.toml", shared.MEDIA, True)
        html = gallery(record, "/prefix/", views.media_address)
        self.assertIn('data-cover="1"', html)
        self.assertIn('Фото 2 из 3', html)
        self.assertIn('src="/prefix/property-media/test/test-apartment/shared/room-b.svg"', html)
        links = html.split('<ol class="gallery-thumbs">', 1)[1].split('</ol>', 1)[0]
        self.assertEqual(links.count('data-gallery-item'), 3)
        self.assertLess(links.index('room-a.svg'), links.index('room-b.svg'))
        self.assertLess(links.index('room-b.svg'), links.index('portrait-room.svg'))
        self.assertIn('hidden', html.split('data-gallery-controls', 1)[1].split('>', 1)[0])
        one = deepcopy(record)
        one["photos"] = record["photos"][:1]
        one["cover"] = 0
        html = gallery(one, "/", views.media_address)
        self.assertNotIn('data-gallery-prev', html)
        self.assertNotIn('data-gallery-next', html)
        self.assertIn('Фото 1 из 1', html)
        one["photos"] = []
        html = gallery(one, "/", views.media_address)
        self.assertIn('Фотографий пока нет', html)
        self.assertNotIn('<dialog', html)
        self.assertNotIn('<button', html)

    def test_only_present_content_safe_materials_and_sotkas(self):
        record = data.validate(shared.fixture("land"), "land.toml", shared.MEDIA, True)
        _, html = views.object_page(record, "/", "tel:+79657127848", "PHONE")
        self.assertIn('15 сот.', html)
        self.assertIn('Цена по запросу', html)
        self.assertNotIn('Дополнительные материалы', html)
        self.assertNotIn('<dt>Комнаты</dt>', html)
        self.assertIn('Заинтересовал объект?', html)
        self.assertIn('href="tel:+79657127848"', html)
        self.assertIn('data-copy-link hidden', html)
        self.assertIn('data-object-path="/objects/test-land/"', html)
        record["video_url"] = 'https://example.test/video?a=1&b=2'
        record["tour_url"] = 'https://example.test/tour'
        _, html = views.object_page(record, "/prefix/", "tel:+79657127848", "PHONE")
        self.assertIn('https://example.test/video?a=1&amp;b=2', html)
        self.assertIn('>Виртуальный тур</a>', html)
        self.assertNotIn('<iframe', html)

    def test_caption_and_alt_cannot_inject_markup(self):
        record = data.validate(shared.fixture(), "safe.toml", shared.MEDIA, True)
        record["photos"][0].update(alt='" onload="alert(1)', caption='<script>bad</script>')
        html = gallery(record, "/", views.media_address)
        self.assertNotIn('<script>bad</script>', html)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', html)
        self.assertIn('alt="&quot; onload=&quot;alert(1)"', html)

    def test_root_subfolder_and_cleanup_keep_inactive_pages_minimal(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            builder.build(base, True, self.output, test_data=True)
            self.assertTrue((self.output / "assets/object.js").is_file())
            html = (self.output / "objects/test-apartment/index.html").read_text(encoding="utf-8")
            self.assertIn(f'src="{base}assets/object.js"', html)
            self.assertIn('>Планировка</a>', html)
            self.assertTrue((self.output / "property-media/test/test-apartment/shared/portrait-room.svg").exists())
            for slug in ("test-sold", "test-withdrawn"):
                html = (self.output / f"objects/{slug}/index.html").read_text(encoding="utf-8")
                for marker in ('data-gallery', 'object.js', 'OLD-', 'property-media'):
                    self.assertNotIn(marker, html)
            builder.build(base, False, self.output, preliminary=True)
            self.assertFalse((self.output / "assets/object.js").exists())
            self.assertFalse((self.output / "property-media").exists())
            self.assertFalse((self.output / "objects").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

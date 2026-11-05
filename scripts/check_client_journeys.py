"""Regression checks for truthful home states and configured contact actions."""
import unittest
from unittest.mock import patch

import check_properties as shared

builder, data = shared.builder, shared.data


class ClientJourneyTests(unittest.TestCase):
    setUp = shared.PropertyTests.setUp
    tearDown = shared.PropertyTests.tearDown

    def home(self, base="/", *, records=None, test_data=False):
        if records is None:
            builder.build(base, test_data, self.output, test_data=test_data)
        else:
            with patch.object(builder, "load_catalog", return_value=records):
                builder.build(base, False, self.output)
        return (self.output / "index.html").read_text(encoding="utf-8")

    def test_empty_home_prioritizes_contact_and_keeps_navigation(self):
        for base in ("/", "/yulia-ryazan-realty/"):
            html = self.home(base)
            hero = html.split('<section class="hero', 1)[1].split('</section>', 1)[0]
            self.assertIn("Покупаете или продаёте недвижимость?", hero)
            self.assertIn("Рязань и Рязанская область", hero)
            self.assertIn("Позвоните мне, чтобы обсудить ваш запрос.", hero)
            self.assertIn(f'class="button button-primary" href="{base}contacts/"', hero)
            self.assertNotIn(f'href="{base}catalog/"', hero)
            self.assertNotIn('id="properties-title"', html)
            self.assertIn(f'href="{base}catalog/"', html)
            self.assertIn('Обсудить покупку', html)
            self.assertIn('Обсудить продажу', html)
            self.assertEqual(html.count('<article class="service-item">'), 2)

    def test_active_home_is_independent_of_featured_but_selection_is_not(self):
        record = data.validate(shared.fixture(), "public-example.toml", shared.MEDIA, False)
        for base in ("/", "/yulia-ryazan-realty/"):
            for featured in (False, True):
                record["featured"] = featured
                html = self.home(base, records=[record])
                hero = html.split('<section class="hero', 1)[1].split('</section>', 1)[0]
                self.assertIn('>Недвижимость в Рязани и области</h1>', hero)
                self.assertIn('Посмотрите актуальные предложения или расскажите Юлии', hero)
                self.assertIn(f'class="button button-primary" href="{base}catalog/"', hero)
                self.assertNotIn('квартир', hero.lower())
                self.assertEqual('id="properties-title"' in html, featured)
                if featured:
                    self.assertEqual(html.count('data-property-id="test-apartment"'), 1)
                    self.assertIn('Актуальные предложения', html)
                    self.assertLess(html.index('id="hero-title"'), html.index('id="properties-title"'))
                    self.assertLess(html.index('id="properties-title"'), html.index('id="services-title"'))

    def test_inactive_and_test_only_records_do_not_claim_real_offers(self):
        inactive = [record for record in data.load_catalog(True) if record["status"] in ("sold", "withdrawn")]
        html = self.home(records=inactive)
        self.assertIn('Покупаете или продаёте недвижимость?', html)
        self.assertNotIn('id="properties-title"', html)
        html = self.home(test_data=True)
        self.assertIn('В каталоге сейчас тестовые примеры', html)
        self.assertIn('data-demo="fixture"', html)
        self.assertNotIn('Посмотрите актуальные предложения или расскажите Юлии', html)

    def test_about_process_faq_and_phone_only_contact(self):
        self.home()
        about = (self.output / "about/index.html").read_text(encoding="utf-8")
        self.assertIn('Как проходит работа', about)
        self.assertIn('Частые вопросы', about)
        self.assertEqual(about.count('<details>'), 5)
        for material in ('Коммерческая недвижимость', 'Недвижимость для инвестиций', 'до вручения ключей', 'на другом сайте', 'затем купить другую', 'Рязанской области'):
            self.assertIn(material, about)
        self.assertIn('С какой недвижимостью я работаю', about)
        self.assertLess(about.index('id="directions-title"'), about.index('id="process-title"'))
        self.assertIn('Сотрудничаю с агентством «Новоселье». При необходимости к вопросам сделки подключаются специалисты агентства.', about)
        self.assertIn('Обсудить мою ситуацию', about)
        for topic in ('Начинаю с вашей ситуации.', 'Уже нашли объект?', 'Нужно сначала продать, а потом купить?', 'Работаю с поддержкой команды.'):
            self.assertIn(f'<h3>{topic}</h3>', about)
        home = (self.output / 'index.html').read_text(encoding='utf-8')
        for material in ('от первого обращения до вручения ключей', 'Оценка объекта и сбор документов', 'Показы и переговоры', 'Работа с договором'):
            self.assertIn(material, home)
        self.assertIn('Новоселье', about)
        self.assertIn('Советскому району', about)
        for marker in ('бесплатн', 'гаранти', 'юридическ', 'согласовать текст'):
            self.assertNotIn(marker, about.lower())
        contacts = (self.output / "contacts/index.html").read_text(encoding="utf-8")
        self.assertIn('contact-grid-single', contacts)
        self.assertIn('tel:+79657127848', contacts)
        self.assertEqual(contacts.count('class="contact-tile phone-tile"'), 1)
        self.assertIn('class="contact-identity"', contacts)
        self.assertIn('class="contact-call"', contacts)
        for marker in ('Переписка', 'Telegram', 'WhatsApp', 'MAX', 'уточнить при звонке'):
            self.assertNotIn(marker, contacts)

    def test_optional_max_validation_and_safe_rendering(self):
        import tomllib
        raw = tomllib.loads((builder.ROOT / 'src/data/contacts.toml').read_text(encoding='utf-8'))
        original_loads = builder.tomllib.loads
        for value in ('javascript:alert(1)', 'https://example.test/contact', 'https://max.ru/', 'http://max.ru/u/test', 'https://user:pass@max.ru/u/test', 'https://max.ru:444/u/test', 123):
            changed = dict(raw, max_url=value)
            with patch.object(builder.tomllib, 'loads', return_value=changed):
                with self.assertRaises(ValueError):
                    builder.contacts()
        # This URL exists only in a temporary test build; it is never opened.
        synthetic = 'https://max.ru/u/synthetic-test?one=1&two=2'
        with patch.object(builder.tomllib, 'loads', return_value=dict(raw, max_url=synthetic)):
            contact = builder.contacts()
        self.assertEqual(contact['max_url'], synthetic)
        for base in ('/', '/yulia-ryazan-realty/'):
            with patch.object(builder, 'contacts', return_value=contact):
                builder.build(base, True, self.output, test_data=True)
            for relative in ('index.html', 'contacts/index.html', 'objects/test-apartment/index.html'):
                html = (self.output / relative).read_text(encoding='utf-8')
                self.assertIn('https://max.ru/u/synthetic-test?one=1&amp;two=2', html)
                self.assertIn('Написать в MAX', html)
                self.assertIn('tel:+79657127848', html)
        self.assertIs(builder.tomllib.loads, original_loads)


if __name__ == '__main__':
    unittest.main(verbosity=2)

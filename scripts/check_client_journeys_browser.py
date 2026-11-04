"""Chrome checks of client paths, conditional home content and static FAQ."""
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
import time
from unittest.mock import patch

from browser_support import open_browser, ROOT, SHOTS
from check_properties import builder


def check(base, output, browser):
    label = 'root' if base == '/' else 'subfolder'
    with builder.preview_server(base, output, port=0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        prefix = origin + base
        def js(expression):
            return browser.evaluate(expression)
        def key(value):
            codes = {'Tab':9, 'Enter':13}
            for kind in ('keyDown','keyUp'):
                params = dict(type=kind, key=value, code=value, windowsVirtualKeyCode=codes[value])
                if value == 'Enter' and kind == 'keyDown':
                    params.update(text='\r', unmodifiedText='\r')
                browser.call('Input.dispatchKeyEvent', **params)
        def wait(expression):
            for _ in range(60):
                if js(expression): return
                time.sleep(.03)
            raise AssertionError(expression)
        try:
            browser.call('Network.enable')
            browser.call('Network.setCacheDisabled', cacheDisabled=True)
            for mode, filled, featured in (('empty', False, False), ('filled', True, True), ('unfeatured', True, False)):
                records = builder.load_catalog(test_data=filled)
                if filled and not featured:
                    for record in records:
                        record['featured'] = False
                with patch.object(builder, 'load_catalog', return_value=records):
                    builder.build(base, filled, output, test_data=filled, preliminary=not filled)
                routes = [('home',''),('catalog','catalog/'),('about','about/'),('contacts','contacts/')]
                if filled: routes.append(('object','objects/test-apartment/'))
                for width in (1280,390,360):
                    browser.call('Emulation.setDeviceMetricsOverride', width=width, height=900 if width==1280 else 844, deviceScaleFactor=1, mobile=width<600)
                    for name, route in routes:
                        browser.navigate(prefix+route)
                        metric = js('''({
                            width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
                            robots:document.querySelector('meta[name=robots]')?.content,
                            broken:[...document.images].some(i=>!i.complete||!i.naturalWidth),
                            phone:[...document.querySelectorAll('a[href^="tel:"]')].map(a=>a.getAttribute('href')),
                            review:!!document.querySelector('[data-review]'),
                            photo:document.querySelector('.portrait-photo img')?.naturalWidth,
                            max:!!document.querySelector('a[href^="https://max.ru/"]')
                        })''')
                        assert metric['width']==width and metric['scrollWidth']<=width, (mode,name,metric)
                        assert metric['robots']=='noindex, nofollow' and not metric['broken'] and not metric['review'], metric
                        assert metric['phone'] and all(p=='tel:+79657127848' for p in metric['phone']),metric
                        assert not metric['max'],metric
                        if name in ('home','about'): assert metric['photo']==900,metric
                        if name=='home':
                            assert js("document.querySelectorAll('.client-grid article').length===2")
                            if filled:
                                assert js("document.querySelector('.hero .button-primary').getAttribute('href').endsWith('/catalog/')")
                                assert js("!!document.querySelector('#properties-title')")==featured
                                assert js("document.querySelector('.hero h1').textContent==='Недвижимость в Рязани и области'")
                                assert js("document.querySelector('.hero-description').textContent.includes('тестовые примеры')")
                                if featured: assert js("document.querySelector('#properties-title').textContent==='Актуальные предложения'")
                            else:
                                assert js("document.querySelector('.hero h1').textContent==='Покупаете или продаёте недвижимость?'")
                                assert js("document.querySelector('.hero .button-primary').getAttribute('href').endsWith('/contacts/') && !document.querySelector('#properties-title')")
                        if name=='about':
                            assert js("document.querySelectorAll('.process-grid li').length===3 && document.querySelectorAll('.faq-section details').length===5")
                        if name=='contacts':
                            assert js("document.querySelectorAll('.contact-grid .contact-tile').length===1 && !document.body.innerText.includes('WhatsApp') && !document.body.innerText.includes('Telegram')")
                            assert js("document.querySelector('.phone-tile').getBoundingClientRect().width >= document.querySelector('.contact-grid').getBoundingClientRect().width-2")
                            if width==1280:
                                assert js("document.querySelector('.contact-call').getBoundingClientRect().left > document.querySelector('.contact-identity').getBoundingClientRect().right")
                            else:
                                assert js("document.querySelector('.contact-call').getBoundingClientRect().top > document.querySelector('.contact-identity').getBoundingClientRect().bottom")
                        if width!=360:
                            browser.screenshot(f'clarity-{label}-{mode}-{name}-{width}.png')
                # Actual keyboard navigation to the main action; never activate a telephone link.
                browser.navigate(prefix)
                for _ in range(40):
                    key('Tab')
                    state=js("({hero:document.activeElement.matches('.hero .button-primary'),outline:getComputedStyle(document.activeElement).outlineWidth})")
                    if state['hero']:
                        assert float(state['outline'].removesuffix('px'))>=2,state
                        key('Enter')
                        expected=base+('catalog/' if filled else 'contacts/')
                        wait(f'location.pathname==={expected!r} && document.readyState==="complete"')
                        break
                else: raise AssertionError('Primary action is not keyboard reachable')
                # Buyer/seller link targets are explicit and remain local.
                browser.navigate(prefix)
                links=js("[...document.querySelectorAll('.client-actions a')].map(a=>a.getAttribute('href'))")
                assert links==[base+'catalog/',base+'contacts/',base+'contacts/'],links
                browser.navigate(prefix+'about/')
                js("document.querySelector('.faq-section summary').focus()")
                assert js("parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2")
                key('Enter')
                wait("document.querySelector('.faq-section details').open")
                browser.screenshot(f'clarity-{label}-{mode}-faq-open.png')
                if not filled:
                    browser.navigate(prefix+'catalog/')
                    js("document.querySelector('.empty-state .text-link').click()")
                    wait(f'location.pathname==={base+"contacts/"!r}')
                # FAQ, contact paths and core content also work without JS.
                browser.call('Emulation.setScriptExecutionDisabled',value=True)
                try:
                    browser.navigate(prefix+'about/')
                    js("document.querySelector('.faq-section summary').focus()")
                    key('Enter')
                    wait("document.querySelector('.faq-section details').open")
                    browser.navigate(prefix)
                    assert js("!!document.querySelector('.hero .button-primary') && document.querySelectorAll('.client-grid article').length===2")
                    browser.navigate(prefix+'catalog/')
                    if filled:
                        assert js("document.querySelector('#catalog-filters').hidden && document.querySelectorAll('[data-property-id]').length===6")
                    else: assert js("!!document.querySelector('.empty-state')")
                finally:
                    browser.call('Emulation.setScriptExecutionDisabled',value=False)
                print('PASS client paths:',base,mode,'360/390/1280; hero, cards, contacts, FAQ, keyboard and no-JS',flush=True)
            # Rendering only: never navigate to or activate the synthetic MAX URL.
            contact = dict(builder.contacts(), max_url='https://max.ru/u/synthetic-test?one=1&two=2')
            with patch.object(builder, 'contacts', return_value=contact):
                builder.build(base, True, output, test_data=True)
            for width in (1280,390,360):
                browser.call('Emulation.setDeviceMetricsOverride', width=width, height=900 if width==1280 else 844, deviceScaleFactor=1, mobile=width<600)
                for route in ('','contacts/','objects/test-apartment/'):
                    browser.navigate(prefix+route)
                    assert js("document.querySelector('a[href=\"https://max.ru/u/synthetic-test?one=1&two=2\"]')!==null && document.documentElement.scrollWidth<=innerWidth")
                    assert js("[...document.querySelectorAll('a[href^=\"tel:\"]')].every(a=>a.getAttribute('href')==='tel:+79657127848')")
                browser.navigate(prefix+'contacts/')
                assert js("document.querySelectorAll('.contact-grid .contact-tile').length===2")
                if width!=360: browser.screenshot(f'clarity-{label}-synthetic-max-contacts-{width}.png')
            print('PASS optional MAX rendering:',base,'home, contacts, object; 360/390/1280; no messenger activation',flush=True)
        finally:
            server.shutdown();thread.join()


if __name__=='__main__':
    with TemporaryDirectory(prefix='.check-clients-browser-',dir=ROOT) as directory, open_browser() as browser:
        output=Path(directory)/'dist'
        for base in ('/','/yulia-ryazan-realty/'):
            check(base,output,browser)
        shutil.rmtree(directory,onexc=builder.retry_windows_lock)
    print('Client paths browser checks passed; screenshots:',SHOTS)

"""Real Chrome checks for the object gallery, modal focus and copy fallback."""
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
import time

from browser_support import open_browser, ROOT, SHOTS
from check_properties import builder


def check(base, output, browser):
    builder.build(base, True, output, test_data=True)
    with builder.preview_server(base, output, port=0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        prefix = origin + base
        label = "root" if base == "/" else "subfolder"
        def js(expression):
            return browser.evaluate(expression)
        def wait(expression):
            for _ in range(100):
                if js(expression):
                    return
                time.sleep(.03)
            raise AssertionError(expression)
        def click(selector):
            js(f"document.querySelector({selector!r}).click()")
        def key(value, shift=False):
            codes = {"Enter":13, "Escape":27, "Tab":9, "ArrowLeft":37, "ArrowRight":39}
            for kind in ("keyDown", "keyUp"):
                browser.call("Input.dispatchKeyEvent", type=kind, key=value, code=value, windowsVirtualKeyCode=codes[value], modifiers=8 if shift else 0)
        def main_is(file):
            wait(f"document.querySelector('[data-gallery-main]').src.endsWith('/{file}') && document.querySelector('[data-gallery-main]').naturalWidth>0")
        try:
            browser.call("Network.enable")
            browser.call("Network.setCacheDisabled", cacheDisabled=True)
            browser.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
            url = prefix + "objects/test-apartment/"
            browser.navigate(url)
            main_is("room-b.svg")
            assert js("document.querySelector('[data-gallery-count]').textContent==='Фото 2 из 3'")
            assert js("[...document.querySelectorAll('[data-gallery-item]')].map(a=>a.href.split('/').pop()).join(',')==='room-a.svg,room-b.svg,portrait-room.svg'")
            click('[data-gallery-controls] [data-gallery-prev]'); main_is('room-a.svg')
            click('[data-gallery-controls] [data-gallery-next]'); main_is('room-b.svg')
            js("document.querySelectorAll('[data-gallery-item]')[2].click()")
            main_is('portrait-room.svg')
            js("document.querySelector('[data-gallery-open]').focus()")
            key('Enter')
            wait("document.querySelector('dialog').open")
            assert js("document.querySelector('[data-dialog-count]').textContent==='Фото 3 из 3'")
            assert js("getComputedStyle(document.querySelector('[data-dialog-image]')).objectFit==='contain'")
            js("document.querySelector('[data-dialog-original]').focus()")
            key('Tab')
            assert js("document.activeElement.matches('[data-gallery-close]')")
            key('Tab', shift=True)
            assert js("document.activeElement.matches('[data-dialog-original]')")
            key('ArrowRight')
            assert js("document.querySelector('[data-dialog-count]').textContent==='Фото 1 из 3'")
            assert js("document.activeElement.matches('[data-dialog-original]')")
            key('Escape')
            wait("!document.querySelector('dialog').open")
            assert js("document.activeElement.matches('[data-gallery-open]')")
            click('[data-gallery-open]'); wait("document.querySelector('dialog').open")
            click('[data-gallery-close]')
            wait("!document.querySelector('dialog').open")
            assert js("document.activeElement.matches('[data-gallery-open]')")
            # Test copy success deterministically without touching the system clipboard.
            js("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedObjectUrl=value;}}})")
            click('[data-copy-link]')
            wait("!!window.copiedObjectUrl")
            assert js("window.copiedObjectUrl") == url
            assert js("document.querySelector('[data-copy-status]').textContent==='Ссылка скопирована.'")
            js("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied')}}})")
            click('[data-copy-link]')
            wait("!document.querySelector('[data-permalink]').hidden")
            assert js("document.activeElement.matches('[data-permalink]')")
            assert js("document.querySelector('[data-permalink]').value") == url
            assert js("document.querySelector('[data-permalink]').selectionEnd-document.querySelector('[data-permalink]').selectionStart") == len(url)
            js("Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined})")
            click('[data-copy-link]')
            wait("document.querySelector('[data-copy-status]').textContent.includes('вручную')")
            # Direct refresh produces the same route and selected cover image.
            browser.call('Page.reload', ignoreCache=True)
            wait("document.readyState==='complete' && !!document.querySelector('[data-gallery-main]')")
            main_is('room-b.svg')
            assert js('location.pathname') == base + 'objects/test-apartment/'
            # Single and absent photos keep the right amount of controls.
            browser.navigate(prefix + 'objects/test-house/')
            assert js("document.querySelectorAll('[data-gallery-item]').length===1 && !document.querySelector('[data-gallery-next]')")
            assert js("document.querySelector('[data-gallery-controls]').hidden")
            click('[data-gallery-open]')
            wait("document.querySelector('dialog').open")
            key('Escape')
            browser.navigate(prefix + 'objects/test-land/')
            assert js("!!document.querySelector('.object-no-photo') && !document.querySelector('dialog') && !document.querySelector('[data-gallery-controls]')")
            assert js("document.querySelector('.property-summary').textContent.includes('15 сот.') && !document.querySelector('.property-summary').textContent.includes('га')")
            for width in (1280,390,360):
                browser.call('Emulation.setDeviceMetricsOverride',width=width,height=900 if width==1280 else 844,deviceScaleFactor=1,mobile=width<600)
                for slug in ('test-apartment','test-house','test-land'):
                    browser.navigate(prefix+'objects/'+slug+'/')
                    assert js("document.documentElement.scrollWidth<=innerWidth")
                    assert js("document.querySelector('meta[name=robots]').content==='noindex, nofollow'")
                    assert js("[...document.querySelectorAll('a[href^=\"tel:\"]')].every(a=>a.getAttribute('href')==='tel:+79657127848')")
                    assert js("!document.querySelector('[data-review]')")
                    browser.screenshot(f'gallery-{label}-{slug}-{width}.png')
                    if slug=='test-apartment':
                        js("document.querySelectorAll('[data-gallery-item]')[2].click()")
                        click('[data-gallery-open]'); wait("document.querySelector('dialog').open")
                        wait("document.querySelector('[data-dialog-image]').naturalHeight>0")
                        assert js("document.querySelector('dialog').getBoundingClientRect().right<=innerWidth && document.querySelector('dialog').getBoundingClientRect().left>=0")
                        assert js("document.querySelector('[data-dialog-image]').naturalHeight>document.querySelector('[data-dialog-image]').naturalWidth")
                        browser.screenshot(f'gallery-{label}-enlarged-{width}.png',full=False)
                        key('Escape')
            # Block an image URL as a real network failure, then recover by switching.
            browser.call('Network.setBlockedURLs',urls=['*room-b.svg'])
            browser.navigate(url)
            wait("!document.querySelector('.gallery-feature [data-image-error]').hidden")
            click('[data-gallery-open]'); wait("document.querySelector('dialog').open")
            wait("!document.querySelector('dialog [data-image-error]').hidden")
            assert js("!!document.querySelector('[data-dialog-original]').href")
            click('dialog [data-gallery-next]')
            wait("document.querySelector('dialog [data-image-error]').hidden && document.querySelector('[data-dialog-image]').naturalHeight>0")
            key('Escape')
            browser.call('Network.setBlockedURLs',urls=[])
            browser.call('Network.setBlockedURLs',urls=['*room-a.svg'])
            browser.navigate(prefix+'objects/test-house/')
            wait("!document.querySelector('.gallery-feature [data-image-error]').hidden")
            assert js("!document.querySelector('[data-gallery-next]') && !document.querySelector('.gallery-feature [data-image-error]').textContent.includes('другую')")
            assert js("document.querySelector('.gallery-feature [data-image-original]').href.endsWith('/shared/room-a.svg')")
            browser.screenshot(f'gallery-{label}-single-image-error.png')
            browser.call('Network.setBlockedURLs',urls=[])
            # Without JS the ordered photo anchors and cover remain real links.
            browser.call('Emulation.setScriptExecutionDisabled',value=True)
            try:
                browser.navigate(url)
                assert js("document.querySelectorAll('[data-gallery-item]').length===3 && document.querySelector('[data-gallery-controls]').hidden && document.querySelector('[data-copy-link]').hidden")
                assert js("!document.querySelector('dialog').open")
                click('[data-gallery-open]')
                wait("location.pathname.endsWith('/shared/room-b.svg')")
            finally:
                browser.call('Emulation.setScriptExecutionDisabled',value=False)
            for slug in ('test-sold','test-withdrawn'):
                browser.navigate(prefix+'objects/'+slug+'/')
                assert js("!document.querySelector('[data-gallery]') && !document.body.innerHTML.includes('OLD-') && !document.querySelector('script[src*=\"object.js\"]')")
            print('PASS gallery:',base,'cover/order, switch/modal, Escape/focus/trap, copy success/fallback, single/none/error, no-JS, 360/390/1280',flush=True)
        finally:
            browser.call('Network.setBlockedURLs',urls=[])
            server.shutdown();thread.join()


if __name__=='__main__':
    with TemporaryDirectory(prefix='.check-gallery-browser-',dir=ROOT) as directory, open_browser() as browser:
        output=Path(directory)/'dist'
        for base in ('/','/yulia-ryazan-realty/'):
            check(base,output,browser)
        shutil.rmtree(directory,onexc=builder.retry_windows_lock)
    print('Gallery browser checks passed; screenshots:',SHOTS)

"""Optional real-Chrome regression checks for the static catalog, no dependencies."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
import time
from unittest.mock import patch

from browser_support import open_browser, ROOT, SHOTS
from check_properties import builder, data


ALL = ["test-apartment", "test-apartment-studio", "test-house", "test-house-no-price", "test-land", "test-land-priced"]


def check(base, output, browser):
    builder.build(base, True, output, test_data=True)
    with builder.preview_server(base, output, port=0) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        url = origin + base + "catalog/"
        label = "root" if base == "/" else "subfolder"
        try:
            browser.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
            browser.navigate(url)
            def evaluate(expression):
                return browser.evaluate(expression)
            def visible():
                return evaluate("[...document.querySelectorAll('.catalog-grid [data-property-id]')].filter(c=>!c.hidden && c.getClientRects().length).map(c=>c.dataset.propertyId)")
            def expect(ids):
                assert visible() == ids, (ids, visible())
            def set_fields(**values):
                for name, value in values.items():
                    evaluate(f"(() => {{const f=document.querySelector('#catalog-filters').elements.namedItem({json.dumps(name)});f.value={json.dumps(str(value))};f.dispatchEvent(new Event(f.tagName==='SELECT'?'change':'input',{{bubbles:true}}));}})()")
            def reset():
                evaluate("document.querySelector('#catalog-filters').reset()")
                evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                expect(ALL)
            expect(ALL)
            assert evaluate("!document.querySelector('#catalog-filters').hidden")
            set_fields(type="apartment"); expect(ALL[:2])
            set_fields(market="primary"); expect([ALL[0]])
            reset(); set_fields(location="ДРУГОЙ тестовый"); expect([ALL[1], ALL[3]])
            reset(); set_fields(location="часть адреса"); expect([ALL[0]])
            reset(); set_fields(rooms="0"); expect([ALL[1]])
            reset(); set_fields(price_min="4200000", price_max="4200000"); expect(ALL[:2])
            reset(); set_fields(area_min="80", area_max="120"); expect(ALL[2:4])
            reset(); set_fields(plot_min="8", plot_max="15"); expect([ALL[2], ALL[4], ALL[5]])
            reset(); set_fields(type="house", market="secondary", rooms="4", price_min="6000000", area_min="100", plot_min="8"); expect([ALL[2]])
            set_fields(type="land")
            assert evaluate("['market','rooms','area_min','area_max'].every(n=>{const f=document.querySelector('#catalog-filters').elements.namedItem(n);return f.disabled && f.value==='';})")
            assert evaluate("document.querySelector('#catalog-type-note').textContent.length > 0")
            set_fields(price_min=""); expect(ALL[4:])
            assert evaluate("document.querySelector('#catalog-filters [name=type] option[value=apartment]').disabled===false")
            reset(); set_fields(type="apartment", market="secondary")
            set_fields(type="house")
            assert evaluate("document.querySelector('#catalog-filters [name=market]').value==='secondary'")
            set_fields(type="land")
            set_fields(type="house")
            assert evaluate("document.querySelector('#catalog-filters [name=market]').value===''")
            reset(); set_fields(price_min="90000000")
            expect([])
            assert evaluate("!document.querySelector('#catalog-no-results').hidden && document.querySelector('#catalog-error').hidden")
            browser.screenshot(f"catalog-{label}-no-results-desktop.png")
            evaluate("document.querySelector('[data-catalog-reset]').click()")
            evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
            expect(ALL)
            assert evaluate("document.activeElement.name==='type'")
            set_fields(price_min="20", price_max="10")
            expect([])
            assert evaluate("!document.querySelector('#catalog-error').hidden && document.querySelector('#catalog-no-results').hidden && document.querySelector('[name=price_min]').getAttribute('aria-invalid')==='true'")
            reset(); set_fields(price_min="-1")
            assert evaluate("!document.querySelector('#catalog-error').hidden")
            reset(); set_fields(area_min="2", area_max="1")
            assert evaluate("!document.querySelector('#catalog-error').hidden")
            reset(); set_fields(plot_min="2", plot_max="1")
            assert evaluate("!document.querySelector('#catalog-error').hidden")
            reset(); set_fields(sort="price_asc"); expect([ALL[5],ALL[0],ALL[1],ALL[2],ALL[3],ALL[4]])
            set_fields(sort="price_desc"); expect([ALL[2],ALL[0],ALL[1],ALL[5],ALL[3],ALL[4]])
            set_fields(sort="newest"); expect([ALL[0],ALL[1],ALL[3],ALL[2],ALL[4],ALL[5]])
            set_fields(sort="catalog"); expect(ALL)
            # Reapply a filter after reordering: ties must still follow initial catalog order.
            set_fields(sort="price_desc"); set_fields(location="тестовый"); expect([ALL[2],ALL[0],ALL[1],ALL[5],ALL[3],ALL[4]])
            reset()
            # Native Tab/Enter check: filter focus is visible and the card link opens its real URL.
            evaluate("document.activeElement.blur();document.body.focus()")
            browser.navigate(url)
            focused_filter = False
            focused_card = False
            for _ in range(60):
                browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
                browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
                state = evaluate("({filter:!!document.activeElement.closest('#catalog-filters'),card:document.activeElement.classList.contains('property-link'),outline:getComputedStyle(document.activeElement).outlineWidth,href:document.activeElement.getAttribute('href')})")
                if state["filter"]:
                    assert float(state["outline"].removesuffix("px")) >= 2, state
                    focused_filter = True
                if state["card"]:
                    assert float(state["outline"].removesuffix("px")) >= 2, state
                    browser.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
                    browser.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
                    time.sleep(.15)
                    assert evaluate("location.pathname") == state["href"]
                    focused_card = True
                    break
            assert focused_filter and focused_card
            browser.navigate(url)
            # Existing direct object routes, all resources, no broken images.
            for slug in ALL + ["test-sold", "test-withdrawn"]:
                browser.navigate(origin + base + "objects/" + slug + "/")
                assert evaluate("!!document.querySelector('h1') && [...document.images].every(i=>i.complete && i.naturalWidth)")
            for width in (1280, 390, 360):
                browser.call("Emulation.setDeviceMetricsOverride", width=width, height=900 if width==1280 else 844, deviceScaleFactor=1, mobile=width<600)
                browser.navigate(url)
                expect(ALL)
                assert evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.images].every(i=>i.complete && i.naturalWidth)")
                columns = evaluate("getComputedStyle(document.querySelector('.catalog-grid')).gridTemplateColumns.split(' ').length")
                assert columns == (3 if width==1280 else 1), (width, columns)
                browser.screenshot(f"catalog-{label}-populated-{width}.png")
                set_fields(price_min="90000000")
                browser.screenshot(f"catalog-{label}-no-results-{width}.png")
                assert evaluate("!document.querySelector('#catalog-no-results').hidden && document.documentElement.scrollWidth<=innerWidth")
            # The static catalog remains complete with JS execution disabled.
            browser.call("Emulation.setScriptExecutionDisabled", value=True)
            try:
                browser.navigate(url)
                expect(ALL)
                assert evaluate("document.querySelector('#catalog-filters').hidden && [...document.querySelectorAll('.property-link')].length===6")
                browser.screenshot(f"catalog-{label}-no-javascript.png")
            finally:
                browser.call("Emulation.setScriptExecutionDisabled", value=False)
            # Temporary records exercise fractional m² conversion, missing plot data,
            # inclusive boundaries and type switching without editing fixture files.
            records = data.load_catalog(True)
            for record in records:
                if record["id"] == "test-house-no-price":
                    record.update(plot_area=805.3, plot_unit="m2")
                if record["id"] == "test-house":
                    record.pop("plot_area")
                    record.pop("plot_unit")
            with patch.object(builder, "load_catalog", return_value=records):
                builder.build(base, True, output, test_data=True)
            browser.call("Network.enable")
            browser.call("Network.setCacheDisabled", cacheDisabled=True)
            browser.navigate(url)
            set_fields(type="house", plot_min="8.053", plot_max="8.053"); expect([ALL[3]])
            assert evaluate("document.querySelector('[data-property-id=test-house-no-price] .property-facts').textContent.includes('8,053')")
            set_fields(plot_max="8.0529")
            assert evaluate("!document.querySelector('#catalog-error').hidden")
            set_fields(plot_min="0", plot_max="8.0529"); expect([])
            set_fields(plot_min="8.0531", plot_max="20"); expect([])
            set_fields(plot_min="-0.1")
            assert evaluate("!document.querySelector('#catalog-error').hidden")
            set_fields(plot_min="8.053", plot_max="8.053"); expect([ALL[3]])
            set_fields(type="apartment"); expect(ALL[:2])
            assert evaluate("['plot_min','plot_max'].every(n=>{const f=document.querySelector('#catalog-filters').elements.namedItem(n);return f.disabled && f.value==='';})")
            reset()
            builder.build(base, False, output, preliminary=True)
            for width in (1280, 390, 360):
                browser.call("Emulation.setDeviceMetricsOverride", width=width, height=900 if width==1280 else 844, deviceScaleFactor=1, mobile=width<600)
                browser.navigate(url)
                assert evaluate("!document.querySelector('#catalog-filters') && !document.querySelector('#catalog-no-results') && !!document.querySelector('.empty-state') && document.documentElement.scrollWidth<=innerWidth")
                browser.screenshot(f"catalog-{label}-empty-{width}.png")
                evaluate("document.querySelector('.empty-state .text-link').click()")
                time.sleep(.1)
                assert evaluate("location.pathname") == base + "contacts/"
            for route in ("", "about/", "contacts/"):
                browser.navigate(origin + base + route)
                assert evaluate("document.querySelector('meta[name=robots]').content==='noindex, nofollow' && !document.querySelector('[data-review]') && !document.querySelector('.preview-banner')")
                assert evaluate("[...document.querySelectorAll('a[href^=\"tel:\"]')].every(a=>a.getAttribute('href')==='tel:+79657127848')")
                if route != "contacts/":
                    assert evaluate("document.querySelector('.portrait-photo img').naturalWidth===900")
            print("PASS:", base, "filters, combinations, clearing, errors, stable sorts, empty states, no-JS, keyboard, resources, 360/390/1280", flush=True)
        finally:
            server.shutdown()
            worker.join()


if __name__ == "__main__":
    with TemporaryDirectory(prefix=".check-catalog-browser-", dir=ROOT) as directory, open_browser() as browser:
        output = Path(directory) / "dist"
        for base in ("/", "/yulia-ryazan-realty/"):
            check(base, output, browser)
        shutil.rmtree(directory, onexc=builder.retry_windows_lock)
    print("Browser catalog checks passed; screenshots:", SHOTS)

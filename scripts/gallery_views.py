"""Accessible static photo links with optional browser enhancement."""
from html import escape


def gallery(record, base, media_address):
    photos = record["photos"]
    if not photos:
        return '<div class="object-no-photo">Фотографий пока нет</div>'
    index = record["cover"]
    main = photos[index]
    source = media_address(record, main["path"], base)
    caption = escape(main["caption"] or main["alt"])
    links = "".join(
        f'<li><a href="{media_address(record, photo["path"], base)}" data-gallery-item data-caption="{escape(photo["caption"] or photo["alt"], quote=True)}"'
        + (' aria-current="true"' if position == index else '')
        + f'><img src="{media_address(record, photo["path"], base)}" alt="{escape(photo["alt"], quote=True)}" decoding="async"><span>Фото {position + 1}</span></a></li>'
        for position, photo in enumerate(photos)
    )
    controls = '<button type="button" data-gallery-prev aria-label="Предыдущая фотография">← Назад</button><button type="button" data-gallery-next aria-label="Следующая фотография">Далее →</button>' if len(photos) > 1 else ""
    recovery = 'Можно выбрать другую фотографию или открыть файл.' if len(photos) > 1 else 'Попробуйте открыть файл фотографии.'
    error = f'<p class="gallery-error" data-image-error hidden role="status">Не удалось загрузить фотографию. {recovery} <a data-image-original href="{source}">Открыть файл фотографии</a></p>'
    return f'''<section class="object-gallery" data-gallery data-cover="{index}" aria-label="Фотографии объекта">
      <figure class="gallery-feature">
        <a href="{source}" data-gallery-open aria-label="Рассмотреть фотографию крупнее"><img src="{source}" alt="{escape(main["alt"], quote=True)}" data-gallery-main decoding="async"></a>
        {error}
        <figcaption role="status" aria-live="polite" aria-atomic="true"><span data-gallery-count>Фото {index + 1} из {len(photos)}</span><span data-gallery-caption>{caption}</span></figcaption>
      </figure>
      <div class="gallery-controls" data-gallery-controls hidden>{controls}</div>
      <p class="gallery-help">Откройте фотографию, чтобы рассмотреть её крупнее.</p>
      <ol class="gallery-thumbs">{links}</ol>
      <dialog class="gallery-dialog" aria-labelledby="gallery-dialog-title">
        <div class="gallery-dialog-head"><h2 id="gallery-dialog-title">Фотографии объекта</h2><button type="button" data-gallery-close autofocus>Закрыть ×</button></div>
        <figure><img data-dialog-image src="{source}" alt="{escape(main["alt"], quote=True)}">{error}<figcaption role="status" aria-live="polite" aria-atomic="true"><span data-dialog-count></span><span data-dialog-caption></span></figcaption></figure>
        <div class="gallery-dialog-actions">{controls}<a data-dialog-original href="{source}">Открыть файл фотографии</a></div>
      </dialog>
    </section>'''

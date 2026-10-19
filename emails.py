# Транзакційні листи Mamulya.lviv (Resend). Памятка адаптується під категорію товару.
MEMO_SUBJECT = "Ваше замовлення вже в дорозі! \U0001F69A Важлива памятка"
# бренд-кольори з лого: кораловий #F07068 (для тексту/кнопок трохи темніший #E05A50), блиш #FCEBEA

# ---- класифікація замовлення за назвами товарів (пріоритет згори вниз) ----
_KW = [
    ("nonreturn", ("бюстгал", "трус", "білизн", "купальник", "колгот", "панчох", "косметик", "крем для", "гігієн")),
    ("sling",     ("слінг", "ерго", "хіпсіт", "хипсит", "май-слінг", "намотк", "слингонакид", "слінгонакид", "перенос")),
    ("toy",       ("lipoland", "ліполенд", "ліпуч", "ліпол", "домана", "пекс")),
    ("furniture", ("ліжеч", "ліжко", "комод", "пеленат", "стільч", "стілец", "крісл", "матрац", "вежа помічник",
                   "меблі", "модульн", "коляск", "автокрісл", "бустер", "шафа")),
]
def memo_category(items):
    t = " ".join(str(i) for i in (items or [])).lower()
    for cat, kws in _KW:
        if any(k in t for k in kws):
            return cat
    return "clothing"

import os as _os
# куди Яна заллє гіфки (той самий /uploads/images, де лого); можна перевизначити env MAIL_ASSET_BASE
ASSET = _os.environ.get("MAIL_ASSET_BASE", "https://mamulya.lviv.ua/uploads/images").rstrip("/")
_TRACK = _os.environ.get("TRACK_BASE", "https://mamulya-bot.onrender.com").rstrip("/")
def _px(okey):  # піксель відкриття листа (1x1)
    return f'<img src="{_TRACK}/px?k={okey}" width="1" height="1" alt="" style="display:block;max-height:1px;opacity:0">' if okey else ""
def _div(name, w=300):
    return (f'<tr><td style="padding:10px 22px 0;text-align:center;">'
            f'<img src="{ASSET}/{name}" width="{w}" alt="" style="width:{w}px;max-width:82%;height:auto;"/></td></tr>')

# ---- верх листа: лого, герой, коли отримаєте, способи доставки (спільне) ----
_TOP = r"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting"><title>Памятка Mamulya.lviv</title></head>
<body translate="no" class="notranslate" style="margin:0;padding:0;background:#f4ece9;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#4a3f44;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">Збережіть цей лист: як прийняти посилку, оглянути та оформити повернення чи обмін 💗</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4ece9;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 2px 14px rgba(140,90,110,.10);">
  <tr><td style="background:#E05A50;padding:9px 16px;text-align:center;">
    <span style="color:#ffffff;font-size:12px;font-weight:700;letter-spacing:.6px;">📌 ВАЖЛИВО · ЗБЕРЕЖІТЬ ЦЕЙ ЛИСТ</span>
  </td></tr>
  <tr><td style="background:#ffffff;padding:22px 22px 10px;text-align:center;">
    <img src="https://mamulya.lviv.ua/uploads/images/logo-mamulya-lviv.png" width="210" alt="Mamulya.lviv" style="width:210px;max-width:66%;height:auto;" />
  </td></tr>
  <tr><td style="padding:6px 22px 8px;text-align:center;">
    <img src="REPLACED_HERO" width="300" alt="" style="width:300px;max-width:82%;height:auto;margin-bottom:2px;"/>
  </td></tr>
  <tr><td style="padding:2px 22px 10px;text-align:center;">
    <h1 style="margin:0 0 8px;font-size:23px;color:#3a2f34;font-weight:700;">Ваше замовлення вже в дорозі!</h1>
    <p style="margin:0;font-size:15px;line-height:1.6;color:#6e5f65;">Нова Пошта везе його до вас. Тримайте коротку памятку — як прийняти, оглянути та (за потреби) повернути.<br>Збережіть лист, щоб був під рукою.</p>
  </td></tr>
  <!--ORDER_ITEMS-->
  <tr><td style="padding:22px 22px 4px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FCEBEA;border-radius:14px;"><tr><td style="padding:18px 20px;">
      <div style="font-size:17px;font-weight:700;color:#E05A50;">📦 Коли чекати</div>
      <ul style="margin:10px 0 0;padding-left:20px;font-size:14.5px;line-height:1.7;color:#4a3f44;">
        <li>Нова Пошта доставляє зазвичай за <b>1–3 дні</b>.</li>
      </ul>
      <!--TTN-->
      <p style="margin:10px 0 0;font-size:13px;line-height:1.6;color:#9a8b90;">🕊 Працюємо в умовах воєнного часу — тривоги чи збої інколи затримують доставку. Якщо щось піде не так — повідомимо вас особисто.</p>
    </td></tr></table>
  </td></tr>
"""

# ---- блок оплати (перед ним — гіфка), адаптується під післяплату/передоплату ----
def _payment_block(cod):
    if cod is False:  # повна передоплата
        head, body = ("💳 Оплата", "Замовлення <b>вже повністю оплачене</b> — просто заберіть посилку після огляду. Доплачувати при отриманні нічого не потрібно 💗")
    elif cod is True:  # післяплата (накладений платіж)
        head, body = ("💳 Оплата при отриманні", "Решту суми сплачуєте у відділенні <b>після огляду</b> посилки. Завдаток 200 грн, що бронював відправку, <b>зараховано</b> у вартість. При відмові від посилки після відправлення завдаток не повертається.")
    else:  # невідомо — нейтрально, без згадок завдатку/оплати
        head, body = ("💳 Оплата", "Оплата — згідно зі способом, який ви обрали при оформленні замовлення.")
    return (f'<tr><td style="padding:14px 22px 4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#fbf7ee;border-radius:14px;"><tr><td style="padding:16px 20px;">'
            f'<div style="font-size:16px;font-weight:700;color:#c79a3e;">{head}</div>'
            f'<p style="margin:8px 0 0;font-size:14px;line-height:1.65;color:#4a3f44;">{body}</p>'
            f'</td></tr></table></td></tr>')

# ---- хвіст листа: кнопки, контакти, футер (спільне) ----
_TAIL = r"""
  <tr><td style="padding:24px 22px 6px;text-align:center;">
    <a href="https://mamulya.lviv.ua/dostavka-i-oplata" style="display:block;width:250px;box-sizing:border-box;background:#E05A50;color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:13px 10px;border-radius:10px;margin:8px auto;text-align:center;">📦 Доставка та оплата</a>
    <a href="https://mamulya.lviv.ua/povernennya" style="display:block;width:250px;box-sizing:border-box;background:#ffffff;color:#E05A50;text-decoration:none;font-size:14px;font-weight:600;padding:13px 10px;border-radius:10px;border:1.5px solid #E05A50;margin:8px auto;text-align:center;">🔁 Повернення та обмін</a>
  </td></tr>
  <tr><td style="padding:14px 22px 28px;text-align:center;">
    <div style="font-size:15px;font-weight:700;color:#3a2f34;">📞 Маєте питання?</div>
    <p style="margin:6px 0 0;font-size:14px;line-height:1.7;color:#6e5f65;">
      Телефон / Viber / Telegram: <a href="tel:+380636324010" style="color:#E05A50;text-decoration:none;font-weight:600;white-space:nowrap;">063-632-40-10</a><br>
      Пошта: <a href="mailto:mamulyashopping@gmail.com" style="color:#E05A50;text-decoration:none;">mamulyashopping@gmail.com</a><br>
      <span style="color:#9a8b90;font-size:13px;">Пн–Пт 10:00–17:00</span>
    </p>
  </td></tr>
  <tr><td style="background:#f4ece9;padding:18px 22px;text-align:center;">
    <div style="font-size:12px;color:#a99ba0;line-height:1.6;">Mamulya.lviv · турботливий магазин для мам 💗<br>Ви отримали цей лист, бо оформили замовлення на mamulya.lviv.ua</div>
  </td></tr>
</table></td></tr></table></body></html>"""

# ---- секція «Як прийняти» під категорію ----
def _accept(title, bullets, tint="#eef6f0", head="#3f9d6c"):
    lis = "".join(f"<li>{b}</li>" for b in bullets)
    return (f'<tr><td style="padding:18px 22px 4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{tint};border-radius:14px;"><tr><td style="padding:18px 20px;">'
            f'<div style="font-size:17px;font-weight:700;color:{head};">{title}</div>'
            f'<ul style="margin:10px 0 0;padding-left:20px;font-size:14.5px;line-height:1.7;color:#4a3f44;">{lis}</ul>'
            f'</td></tr></table></td></tr>')

_VIDEO = "Якщо з замовленням щось не так — <b>зніміть відео прямо у відділенні</b> при отриманні, не вдома. Це ваша страховка."
_KNIFE = "<b>Не ріжте упаковку ножем</b> впритул до товару — так легко порізати річ. Відкривайте обережно."
ACCEPT = {
 "clothing": _accept("✅ Як прийняти посилку", [
    "Розпаковуйте <b>у відділенні, при менеджері</b> — так можна одразу оформити огляд.",
    _KNIFE,
    "Перевірте модель, розмір, колір, комплектність і цілісність.",
    _VIDEO]),
 "furniture": _accept("✅ Як прийняти великогабарит", [
    "Приймайте <b>при менеджері або курʼєрі</b>, не відходячи.",
    "Перевірте цілісність упаковки, відсутність сколів і пошкоджень.",
    "Звірте комплектність — <b>переконайтесь</b>, що всі деталі, кріплення та інструкція на місці.",
    "Є пошкодження — <b>зніміть відео у відділенні</b> при отриманні (не вдома) і складіть акт з оператором НП."]),
 "sling": _accept("✅ Як прийняти слінг / ерго", [
    "Звірте модель і колір.",
    "Підбір — <b>за віком і вагою малюка</b>, не за розміром одягу. Не впевнені — напишіть, підкажемо.",
    "До виробу додається інструкція.",
    _VIDEO], tint="#eef3f8", head="#4a7fb0"),
 "toy": _accept("✅ Як прийняти гру", [
    "Перевірте <b>комплектність</b> — усі картки й елементи на місці.",
    _VIDEO], tint="#fdf4ec", head="#cf8a3f"),
 "nonreturn": _accept("✅ Як прийняти — перевірте одразу", [
    "Розпаковуйте <b>у відділенні, при менеджері</b>.",
    _KNIFE,
    "⚠️ Перевірте <b>особливо уважно</b> при отриманні — модель, розмір, колір, цілісність.",
    "Помітили брак — <b>зніміть відео прямо у відділенні</b>, не вдома."], tint="#FCEBEA", head="#d06060"),
}

# ---- секція «Повернення» під категорію ----
_STEPS4 = ('<div style="margin:9px 0 0;"><div style="background:#FBF1EF;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#3f9d6c;">↩️ Як повернути — 4 кроки</div>'
    '<ol style="margin:8px 0 0;padding-left:18px;font-size:14px;line-height:1.6;color:#4a3f44;">'
    '<li>Напишіть нам <b>до відправлення</b></li><li>Запакуйте з бірками й упаковкою</li>'
    '<li>Відправте Новою Поштою («Легке повернення» — безкоштовно)</li><li>Отримайте кошти після перевірки</li>'
    '</ol></div></div>')

def _returns(intro, right_html, steps=True):
    left = _STEPS4 if steps else ""
    grid = f'{left}{right_html}' if right_html or steps else ""
    return (f'<tr><td style="padding:18px 22px 4px;">'
            f'<div style="font-size:17px;font-weight:700;color:#E05A50;margin-bottom:10px;">🔁 Повернення та обмін — 14 днів</div>'
            f'<p style="margin:0 2px 10px;font-size:14px;line-height:1.6;color:#4a3f44;">{intro}</p>{grid}</td></tr>')

_RIGHT_NONRET = ('<div style="margin:9px 0 0;"><div style="background:#FCEBEA;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#d06060;">🚫 Не підлягають поверненню</div>'
    '<ul style="margin:8px 0 0;padding-left:18px;font-size:14px;line-height:1.6;color:#4a3f44;">'
    '<li>Білизна (бюстгальтери, трусики)</li><li>Купальники</li><li>Колготи, панчішно-шкарпеткові</li><li>Косметика й гігієна</li>'
    '</ul></div></div>')

RETURNS = {
 "clothing": _returns(
    "Якщо не підійшов розмір, фасон чи колір — обміняємо або повернемо протягом <b>14 днів</b>. Головне: річ не носили, а <b>бірки, ярлики й упаковка</b> на місці.",
    _RIGHT_NONRET) + '<tr><td style="padding:0 22px;"><p style="margin:10px 2px 0;font-size:12.5px;color:#9a8b90;">Брак з вини виробника — обмін і доставка за наш рахунок. Перелік за постановою КМУ №172.</p></td></tr>',
 "furniture": _returns(
    "Товар належної якості обміняємо або повернемо протягом <b>14 днів</b>, якщо він не використовувався, збережено вигляд, комплектність та упаковку.",
    '<div style="margin:9px 0 0;"><div style="background:#FBF1EF;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#E05A50;">📦 Великогабарит</div>'
    '<ul style="margin:8px 0 0;padding-left:18px;font-size:14px;line-height:1.6;color:#4a3f44;">'
    '<li>Зворотну доставку великогабариту узгоджуємо окремо — напишіть нам</li>'
    '<li><b>Заводський брак</b> — замінимо за наш рахунок</li>'
    '<li><b>Пошкодження при перевезенні</b> — одразу оформіть акт у відділенні Нової Пошти при отриманні (це зона відповідальності перевізника)</li>'
    '</ul></div></div>'),
 "sling": _returns(
    "Слінг чи ерго-рюкзак можна повернути протягом <b>14 днів</b>, якщо він <b>не використовувався</b> (не прали), а бірки й упаковка на місці.",
    '<div style="margin:9px 0 0;"><div style="background:#eef3f8;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#4a7fb0;">🤱 Не підійшов?</div>'
    '<p style="margin:8px 0 0;font-size:13px;line-height:1.6;color:#4a3f44;">Спершу напишіть нам — часто вирішуємо питання консультацією.</p>'
    '</div></div>'),
 "toy": _returns(
    "Гру належної якості обміняємо або повернемо протягом <b>14 днів</b>, якщо збережено товарний вигляд, комплектність і упаковку, а гра не була у використанні.",
    '<div style="margin:9px 0 0;"><div style="background:#fdf4ec;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#cf8a3f;">🧩 Якщо щось не так</div>'
    '<p style="margin:8px 0 0;font-size:13px;line-height:1.6;color:#4a3f44;">Бракує елемента чи брак ліпучки — напишіть нам, замінимо за наш рахунок.</p>'
    '</div></div>'),
 "nonreturn": _returns(
    "⚠️ <b>Цей товар поверненню та обміну не підлягає</b> — білизна, купальники, колготи й косметика за гігієнічними причинами (постанова КМУ №172). Тому <b>перевірте все при отриманні</b>.",
    '<div style="margin:9px 0 0;"><div style="background:#FCEBEA;border-radius:12px;padding:16px 18px;">'
    '<div style="font-size:14px;font-weight:700;color:#d06060;">Якщо товар із браком</div>'
    '<p style="margin:8px 0 0;font-size:13px;line-height:1.6;color:#4a3f44;">Виявили заводський брак — одразу напишіть нам, розберемось і замінимо.</p>'
    '</div></div>', steps=False),
}

def _items_block(items):
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not items: return ""
    lis = "".join(f'<li style="margin:2px 0;">{i}</li>' for i in items[:12])
    return ('<tr><td style="padding:16px 22px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#FBF1EF;border-radius:14px;"><tr><td style="padding:16px 20px;">'
            '<div style="font-size:16px;font-weight:700;color:#E05A50;">🛍 Ваше замовлення</div>'
            f'<ul style="margin:8px 0 0;padding-left:20px;font-size:14px;line-height:1.6;color:#4a3f44;">{lis}</ul>'
            '</td></tr></table></td></tr>')

def _ttn_block(ttn):
    ttn = str(ttn or "").strip()
    if not ttn:
        return ('<p style="margin:4px 0 0;font-size:14px;line-height:1.6;color:#4a3f44;">'
                '📍 <b>Номер накладної (ТТН)</b> прийде в SMS від Нової Пошти — за ним відстежуйте посилку в застосунку НП.</p>')
    track = f"{_os.environ.get('TRACK_BASE', 'https://mamulya-bot.onrender.com')}/track?ttn={ttn}"
    return (f'<div style="margin:6px 0 0;padding:12px 14px;background:#ffffff;border:1.5px solid #E05A50;border-radius:12px;text-align:center;">'
            f'<div style="font-size:13px;color:#9a8b90;">Ваш номер накладної (ТТН)</div>'
            f'<div style="font-size:18px;font-weight:700;color:#3a2f34;letter-spacing:1px;margin:2px 0 8px;">{ttn}</div>'
            f'<a href="{track}" style="display:inline-block;background:#E05A50;color:#fff;text-decoration:none;font-size:13px;font-weight:600;padding:9px 20px;border-radius:9px;">Відстежити посилку</a></div>')

_RETURN_NOTE = ('<tr><td style="padding:18px 22px 2px;"><p style="margin:0;font-size:13.5px;line-height:1.65;color:#6e5f65;">'
    '📦 «Легке повернення» оформлюється у застосунку чи кабінеті Нової Пошти: <b>Мої відправлення → ваша посилка → Легке повернення</b>.<br>'
    '❗Пошкодження при доставці відшкодовуються <b>лише за актом</b>, складеним оператором Нової Пошти при отриманні. Без акта повернення коштів не здійснюється.'
    '</p></td></tr>')

DELIVERED_SUBJECT = "Дякуємо за покупку! \U0001F497 Ваша знижка та подарунок"
_LEVELS = [(4500, 3, "Базовий 💙"), (9000, 5, "Смарт 🧠"), (15000, 7, "VIP 👑"), (25000, 10, "Діамант 💎")]

def _lvl_row(th, pct, nm, on):
    # приглушена драбинка-довідка (не конкурує з кнопкою): поточний рівень — легкий блиш, решта — сіре
    bg = "background:#FCEBEA;" if on else ""
    col = "#E05A50" if on else "#9a8b90"
    thf = f"{th:,}".replace(",", " ")
    mark = " ✓" if on else ""
    w = "700" if on else "500"
    return (f'<tr><td style="padding:1px 0;"><table role=presentation width=100% cellpadding=0 cellspacing=0 style="{bg}border-radius:8px;"><tr>'
            f'<td style="padding:6px 12px;font-size:13px;color:{col};font-weight:{w};">{nm}{mark}</td>'
            f'<td style="padding:6px 12px;font-size:12.5px;color:{col};text-align:right;white-space:nowrap;">від {thf} грн · −{pct}%</td>'
            f'</tr></table></td></tr>')

def delivered_html(name=None, total=0, cur=None, nxt=None, bot_url="https://t.me/mamulyalvivbot", has_gift=False, okey=None):
    # cur/nxt = (поріг, %, назва) або None
    try: total = int(round(float(total)))
    except Exception: total = 0
    tot = f"{total:,}".replace(",", " ")
    if cur:
        lvl = f'<li>Ваш рівень: <b>{cur[2]}</b> — знижка <b>{cur[1]}%</b> на всі наступні покупки.</li>'
    else:
        lvl = '<li>Ви на старті програми — ще трішки до першої знижки 💙</li>'
    if nxt:
        rem = f"{int(nxt[0]-total):,}".replace(",", " ")
        nx = f'<li>До рівня <b>{nxt[2]}</b> лишилось <b>{rem} грн</b> → знижка {nxt[1]}%.</li>'
    else:
        nx = '<li>Ви на максимальному рівні — найбільша знижка назавжди 💎</li>'
    cur_name = cur[2] if cur else ""
    ladder = "".join(_lvl_row(th, pct, nm, nm == cur_name) for th, pct, nm in _LEVELS)
    if has_gift:
        gift = ('<div style="font-size:16px;font-weight:700;color:#E05A50;">🎁 Ваш баланс і купони — у боті</div>'
                '<p style="margin:8px 0 14px;font-size:14px;line-height:1.6;color:#4a3f44;">Там видно рівень, знижку та персональні купони. Загляньте 💗</p>'
                f'<a href="{bot_url}" style="display:inline-block;background:#E05A50;color:#fff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 36px;border-radius:12px;box-shadow:0 3px 10px rgba(224,90,80,.28);">Відкрити бот →</a>')
    else:
        gift = ('<div style="font-size:16px;font-weight:700;color:#E05A50;">🎁 За це замовлення вам належить подарунок</div>'
                '<p style="margin:8px 0 14px;font-size:14px;line-height:1.6;color:#4a3f44;">Купон на наступне замовлення, безкоштовна доставка або −20% на аналізи Dila — на вибір. Заберіть у нашому боті й стежте там за балансом:</p>'
                f'<a href="{bot_url}" style="display:inline-block;background:#E05A50;color:#fff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 36px;border-radius:12px;box-shadow:0 3px 10px rgba(224,90,80,.28);">🎁 Забрати подарунок →</a>')
    return f"""<!doctype html><html lang=uk><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name="x-apple-disable-message-reformatting"></head>
<body translate="no" class="notranslate" style="margin:0;padding:0;background:#f4ece9;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#4a3f44;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">Дякуємо за покупку 💗 Ваша накопичувальна знижка росте — і на вас чекає подарунок.</div>
<table role=presentation width=100% cellpadding=0 cellspacing=0 style="background:#f4ece9;"><tr><td align=center style="padding:24px 12px;">
<table role=presentation width=600 cellpadding=0 cellspacing=0 style="max-width:600px;width:100%;background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 2px 14px rgba(140,90,110,.1);">
  <tr><td style="background:#fff;padding:24px 22px 8px;text-align:center;">
    <img src="{ASSET}/logo-mamulya-lviv.png" width=210 alt="Mamulya.lviv" style="width:210px;max-width:66%;height:auto;"></td></tr>
  <tr><td style="padding:4px 22px 10px;text-align:center;">
    <div style="font-size:40px;line-height:1;margin-bottom:4px;">💗</div>
    <h1 style="margin:0 0 8px;font-size:23px;color:#3a2f34;font-weight:700;">Дякуємо за покупку!</h1>
    <p style="margin:0;font-size:15px;line-height:1.6;color:#6e5f65;">Сподіваємось, усе підійшло й тішить. А тепер приємне — ваша постійна знижка росте, і на вас чекає подарунок 🎁</p></td></tr>
  <tr><td style="padding:16px 22px 4px;">
    <table role=presentation width=100% cellpadding=0 cellspacing=0 style="background:#FCEBEA;border-radius:14px;"><tr><td style="padding:18px 20px;">
      <div style="font-size:17px;font-weight:700;color:#E05A50;">💳 Ваша постійна знижка</div>
      <ul style="margin:10px 0 0;padding-left:20px;font-size:14.5px;line-height:1.75;color:#4a3f44;">
        <li>Усього покупок у Mamulya.lviv: <b>{tot} грн</b></li>{lvl}{nx}</ul>
    </td></tr></table></td></tr>
  <tr><td style="padding:16px 22px 6px;"><table role=presentation width=100% cellpadding=0 cellspacing=0 style="background:#FBF1EF;border-radius:14px;"><tr><td style="padding:18px 20px;text-align:center;">
    {gift}</td></tr></table></td></tr>
  <tr><td style="padding:14px 22px 4px;">
    <div style="font-size:16px;font-weight:700;color:#E05A50;margin:0 2px 8px;">🏆 Рівні програми</div>
    <table role=presentation width=100% cellpadding=0 cellspacing=0>{ladder}</table></td></tr>
  <tr><td style="padding:14px 22px 4px;">
    <table role=presentation width=100% cellpadding=0 cellspacing=0 style="background:#fbf7ee;border-radius:14px;"><tr><td style="padding:16px 20px;">
      <div style="font-size:16px;font-weight:700;color:#c79a3e;">❓ Як працює програма</div>
      <ul style="margin:8px 0 0;padding-left:20px;font-size:14px;line-height:1.7;color:#4a3f44;">
        <li>Знижка <b>накопичувальна</b> — рахується від суми ваших викуплених замовлень і <b>не згорає</b>.</li>
        <li>Діє <b>автоматично</b> на всі наступні покупки, щойно ви на сайті — вводити нічого не треба.</li>
        <li><b>Повернення:</b> якщо оформите повернення товару, його сума віднімається з накопиченого — рівень може змінитися.</li>
        <li>Актуальний рівень і баланс завжди видно у нашому <b>боті</b>.</li>
      </ul></td></tr></table></td></tr>
  <tr><td style="padding:14px 22px 26px;text-align:center;">
    <div style="font-size:15px;font-weight:700;color:#3a2f34;">📞 Маєте питання?</div>
    <p style="margin:6px 0 0;font-size:14px;line-height:1.7;color:#6e5f65;">Телефон / Viber / Telegram: <a href="tel:+380636324010" style="color:#E05A50;text-decoration:none;font-weight:600;white-space:nowrap;">063-632-40-10</a><br>
    Пошта: <a href="mailto:mamulyashopping@gmail.com" style="color:#E05A50;text-decoration:none;">mamulyashopping@gmail.com</a></p></td></tr>
  <tr><td style="background:#f4ece9;padding:18px 22px;text-align:center;"><div style="font-size:12px;color:#a99ba0;line-height:1.6;">Mamulya.lviv · турботливий магазин для мам 💗<br>Ви отримали цей лист, бо забрали замовлення на mamulya.lviv.ua</div></td></tr>
</table></td></tr></table>{_px(okey)}</body></html>"""

def order_memo_html(items=None, ttn=None, cod=None, okey=None):
    cat = memo_category(items)
    top = (_TOP.replace("REPLACED_HERO", f"{ASSET}/mamulya-hero.gif")
                .replace("<!--ORDER_ITEMS-->", _items_block(items))
                .replace("<!--TTN-->", _ttn_block(ttn)))
    # блок оплати: для повної передоплати (cod=False) не показуємо взагалі
    pay = "" if cod is False else (_div("div-deposit.gif") + _payment_block(cod))
    return (top
            + _div("div-accept.gif") + ACCEPT[cat]
            + _div("div-return.gif") + RETURNS[cat] + _RETURN_NOTE
            + pay
            + _TAIL).replace("</body>", _px(okey)+"</body>")

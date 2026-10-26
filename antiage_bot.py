# -*- coding: utf-8 -*-
"""AntiAge Cosmetics бот (@AntiAgeCosmetics_Bot) — квіз-підбір догляду, перенесений із SendPulse.
Тільки stdlib. ENV: BOT_TOKEN, ADMIN_IDS, ADMIN_KEY, PEER_ADMIN (URL кабінету Mamulya), DB, PORT
"""
import json, os, sqlite3, threading, time, urllib.request
os.environ["TZ"] = "Europe/Kyiv"
try: time.tzset()
except Exception: pass
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x}
DB = sqlite3.connect(os.environ.get("DB", "antiage.db"), check_same_thread=False)
DB.executescript("""
create table if not exists users(chat_id integer primary key, src text default '', cat text default '', concern text default '', priority text default '', created real);
create table if not exists sent(chat_id int, key text, ts real, primary key(chat_id,key));
create table if not exists posts(id integer primary key autoincrement, ts real, text text);
create table if not exists orders(order_id text primary key, chat_id int, phone text, amount real, ts real, status int, replenish real);
create table if not exists gifts(chat_id int primary key, gift text, ts real);
create table if not exists msgs(id integer primary key autoincrement, chat_id int, dir text, text text, ts real);
create table if not exists shelf(id integer primary key autoincrement, chat_id int, order_id text, product text, category text, days int, opened real default 0, remind real default 0, reminded int default 0, ts real);
""")
DAY = 86400
SITE = "https://antiagecosmetics.com.ua"
SD_KEY = os.environ.get("SALESDRIVE_KEY", "")
REPLENISH_DAYS = 50  # крем/сироватка ~1,5-2 міс — нагадування про поповнення
SHELF_KW = [("сироватк", 45), ("ампул", 30), ("маск", 90), ("скраб", 120), ("пілінг", 90), ("вмива", 90), ("пінк", 90), ("міцеляр", 60), ("гель для душу", 30), ("тонік", 60), ("тонер", 60), ("крем", 60), ("spf", 60), ("сонцезахис", 60), ("олі", 90), ("шампун", 60), ("кондиціонер", 75), ("бальзам", 75), ("інтим", 60)]
SHELF_LEAD = 10  # нагадати за N днів до кінця; # ponytail: груба евристика терміну по назві, уточнимо по обʼєму товару пізніше
def shelf_days(name):
    n = (name or "").lower()
    for kw, dd in SHELF_KW:
        if kw in n: return kw, dd
    return "", REPLENISH_DAYS
def short_prod(name):
    name = (name or "").strip()
    return name if len(name) <= 44 else name[:43] + "…"
LVL = [(25000, 10, "Діамант"), (15000, 7, "VIP"), (9000, 5, "Смарт"), (4500, 3, "Базовий")]

def norm_phone(p):
    d = "".join(c for c in str(p) if c.isdigit())
    return "380" + d[-9:] if len(d) >= 9 else d

def sd_order(order_id):
    if not SD_KEY: return None
    try:
        req = urllib.request.Request(f"https://aleyana.salesdrive.me/api/order/list/?filter[id][from]={order_id}&filter[id][to]={order_id}", headers={"Form-Api-Key": SD_KEY})
        data = json.load(urllib.request.urlopen(req, timeout=20)).get("data", [])
        for o in data:
            if str(o.get("id")) == str(order_id): return o
        return data[0] if data else None
    except Exception as e: print("sd_order", e); return None

def sd_total(phone):
    # сума SOLD по всіх магазинах (спільний рівень)
    if not SD_KEY or not phone: return 0
    try:
        req = urllib.request.Request(f"https://aleyana.salesdrive.me/api/order/list/?filter[phone]={phone}&limit=100", headers={"Form-Api-Key": SD_KEY})
        data = json.load(urllib.request.urlopen(req, timeout=20)).get("data", [])
        return sum(float(o.get("paymentAmount") or 0) for o in data if int(o.get("statusId") or 0) == 5)
    except Exception as e: print("sd_total", e); return 0

DILA_CODE = os.environ.get("ANTIAGE_DILA_CODE", "667562")
FREESHIP_CODE = os.environ.get("ANTIAGE_FREESHIP_CODE", "")

def gift_menu(chat_id):
    if DB.execute("select 1 from gifts where chat_id=?", (chat_id,)).fetchone():
        return  # вже обрано
    btns = [[("🧪 −20% на аналізи в Dila", "gift:dila")]]
    if FREESHIP_CODE: btns.append([("📦 Безкоштовна доставка", "gift:ship")])
    if os.environ.get("ANTIAGE_REPEAT_CODE"): btns.append([("🎁 −10% на наступне замовлення", "gift:repeat")])
    send(chat_id, "🎁 Дякуємо за довіру! Оберіть подарунок, який вам зараз корисний:", btns)

def give_gift(chat_id, gift):
    DB.execute("insert or replace into gifts values(?,?,?)", (chat_id, gift, time.time())); DB.commit()
    if gift == "dila":
        send(chat_id, f"🧪 <b>−20% на аналізи в лабораторії Dila</b> — краса починається зсередини 💛\nКод: <code>{DILA_CODE}</code> — назвіть на рецепції або в кабінеті Dila.\nЗнижка не сумується з іншими.")
    elif gift == "ship":
        send(chat_id, f"📦 <b>Безкоштовна доставка</b> на наступне замовлення в AntiAge.\nКод: <code>{FREESHIP_CODE}</code> — введіть у полі «Маєте купон на знижку?».")
    elif gift == "repeat":
        code = os.environ.get("ANTIAGE_REPEAT_CODE", ""); desc = os.environ.get("ANTIAGE_REPEAT_DESC", "−10%")
        send(chat_id, f"🎁 Знижка <b>{desc}</b> на наступне замовлення.\nКод: <code>{code}</code> — у полі «Маєте купон на знижку?».")
    send(chat_id, "Збережено 💛 Промокод завжди під рукою — кнопка «🎁 Мій промокод» унизу.")

def level_line(phone):
    total = sd_total(phone)
    cur = next(((t, p, n) for t, p, n in LVL if total >= t), None)
    if not cur: return None
    return f"💎 Ваші покупки: <b>{total:,.0f} грн</b> — постійна знижка <b>{cur[1]}%</b> (рівень «{cur[2]}») діє на всі замовлення!".replace(",", " ")
PROMO = ("\n\nВаш промокод: <code>ANTIAGE10</code>\n"
         "🎯 10% знижки на перше замовлення\n⏰ Діє 7 днів\n"
         "📝 Поле «Маєте купон на знижку?» при оформленні\n"
         "❗ Не сумується з товарами зі знижками")

GREET = ("Привіт! 👋 Це AntiAge Cosmetics — ваш експерт у професійному догляді.\n\n"
         "У нас є засоби для обличчя, волосся, тіла та інтимного догляду. Щоб підібрати найкращі рекомендації "
         "та надсилати тільки корисну інформацію, поставимо кілька коротких питань про ваші потреби.\n\n"
         "Займе 2 хвилини, а ви отримаєте персональну знижку 10%! 😊")

Q1 = ("Яка категорія догляду вас зараз найбільше цікавить?", [
    ("Догляд за обличчям", "face"), ("Догляд за тілом", "body"), ("Догляд за волоссям", "hair"),
    ("Інтимний догляд", "intimate"), ("Комплексний догляд", "complex")])

Q2 = {
 "face": ("Що найбільше турбує в догляді за обличчям?", [
    ("Перші зморшки", "early"), ("Сухість", "dry"), ("Пігментація", "pigment"),
    ("Чутливість", "sens"), ("Глибокі зморшки", "mature"), ("Все добре — підтримка", "good")]),
 "body": ("Що найбільше турбує в догляді за тілом?", [
    ("Сухість", "dry"), ("Втрата пружності", "firm"), ("Целюліт", "cellu"),
    ("Розтяжки", "stretch"), ("Чутливість", "sens"), ("Загальний догляд", "good")]),
 "hair": ("Що найбільше турбує щодо волосся?", [
    ("Сухість і ламкість", "dry"), ("Жирність", "oily"), ("Лупа", "dandruff"),
    ("Випадіння", "loss"), ("Все добре — підтримка", "good")]),
}

Q3 = ("Що найважливіше при виборі засобів?", [
    ("Швидкий результат", "speed"), ("Відгуки", "reviews"), ("Безпечний склад", "safety"),
    ("Бренд", "brand"), ("Ціна/якість", "value")])

def rec(title, bullets, promise):
    return ("Дякуємо за відповіді! 💛 " + title + "\n\n" +
            "\n".join("🔸 " + b for b in bullets) + "\n\n" + promise + PROMO)

RECS = {
 ("face","early"):  rec("Чудово, що думаєте про профілактику! 👏", ["Сироватки з вітаміном C та пептидами", "М'які креми з ретинолом", "Якісний SPF щодня — це основа!"], "⚡ Результат помітний через 2–3 тижні!"),
 ("face","dry"):    rec("Розуміємо, як турбує сухість шкіри 💧", ["Креми з гіалуроновою кислотою", "Сироватки з церамідами", "Живильні нічні маски"], "🌿 Комфорт з першого застосування!"),
 ("face","pigment"):rec("Пігментація — це вирішувано! ✨", ["Сироватки з вітаміном C та арбутином", "М'які кислотні пілінги", "Освітлюючі креми з ніацинамідом"], "🌟 Рівний тон через 4–6 тижнів!"),
 ("face","sens"):   rec("Розуміємо важливість м'якого догляду 🌸", ["Гіпоалергенні креми без парабенів", "Заспокійливі сироватки з алое", "М'які очищувальні засоби"], "✅ Комфорт без подразнень!"),
 ("face","mature"): rec("Що потрібно для інтенсивної боротьби з віковими змінами:", ["Концентровані сироватки з пептидами", "Ліфтинг-креми з колагеном", "Відновлюючі нічні засоби"], "🚀 Помітне підтягування через місяць!"),
 ("face","good"):   rec("Чудово, що шкіра в хорошому стані! 😊", ["Якісні зволожувальні креми", "Антиоксидантні сироватки", "Професійні маски для сяйва"], "✨ Збережіть красу та молодість!"),
 ("body","dry"):    rec("Повернемо шкірі тіла комфорт 💧", ["Живильні батери й лосьйони", "Олійки для тіла після душу", "М'які кремові гелі для душу"], "🌿 Оксамитова шкіра щодня!"),
 ("body","firm"):   rec("Попрацюємо над пружністю 💪", ["Зміцнювальні креми з колагеном", "Моделюючі сироватки для тіла", "Сухі олійки з ліфтинг-ефектом"], "✨ Тонус помітний через 3–4 тижні!"),
 ("body","cellu"):  rec("Візьмемо целюліт під контроль 🍊", ["Антицелюлітні креми й гелі", "Розігріваючі засоби для масажу", "Скраби для стимуляції"], "⚡ У парі з масажем — результат швидше!"),
 ("body","stretch"):rec("Подбаємо про еластичність шкіри 🌸", ["Олійки проти розтяжок", "Креми з центелою і пептидами", "Живильні батери"], "💛 Регулярність — ключ до результату!"),
 ("body","sens"):   rec("М'який догляд для чутливої шкіри тіла 🌿", ["Гіпоалергенні лосьйони", "Засоби без віддушок", "Заспокійливі креми з пантенолом"], "✅ Комфорт без подразнень!"),
 ("body","good"):   rec("Підтримаємо шкіру в чудовій формі 😊", ["Зволожувальні лосьйони щодня", "Скраб раз на тиждень", "Олійка для сяйва"], "✨ Догляд, який приємно повторювати!"),
 ("hair","dry"):    rec("Повернемо волоссю м'якість і блиск 💛", ["Живильні маски з оліями", "Незмивні кондиціонери", "М'які безсульфатні шампуні"], "✨ Слухняне волосся через 2 тижні!"),
 ("hair","oily"):   rec("Контролюємо жирність волосся 🌿", ["Регулюючі шампуні з глиною", "Себорегулюючі тоніки", "Легкі кондиціонери тільки по довжині"], "✅ Свіжість на довше!"),
 ("hair","dandruff"):rec("Позбудемося лупи назавжди! ✨", ["Лікувальні шампуні з цинком", "Заспокійливі тоніки для шкіри голови", "М'які пілінги для очищення"], "🌿 Чиста шкіра голови через тиждень!"),
 ("hair","loss"):   rec("Зміцнимо волосся від коренів 💪", ["Стимулюючі сироватки для шкіри голови", "Зміцнювальні шампуні з кофеїном", "Вітамінні комплекси для волосся"], "🌱 Менше випадіння вже через місяць!"),
 ("hair","good"):   rec("Створимо ідеальну рутину для волосся! ✨", ["Якісні шампуні та кондиціонери", "Живильні маски раз на тиждень", "Термозахист перед укладкою"], "💛 Здорове волосся — щодня!"),
 ("intimate",""):   rec("Делікатна тема — делікатний догляд 🌸", ["М'які гелі для інтимної гігієни", "Засоби з молочною кислотою", "Гіпоалергенні формули без мила"], "✅ Комфорт і впевненість щодня!"),
 ("complex",""):    rec("Комплексний догляд — найкраща інвестиція 💛", ["Базовий набір для обличчя: очищення + крем + SPF", "Догляд за тілом: лосьйон і скраб", "Волосся: шампунь + маска"], "✨ Підберемо все в одному замовленні!"),
}

DRIPS = [(2, "d2", "Ваш промокод <code>ANTIAGE10</code> (−10% на перше замовлення) ще діє 💛 Якщо сумніваєтесь у виборі — напишіть нам, підкажемо під ваш тип шкіри."),
         (5, "d5", "Нагадуємо востаннє: промокод <code>ANTIAGE10</code> діє ще 2 дні ⏰ Після цього більше не турбуватимемо 😊")]

def tg(method, **kw):
    req = urllib.request.Request(API + method, json.dumps(kw).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

def log_msg(chat_id, direction, text):
    try:
        DB.execute("insert into msgs(chat_id,dir,text,ts) values(?,?,?,?)", (chat_id, direction, text, time.time())); DB.commit()
    except Exception as e: print("log_msg", e)

def send(chat_id, text, buttons=None):
    log_msg(chat_id, "out", text)
    kw = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if buttons:
        kw["reply_markup"] = {"inline_keyboard": [[
            {"text": t, **({"url": d} if d.startswith("http") else {"callback_data": d})} for t, d in row] for row in buttons]}
    else:
        kw["reply_markup"] = {"keyboard": [[{"text": "🎁 Мій промокод"}, {"text": "🛍 Каталог"}], [{"text": "🧴 Моя полиця"}, {"text": "🔄 Пройти підбір заново"}], [{"text": "💬 Підтримка"}]],
                              "resize_keyboard": True, "is_persistent": True}
    return tg("sendMessage", **kw)

def ask(chat_id, q, options, prefix):
    send(chat_id, q, [[(label, f"{prefix}:{val}")] for label, val in options])

def start_quiz(chat_id):
    send(chat_id, GREET)
    ask(chat_id, Q1[0], Q1[1], "q1")

def on_start(chat_id, arg):
    DB.execute("insert or ignore into users(chat_id, src, created) values(?,?,?)", (chat_id, arg or "direct", time.time()))
    DB.execute("update users set src=? where chat_id=? and coalesce(src,'')=''", (arg or "direct", chat_id)); DB.commit()
    if arg and arg.isdigit():
        return after_purchase(chat_id, arg)
    start_quiz(chat_id)

def seed_shelf(chat_id, order_id, order):
    added = []; now = time.time(); i = 0
    for p in ((order or {}).get("products") or []):
        name = (p.get("text") or "").strip()
        if not name or not (p.get("sku") or "").strip() or name.upper() == "КУПОН":
            continue
        if DB.execute("select 1 from shelf where chat_id=? and order_id=? and product=?", (chat_id, order_id, name)).fetchone():
            continue
        cat, dd = shelf_days(name)
        remind = now + max(dd - SHELF_LEAD, 7) * DAY + i * 2 * DAY  # авто-старт від доставки; +2дн/товар щоб нагадування не падали разом
        DB.execute("insert into shelf(chat_id,order_id,product,category,days,opened,remind,reminded,ts) values(?,?,?,?,?,?,?,0,?)",
                   (chat_id, order_id, name, cat, dd, now, remind, now))
        added.append(name); i += 1
    DB.commit()
    return added

def shelf_prompt(chat_id, added):
    if added:
        send(chat_id, "🧴 Додав на вашу полицю догляду: <b>" + ", ".join(short_prod(a) for a in added) + "</b>.\n"
             "Я сам нагадаю, коли кожен засіб добігатиме кінця — щоб ви встигли докупити без паузи в догляді 💛")

def shelf_view(chat_id):
    rows = DB.execute("select id, product, opened, days from shelf where chat_id=? order by ts desc limit 15", (chat_id,)).fetchall()
    if not rows:
        return send(chat_id, "🧴 Ваша полиця догляду поки порожня.\nЗасоби зʼявляться тут після замовлення — і я нагадаю, коли час докупити 💛")
    now = time.time(); lines = ["🧴 <b>Ваша полиця догляду</b>\nНагадаю про кожен засіб, коли добігатиме кінця 💛\n"]; btns = []
    for rid, prod, opened, days in rows:
        left = int(((opened or now) + (days or REPLENISH_DAYS) * DAY - now) / DAY)
        lines.append(f"• {short_prod(prod)}\n   нагадаю ~через {max(left - SHELF_LEAD, 0)} дн.")
        btns.append([(f"✔ Закінчився: {prod[:14]}", f"sh:d:{rid}")])
    return send(chat_id, "\n".join(lines), btns)

def after_purchase(chat_id, order_id):
    o = sd_order(order_id)
    phone = norm_phone((o.get("contacts") or [{}])[0].get("phone", [""])[0]) if o and isinstance(o.get("contacts"), list) else ""
    amount = float(o.get("paymentAmount") or 0) if o else 0
    status = int(o.get("statusId") or 0) if o else 0
    DB.execute("insert or replace into orders values(?,?,?,?,?,?,?)", (order_id, chat_id, phone, amount, time.time(), status,
               time.time() + REPLENISH_DAYS * DAY if status == 5 else 0)); DB.commit()
    send(chat_id, "Дякуємо за замовлення в AntiAge Cosmetics 💛 Ми вже готуємо вашу посилку.")
    ll = level_line(phone)
    if ll: send(chat_id, ll)
    if status == 5:
        gift_menu(chat_id)
        shelf_prompt(chat_id, seed_shelf(chat_id, order_id, o))
    else:
        send(chat_id, "А поки — підкажу, як доглядати за шкірою правильно 💧 Щойно отримаєте посилку, на вас чекатиме подарунок 🎁")

def finish(chat_id):
    row = DB.execute("select cat, concern from users where chat_id=?", (chat_id,)).fetchone()
    cat, concern = row or ("complex", "")
    text = RECS.get((cat, concern)) or RECS.get((cat, "")) or RECS[("complex", "")]
    send(chat_id, text, [[("🛍 Обрати на сайті", SITE)]])
    DB.execute("insert or ignore into sent values(?,?,?)", (chat_id, "quiz_done", time.time())); DB.commit()
    send(chat_id, "Рекомендації збережено 💛 Кнопки внизу — промокод, каталог і підтримка завжди під рукою.")

def on_callback(cb):
    chat_id, data = cb["message"]["chat"]["id"], cb["data"]
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data.startswith("gift:"):
        return give_gift(chat_id, data[5:])
    if data.startswith("sh:l:"):
        DB.execute("update shelf set remind=?, reminded=0 where id=? and chat_id=?", (time.time() + 18 * DAY, data[5:], chat_id)); DB.commit()
        return send(chat_id, "Добре 💛 Нагадаю ще раз приблизно за 2,5 тижні.")
    if data.startswith("sh:d:"):
        DB.execute("delete from shelf where id=? and chat_id=?", (data[5:], chat_id)); DB.commit()
        return send(chat_id, "Прибрав із полиці ✅ Докупите — додам знову автоматично.")
    if data.startswith("q1:"):
        cat = data[3:]
        DB.execute("update users set cat=? where chat_id=?", (cat, chat_id)); DB.commit()
        if cat in Q2: ask(chat_id, Q2[cat][0], Q2[cat][1], "q2")
        else: ask(chat_id, Q3[0], Q3[1], "q3")
    elif data.startswith("q2:"):
        DB.execute("update users set concern=? where chat_id=?", (data[3:], chat_id)); DB.commit()
        ask(chat_id, Q3[0], Q3[1], "q3")
    elif data.startswith("q3:"):
        DB.execute("update users set priority=? where chat_id=?", (data[3:], chat_id)); DB.commit()
        finish(chat_id)

def on_text(chat_id, t):
    t = t.strip()
    if chat_id in ADMINS and t == "/stats":
        n = lambda q: DB.execute(q).fetchone()[0]
        done = n("select count(*) from sent where key='quiz_done'")
        total = n("select count(*) from users")
        return send(chat_id, f"👥 У боті: {total}\n✅ Пройшли квіз: {done}")
    if chat_id in ADMINS and t.startswith("/post"):
        body = t[5:].strip()
        if not body: return send(chat_id, "Формат: /post текст")
        cur = DB.execute("insert into posts(ts,text) values(?,?)", (time.time(), body)); pid = cur.lastrowid; DB.commit()
        ok = 0
        for (cid,) in DB.execute("select chat_id from users"):
            try:
                send(cid, body); ok += 1
                DB.execute("insert or ignore into sent values(?,?,?)", (cid, f"post:{pid}", time.time()))
            except Exception as e: print("post", e)
        DB.commit()
        return send(chat_id, f"Надіслано {ok}")
    if t == "🎁 Мій промокод":
        return send(chat_id, "Ваш промокод на першу покупку: <code>ANTIAGE10</code> (−10%)\nВведіть у полі «Маєте купон на знижку?» при оформленні. Не сумується з товарами зі знижками.", [[("🛍 На сайт", SITE)]])
    if t == "🛍 Каталог":
        return send(chat_id, "Обирайте: обличчя, тіло, волосся, інтимний догляд 💛", [[("Відкрити каталог", SITE)]])
    if t == "🔄 Пройти підбір заново":
        return start_quiz(chat_id)
    if t == "🧴 Моя полиця":
        return shelf_view(chat_id)
    if t == "💬 Підтримка":
        return send(chat_id, "Напишіть нам — підкажемо із засобом і складом 💛\n📩 Instagram/сайт: antiagecosmetics.com.ua\n🕐 Пн–Пт 10:00–17:00")
    send(chat_id, "Натисніть кнопку внизу — або «🔄 Пройти підбір заново», щоб отримати рекомендації 😊")

def poll():
    offset = 0
    while True:
        try:
            for u in tg("getUpdates", offset=offset, timeout=50)["result"]:
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    cb = u["callback_query"]; log_msg(cb["message"]["chat"]["id"], "in", "[кнопка] " + cb.get("data", "")); on_callback(cb)
                elif "message" in u and "text" in u["message"]:
                    m = u["message"]; txt = m["text"]; log_msg(m["chat"]["id"], "in", txt)
                    if txt.startswith("/start"): on_start(m["chat"]["id"], txt.split(" ", 1)[1] if " " in txt else "")
                    else: on_text(m["chat"]["id"], txt)
        except Exception as e:
            print("poll", e); time.sleep(5)

def replenish_text(phone):
    total = sd_total(phone)
    cur = next(((t, p, n) for t, p, n in LVL if total >= t), None)
    base = "Ваш догляд, мабуть, добігає кінця 💧 Час поповнити запас, щоб не переривати рутину."
    code = os.environ.get("ANTIAGE_REPEAT_CODE", "")
    if code:
        desc = os.environ.get("ANTIAGE_REPEAT_DESC", "−10%")
        return base + f"\n\n🎁 Тільки для вас — знижка <b>{desc}</b> на це замовлення. Промокод: <code>{code}</code> у полі «Маєте купон на знижку?» 👇"
    if cur:
        return base + f"\n\n💎 Ваша постійна знижка <b>{cur[1]}%</b> (рівень «{cur[2]}») чекає — просто оберіть улюблене 👇"
    nxt = ([l for l in reversed(LVL) if total < l[0]] or [None])[0]
    if nxt and total > 0:
        need = f"{nxt[0]-total:,.0f}".replace(",", " ")
        return base + f"\n\nА цим замовленням ви наблизитесь до постійної знижки {nxt[1]}% — лишилось лише {need} грн 👇"
    return base + "\n\nОберіть улюблене — і почніть накопичувати на постійну знижку до 10% 👇"
CROSS_TEXT = ("Як ваша шкіра? 🌿 Якщо результат тішить — саме час підсилити догляд: сироватка + крем працюють у парі краще, ніж окремо.\n\n"
    "Загляньте в каталог — підберемо наступний крок 💛")

def cron():
    while True:
        now = time.time()
        for chat_id, ts0 in DB.execute("select chat_id, ts from sent where key='quiz_done'"):
            for days, key, text in DRIPS:
                if now - ts0 >= days * DAY and not DB.execute("select 1 from sent where chat_id=? and key=?", (chat_id, key)).fetchone():
                    try:
                        send(chat_id, text, [[("🛍 На сайт", SITE)]])
                        DB.execute("insert into sent values(?,?,?)", (chat_id, key, now))
                    except Exception as e: print("drip", e)
        # поповнення + крос-сел за датою SOLD
        for chat_id, rep in DB.execute("select chat_id, replenish from orders where replenish>0 and replenish<=?", (now,)):
            using_shelf = DB.execute("select 1 from shelf where chat_id=? and opened>0 limit 1", (chat_id,)).fetchone()
            if not using_shelf and not DB.execute("select 1 from sent where chat_id=? and key='replenish'", (chat_id,)).fetchone():
                ph_ = (DB.execute("select phone from orders where chat_id=? order by ts desc limit 1", (chat_id,)).fetchone() or [""])[0]
                try:
                    send(chat_id, replenish_text(ph_), [[("🛍 Поповнити запас", SITE)]])
                    DB.execute("insert into sent values(?,?,?)", (chat_id, "replenish", now))
                except Exception as e: print("replenish", e)
            DB.execute("update orders set replenish=0 where chat_id=? and replenish<=?", (chat_id, now))
        for chat_id, ts0 in DB.execute("select chat_id, ts from orders group by chat_id having max(ts)=ts"):
            if now - ts0 >= 14 * DAY and not DB.execute("select 1 from sent where chat_id=? and key='cross'", (chat_id,)).fetchone():
                try:
                    send(chat_id, CROSS_TEXT, [[("🌿 Каталог", SITE)]])
                    DB.execute("insert into sent values(?,?,?)", (chat_id, "cross", now))
                except Exception as e: print("cross", e)
        # полиця: по-товарні нагадування про докупівлю
        for chat_id, rid, prod, ph_ in DB.execute("select s.chat_id, s.id, s.product, (select phone from orders o where o.chat_id=s.chat_id order by o.ts desc limit 1) from shelf s where s.opened>0 and s.remind>0 and s.remind<=? and s.reminded=0", (now,)):
            try:
                ll = level_line(ph_ or "")
                send(chat_id, f"🧴 Ваш засіб <b>{short_prod(prod)}</b>, мабуть, добігає кінця 💧 Докупити, щоб не переривати догляд?" + ("\n\n" + ll if ll else ""), [[("🛍 Докупити", SITE)], [("⏳ Ще є — нагадай згодом", f"sh:l:{rid}")]])
                DB.execute("update shelf set reminded=1 where id=?", (rid,))
            except Exception as e: print("shelf-remind", e)
        DB.commit()
        time.sleep(3600)

CAB_CSS = '''<style>
*{box-sizing:border-box}body{font:13.5px/1.5 "Golos Text",system-ui,sans-serif;margin:0;background:#F2F5F1;color:#22301F;padding:18px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:8px}.top h1{font-size:19px;margin:0}.upd{font-size:11.5px;color:#93A28C}
.nav{display:flex;gap:6px;margin:8px 0 16px}.nav a{padding:6px 14px;border-radius:999px;background:#fff;border:1px solid #DFE7DB;color:#5F7057;text-decoration:none;font-size:13px}
.nav a.on{background:#4E7A63;color:#fff;border-color:#4E7A63}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.tile{background:#fff;border:1px solid #DFE7DB;border-radius:10px;padding:9px 15px;min-width:108px}
.tile b{display:block;font-size:21px}.tile span{font-size:10.5px;color:#93A28C;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.p{background:#fff;border:1px solid #DFE7DB;border-radius:12px;padding:14px}.p.wide{grid-column:1/-1}
.p h2{font-size:13px;color:#5F7057;margin:0 0 10px;font-weight:600}.p h2 small{color:#A9B6A2;font-weight:400}
table{border-collapse:collapse;width:100%;font-size:12.5px}td,th{padding:5px 8px;border-bottom:1px solid #EEF2EC;text-align:left}
th{color:#93A28C;font-weight:500}td.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{width:64px}.bar i{display:inline-block;height:7px;background:#9FD8BE;border-radius:4px}
a{color:#4E7A63}
</style>'''

def admin_page():
    q = lambda sql: DB.execute(sql).fetchall()
    n = lambda sql: q(sql)[0][0]
    peer = os.environ.get("PEER_ADMIN", "")
    AK = os.environ.get("ADMIN_KEY", "")
    CAT = {"face": "Обличчя", "body": "Тіло", "hair": "Волосся", "intimate": "Інтимний", "complex": "Комплексний", "": "—"}
    SRC = {"promo": "попап сайту", "qr": "QR з пакування", "direct": "самі знайшли", "": "—"}
    GIFTU = {"dila": "Dila −20%", "ship": "Безкошт. доставка", "repeat": "−10% повторне"}
    CONC = {"early": "Перші зморшки", "dry": "Сухість", "pigment": "Пігментація", "sens": "Чутливість", "mature": "Глибокі зморшки",
            "good": "Підтримка", "firm": "Пружність", "cellu": "Целюліт", "stretch": "Розтяжки", "oily": "Жирність", "dandruff": "Лупа", "loss": "Випадіння"}
    pct = lambda a, b: f"{a/b*100:.0f}%" if b else "—"
    nc = n("select count(*) from users")
    done = n("select count(*) from sent where key='quiz_done'")
    ord_all = n("select count(*) from orders")
    sold = n("select count(*) from orders where status=5")
    buyers = n("select count(distinct chat_id) from orders")
    sold_buyers = n("select count(distinct chat_id) from orders where status=5")
    giftn = n("select count(*) from gifts")
    phones = n("select count(distinct phone) from orders where coalesce(phone,'')!=''")
    cards = [("Клієнтів у боті", nc), ("Пройшли квіз", done), ("Замовлень", ord_all),
             ("Викуплено", sold), ("Подарунків", giftn), ("З телефоном", phones)]
    tiles = "".join(f"<div class=tile><b>{v}</b><span>{k}</span></div>" for k, v in cards)

    def bars(data, names=None, tot=None):
        mx = max([r[1] for r in data], default=1) or 1
        t = tot or sum(r[1] for r in data) or 1
        return "".join(f"<tr><td>{(names or {}).get(k, k)}</td><td class=n>{v}</td><td class=n>{v/t*100:.0f}%</td><td class=bar><i style=width:{int(v/mx*100)}%></i></td></tr>" for k, v in data) or "<tr><td>—</td></tr>"

    fun = (f"<tr><td>Зайшли в бот</td><td class=n>{nc}</td><td class=n>100%</td></tr>"
           f"<tr><td>Пройшли квіз</td><td class=n>{done}</td><td class=n>{pct(done, nc)}</td></tr>"
           f"<tr><td>Зробили замовлення</td><td class=n>{buyers}</td><td class=n>{pct(buyers, nc)}</td></tr>"
           f"<tr><td><b>Викупили</b></td><td class=n><b>{sold_buyers}</b></td><td class=n><b>{pct(sold_buyers, nc)}</b></td></tr>")
    cats_h = bars(q("select cat, count(*) from users group by cat order by 2 desc"), CAT)
    conc_h = bars(q("select concern, count(*) from users where concern!='' group by concern order by 2 desc limit 10"), CONC)
    src_h = bars(q("select coalesce(nullif(src,''),''), count(*) from users group by 1 order by 2 desc"), SRC)
    gifts_h = bars(q("select gift, count(*) from gifts group by gift order by 2 desc"), GIFTU)
    drip = {k: n(f"select count(*) from sent where key='{k}'") for k in ("d2", "d5", "replenish", "cross")}
    auto = (f"<tr><td>Драйп D+2</td><td class=n>{drip['d2']}</td></tr>"
            f"<tr><td>Драйп D+5</td><td class=n>{drip['d5']}</td></tr>"
            f"<tr><td>Поповнення D+50</td><td class=n>{drip['replenish']}</td></tr>"
            f"<tr><td>Крос-сел D+14</td><td class=n>{drip['cross']}</td></tr>")

    lvlc = {nm: 0 for _, _, nm in LVL}
    near = []
    for ph, tot in q("select phone, sum(amount) from orders where status=5 and coalesce(phone,'')!='' group by phone"):
        tot = tot or 0
        cur = next(((t, p, nm) for t, p, nm in LVL if tot >= t), None)
        if cur: lvlc[cur[2]] += 1
        nxt = ([l for l in reversed(LVL) if tot < l[0]] or [None])[0]
        if nxt and tot: near.append((ph, tot, nxt[0] - tot, nxt[1]))
    lvl_rows = "".join(f"<tr><td>{nm}</td><td class=n>{lvlc.get(nm, 0)}</td></tr>" for _, _, nm in LVL)
    near_rows = "".join(f"<tr><td>{ph}</td><td class=n>{t:,.0f} грн</td><td class=n>{d:,.0f} грн до {p}%</td></tr>".replace(",", " ") for ph, t, d, p in sorted(near, key=lambda x: x[2])[:10]) or "<tr><td>—</td></tr>"

    recent = q("select chat_id, coalesce(nullif(cat,''),'—'), coalesce(nullif(concern,''),'—'), coalesce(nullif(src,''),'—'), coalesce(datetime(created,'unixepoch','localtime'),''), (select count(*) from gifts g where g.chat_id=users.chat_id), (select count(*) from orders o where o.chat_id=users.chat_id) from users order by created desc limit 200")
    rec_rows = "".join(f"<tr><td><a href='/client?key={AK}&id={r[0]}'>{r[0]}</a></td><td>{CAT.get(r[1], r[1])}</td><td>{CONC.get(r[2], r[2])}</td><td>{SRC.get(r[3], r[3])}</td><td class=n>{(r[4] or '')[5:16]}</td><td class=n>{r[5]}</td><td class=n>{r[6]}</td></tr>" for r in recent)

    def panel(title, inner, wide=False):
        return f'<section class="p{" wide" if wide else ""}"><h2>{title}</h2>{inner}</section>'
    nav = '<div class=nav><a class=on href="#">🌿 AntiAge</a>' + (f'<a href="{peer}">💗 Mamulya</a>' if peer else "") + '</div>'
    grid = (panel("Воронка · бот → квіз → замовлення → викуп", f"<table>{fun}</table>")
            + panel("Категорії інтересу (квіз)", f"<table>{cats_h}</table>")
            + panel("Що турбує (concern)", f"<table>{conc_h}</table>")
            + panel("Звідки прийшли", f"<table>{src_h}</table>")
            + panel("Обрані подарунки", f"<table>{gifts_h}</table>")
            + panel("Автосерії надіслано", f"<table>{auto}</table>")
            + panel("Рівні лояльності <small>лок. по викуплених</small>", f"<table>{lvl_rows}</table>")
            + panel("Трішки до рівня", f"<table>{near_rows}</table>")
            + panel("Останні клієнти", f"<table><tr><th>ID</th><th>Категорія</th><th>Турбує</th><th>Джерело</th><th>Зайшла</th><th>🎁</th><th>Замовл.</th></tr>{rec_rows}</table>", wide=True))
    return f"""<!doctype html><html lang=uk><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AntiAge Bot — кабінет</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌿</text></svg>">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&display=swap">
{CAB_CSS}
<div class=top><h1>🌿 AntiAge Bot</h1><span class=upd>оновлено {time.strftime("%d.%m %H:%M")}</span></div>
{nav}
<div class=tiles>{tiles}</div>
<div class=grid>{grid}</div></html>"""

def client_page(cid):
    AK = os.environ.get("ADMIN_KEY", "")
    try: ci = int(cid)
    except Exception: ci = 0
    CAT = {"face": "Обличчя", "body": "Тіло", "hair": "Волосся", "intimate": "Інтимний", "complex": "Комплексний", "": "—"}
    SRC = {"promo": "попап сайту", "qr": "QR з пакування", "direct": "самі знайшли", "": "—"}
    CONC = {"early": "Перші зморшки", "dry": "Сухість", "pigment": "Пігментація", "sens": "Чутливість", "mature": "Глибокі зморшки", "good": "Підтримка", "firm": "Пружність", "cellu": "Целюліт", "stretch": "Розтяжки", "oily": "Жирність", "dandruff": "Лупа", "loss": "Випадіння"}
    GIFTU = {"dila": "Dila −20%", "ship": "Безкошт. доставка", "repeat": "−10% повторне"}
    KEYU = {"quiz_done": "Пройшов квіз", "d2": "Драйп D+2", "d5": "Драйп D+5", "replenish": "Поповнення D+50", "cross": "Крос-сел D+14"}
    PR = {"speed": "Швидкий результат", "reviews": "Відгуки", "safety": "Безпечний склад", "brand": "Бренд", "value": "Ціна/якість", "": "—"}
    money = lambda x: f"{(x or 0):,.0f}".replace(",", " ")
    esc = lambda t: (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    head = f"""<!doctype html><html lang=uk><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>AntiAge · клієнт {ci}</title>{CAB_CSS}"""
    back = f"<div class=nav><a href='/admin?key={AK}'>← кабінет</a></div>"
    row = DB.execute("select src,cat,concern,priority,created from users where chat_id=?", (ci,)).fetchone()
    if not row:
        return head + f"<div class=top><h1>🌿 Клієнт {ci}</h1></div>{back}<p style='padding:14px;color:#93A28C'>Такого клієнта нема в базі.</p></html>"
    src, cat, concern, priority, created = row
    created_s = (DB.execute("select coalesce(datetime(?,'unixepoch','localtime'),'')", (created,)).fetchone()[0] or "")[:16]
    phone = (DB.execute("select phone from orders where chat_id=? and coalesce(phone,'')!='' order by ts desc limit 1", (ci,)).fetchone() or [""])[0]
    tot = (DB.execute("select coalesce(sum(amount),0) from orders where chat_id=? and status=5", (ci,)).fetchone() or [0])[0] or 0
    cur = next(((t, p, nm) for t, p, nm in LVL if tot >= t), None)
    lvl = f"{cur[1]}% «{cur[2]}»" if cur else "рівня ще нема"
    prof = (f"<tr><td>Категорія</td><td>{CAT.get(cat, cat or '—')}</td></tr>"
            f"<tr><td>Турбує</td><td>{CONC.get(concern, concern or '—')}</td></tr>"
            f"<tr><td>Пріоритет</td><td>{PR.get(priority, priority or '—')}</td></tr>"
            f"<tr><td>Джерело</td><td>{SRC.get(src, src or '—')}</td></tr>"
            f"<tr><td>Телефон</td><td>{phone or '—'}</td></tr>"
            f"<tr><td>Зайшов</td><td>{created_s or '—'}</td></tr>"
            f"<tr><td>Викуплено всього</td><td>{money(tot)} грн</td></tr>"
            f"<tr><td>Рівень лояльності</td><td>{lvl}</td></tr>")
    st = lambda s: {5: "викуплено", 6: "скасовано", 13: "скасовано"}.get(s, "в роботі")
    orders = DB.execute("select order_id, amount, status, coalesce(datetime(ts,'unixepoch','localtime'),'') from orders where chat_id=? order by ts desc", (ci,)).fetchall()
    ord_rows = "".join(f"<tr><td>{o[0]}</td><td class=n>{money(o[1])} грн</td><td>{st(o[2])}</td><td class=n>{o[3][:16]}</td></tr>" for o in orders) or "<tr><td>—</td></tr>"
    gifts = DB.execute("select gift, coalesce(datetime(ts,'unixepoch','localtime'),'') from gifts where chat_id=?", (ci,)).fetchall()
    gift_rows = "".join(f"<tr><td>{GIFTU.get(g[0], g[0])}</td><td class=n>{g[1][:16]}</td></tr>" for g in gifts) or "<tr><td>—</td></tr>"
    sent = DB.execute("select key, coalesce(datetime(ts,'unixepoch','localtime'),'') from sent where chat_id=? order by ts", (ci,)).fetchall()
    sent_rows = "".join(f"<tr><td>{KEYU.get(s[0], s[0])}</td><td class=n>{s[1][:16]}</td></tr>" for s in sent if not s[0].startswith('post:')) or "<tr><td>—</td></tr>"
    shelf = DB.execute("select product, category, opened, days, reminded from shelf where chat_id=? order by ts desc", (ci,)).fetchall()
    def shst(o2, d2, r2):
        if not o2: return "не відкрито"
        if r2: return "нагадано докупити"
        return f"лишилось ~{max(int((o2 + (d2 or REPLENISH_DAYS) * DAY - time.time()) / DAY), 0)} дн."
    shelf_rows = "".join(f"<tr><td>{(p or '')[:46]}</td><td>{c or '—'}</td><td>{shst(o2, d2, r2)}</td></tr>" for p, c, o2, d2, r2 in shelf) or "<tr><td>—</td></tr>"
    msgs = DB.execute("select dir, text, coalesce(datetime(ts,'unixepoch','localtime'),'') from msgs where chat_id=? order by ts desc limit 300", (ci,)).fetchall()
    msg_rows = "".join(f"<tr><td class=n style='white-space:nowrap;color:#93A28C'>{m[2][5:16]}</td><td style='white-space:nowrap'>{'→ бот' if m[0]=='out' else '← клієнт'}</td><td>{esc(m[1])[:500]}</td></tr>" for m in msgs) or "<tr><td colspan=3 style='color:#93A28C'>Поки порожньо — логування щойно увімкнено, накопичуватиметься з нових повідомлень.</td></tr>"
    def panel(title, inner, wide=False):
        return f'<section class="p{" wide" if wide else ""}"><h2>{title}</h2>{inner}</section>'
    grid = (panel("Профіль", f"<table>{prof}</table>")
            + panel("Замовлення", f"<table>{ord_rows}</table>")
            + panel("Подарунки", f"<table>{gift_rows}</table>")
            + panel("Отримані автосерії", f"<table>{sent_rows}</table>")
            + panel("🧴 Полиця догляду", f"<table>{shelf_rows}</table>")
            + panel("Історія переписки <small>останні 300</small>", f"<table>{msg_rows}</table>", wide=True))
    top = f"<div class=top><h1>🌿 Клієнт {ci}</h1><span class=upd>{phone or ''}</span></div>"
    return head + top + back + f"<div class=grid>{grid}</div></html>"

HTTPServer.allow_reuse_address = True
class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
        o = body.get("data", body)
        if isinstance(o, list): o = o[0]
        try:
            oid = str(o.get("id")); status = int(o.get("statusId") or 0)
            phone = norm_phone((o.get("contacts") or [{}])[0].get("phone", [""])[0]) if isinstance(o.get("contacts"), list) else ""
            row = DB.execute("select chat_id, replenish from orders where order_id=?", (oid,)).fetchone()
            if row:
                cid = row[0]
                if status == 5 and not row[1]:
                    DB.execute("update orders set status=5, replenish=? where order_id=?", (time.time() + REPLENISH_DAYS * DAY, oid))
                    send(cid, "Замовлення отримано 🎉 Дякуємо! Гарного догляду 💛")
                    ll = level_line(phone)
                    if ll: send(cid, ll)
                    gift_menu(cid)
                    shelf_prompt(cid, seed_shelf(cid, oid, sd_order(oid)))
                elif status in (6, 13):
                    DB.execute("update orders set replenish=0 where order_id=?", (oid,))
                DB.commit()
        except Exception as e: print("hook", e)
        self.send_response(200); self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/stats.json" and parse_qs(u.query).get("key", [""])[0] == os.environ.get("ADMIN_KEY", ""):
            n = lambda q: DB.execute(q).fetchone()[0]
            data = {
                "bot": "AntiAge",
                "users": n("select count(*) from users"),
                "quiz_done": n("select count(*) from sent where key='quiz_done'"),
                "categories": dict(DB.execute("select cat, count(*) from users where cat!='' group by cat").fetchall()),
                "orders": n("select count(*) from orders"),
                "orders_sold": n("select count(*) from orders where status=5"),
                "gifts_chosen": n("select count(*) from gifts"),
                "gifts_by_type": dict(DB.execute("select gift, count(*) from gifts group by gift").fetchall()),
                "replenish_pending": n("select count(*) from orders where replenish>0"),
                "replenish_sent": n("select count(*) from sent where key='replenish'"),
                "cross_sent": n("select count(*) from sent where key='cross'"),
                "sources": dict(DB.execute("select coalesce(nullif(src,''),'direct'), count(*) from users group by 1").fetchall()),
                "ts": int(time.time()),
            }
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode()); return
        if u.path == "/admin" and parse_qs(u.query).get("key", [""])[0] == os.environ.get("ADMIN_KEY", ""):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(admin_page().encode()); return
        if u.path == "/client" and parse_qs(u.query).get("key", [""])[0] == os.environ.get("ADMIN_KEY", ""):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(client_page(parse_qs(u.query).get("id", [""])[0]).encode()); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=cron, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Hook).serve_forever()

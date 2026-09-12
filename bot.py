"""Mamulya TG-бот лояльності. Тільки stdlib: long-polling Telegram + HTTP-вебхук SalesDrive + sqlite.
ENV: BOT_TOKEN, SALESDRIVE_KEY, MEDUSA_URL, MEDUSA_KEY, DILA_CODE, BOT_NAME, PORT
"""
import json, os, sqlite3, threading, time, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from rules import infer_stage, gifts_for, LIFECYCLE, STAGE_RULES, GIFTS, TEXTS as T, STAGE_PITCH

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"
BOT_NAME = os.environ.get("BOT_NAME", "mamulya_bot")
DILA_CODE = os.environ.get("DILA_CODE", "667562")
DB = sqlite3.connect(os.environ.get("DB", "bot.db"), check_same_thread=False)
DB.executescript("""
create table if not exists orders(order_id text primary key, phone text, items text, ts real);
create table if not exists customers(chat_id integer primary key, order_id text, phone text, stage text, dob text, created real, picked int default 0);
create table if not exists gifts(chat_id int, gift text, ts real);
create table if not exists coupons(code text primary key, chat_id int, expires real, reminded int default 0);
create table if not exists sent(chat_id int, key text, ts real, primary key(chat_id,key));
create table if not exists posts(id integer primary key autoincrement, ts real, target text, text text);
create table if not exists pool(code text primary key, chat_id int, ts real);
create table if not exists names(phone text primary key, name text);
create table if not exists b2b(phone text primary key);
""")
try: DB.execute("alter table orders add column amount real default 0")
except Exception: pass
try: DB.execute("alter table orders add column store text default ''")
except Exception: pass
try: DB.execute("alter table customers add column store text default ''")
except Exception: pass
try: DB.execute("alter table sent add column ts real")
except Exception: pass
try: DB.execute("alter table customers add column bonus int default 0")
except Exception: pass
try: DB.execute("alter table orders add column status int default 0")
except Exception: pass
try: DB.execute("alter table customers add column src text default ''")
except Exception: pass
DB.execute("update orders set store='Mamulya.lviv' where store='Mamulya'")
DB.execute("update customers set store='Mamulya.lviv' where store='Mamulya'")
DAY = 86400

# ---------- helpers ----------
def tg(method, **kw):
    req = urllib.request.Request(API + method, json.dumps(kw).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

KB = {"keyboard": [[{"text": "🎁 Подарунки"}, {"text": "🎟 Мої купони"}],
                   [{"text": "💎 Мій рівень"}, {"text": "🛍 Добірка для малюка"}],
                   [{"text": "💬 Менеджер"}]],
      "resize_keyboard": True, "is_persistent": True}

def send(chat_id, text, buttons=None):
    kw = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if buttons:  # [[("label","data_or_url"),...]]
        kw["reply_markup"] = {"inline_keyboard": [[
            {"text": t, **({"url": d} if d.startswith("http") else {"callback_data": d})} for t, d in row] for row in buttons]}
    else:
        kw["reply_markup"] = KB  # ponytail: постійна клавіатура на кожному звичайному повідомленні
    return tg("sendMessage", **kw)

def send_photo(chat_id, path, caption):
    # ponytail: multipart руками, щоб не тягнути requests
    b = open(path, "rb").read(); bd = "----mamulya"
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{bd}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n"
            f"--{bd}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
            f"--{bd}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"qr.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + b + f"\r\n--{bd}--\r\n".encode()
    req = urllib.request.Request(API + "sendPhoto", body, {"Content-Type": f"multipart/form-data; boundary={bd}"})
    return json.load(urllib.request.urlopen(req, timeout=30))

def norm_phone(p):
    d = "".join(c for c in str(p) if c.isdigit())
    return "380" + d[-9:] if len(d) >= 9 else d

def create_coupon(chat_id):
    req = urllib.request.Request("https://api.modnamama.ua/api/promos/issue", b"{}",
                                 {"Content-Type": "application/json", "x-secret": os.environ.get("MM_SECRET", "")})
    r = json.load(urllib.request.urlopen(req, timeout=20))
    code = r["code"]; exp = time.time() + 30 * DAY
    DB.execute("insert into coupons values(?,?,?,0)", (code, chat_id, exp)); DB.commit()
    return code, exp

def product_names(resp):
    try: return {o["value"]: o["text"] for o in resp["meta"]["fields"]["products"]["options"]}
    except Exception: return {}

def fetch_order(order_id):
    row = DB.execute("select phone,items,store from orders where order_id=?", (order_id,)).fetchone()
    if row: return row[0], json.loads(row[1]), row[2]
    # ponytail: fallback — тягнемо з SalesDrive API, якщо вебхук не встиг
    if os.environ.get("SALESDRIVE_KEY"):
        try:
            req = urllib.request.Request(f"https://aleyana.salesdrive.me/api/order/list/?filter[id]={order_id}",
                                         headers={"Form-Api-Key": os.environ["SALESDRIVE_KEY"]})
            resp = json.load(urllib.request.urlopen(req, timeout=20))
            ph, it = save_order(resp["data"][0], product_names(resp))
            return ph, it, STORES.get(resp["data"][0].get("sajt"), "")
        except Exception as e: print("salesdrive", e)
    return None, [], ""

STORES = {94: "Mamulya.lviv", 97: "Mamulya.lviv", 134: "Mamulya.lviv", 120: "Modnamama", 150: "Modnamama", 157: "Modnamama", 164: "Znana Mama", 22: "AntiAge"}
# ponytail: рахуємо все живе одразу; DECLINED/Повернення/Скасований/TEST/Видалений випадають самі при зміні статусу (вебхук)

def save_order(o, names=None):
    c0 = (o.get("contacts") or [{}])[0] if isinstance(o.get("contacts"), list) else {}
    phone = norm_phone((c0.get("phone") or [""])[0] if c0 else o.get("phone", ""))
    full = (str(c0.get("fName") or "") + " " + str(c0.get("lName") or "")).strip()
    if phone and full: DB.execute("insert or replace into names values(?,?)", (phone, full))
    if phone and (c0.get("company") or "").strip(): DB.execute("insert or ignore into b2b values(?)", (phone,))
    names = names or {}
    items = [p.get("name") or names.get(p.get("productId"), "") for p in o.get("products", [])]
    store = STORES.get(o.get("sajt"), "")
    DB.execute("insert or replace into orders values(?,?,?,?,?,?,?)", (str(o.get("id")), phone, json.dumps(items, ensure_ascii=False), time.time(), float(o.get("paymentAmount") or 0), store, int(o.get("statusId") or 0))); DB.commit()
    return phone, items

# ---------- gifts ----------
def give(chat_id, gift):
    DB.execute("insert into gifts values(?,?,?)", (chat_id, gift, time.time())); DB.commit()
    if gift == "coupon":
        try:
            code, exp = create_coupon(chat_id)
        except Exception as e:
            print("mm", e)
            DB.execute("delete from gifts where chat_id=? and gift=?", (chat_id, gift)); DB.commit()
            return send(chat_id, "Не вдалось видати код 🙏 Спробуйте інший подарунок або напишіть менеджеру.")
        return send(chat_id, T["gift_coupon"].format(code=code, date=time.strftime("%d.%m", time.localtime(exp))),
                    [[("Обрати на Modnamama", f"https://modnamama.ua/?c={code}")]])
    if gift == "dila":
        send_photo(chat_id, "assets/dila_qr.png", T["gift_dila"].format(code=DILA_CODE))
    elif gift == "znana10":
        body = json.dumps({"prefix": "ZNBOT", "percent": 10, "uses": 1, "days": 30}).encode()
        req = urllib.request.Request("https://znana-stock.onrender.com/api/promos/issue", body,
                                     {"Content-Type": "application/json", "x-secret": os.environ.get("ZNANA_SECRET", "")})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=20))
            code = r["code"]; exp = time.time() + 30 * DAY
            DB.execute("insert into coupons values(?,?,?,0)", (code, chat_id, exp)); DB.commit()
            send(chat_id, T["gift_znana"].format(code=code, date=time.strftime("%d.%m", time.localtime(exp))),
                 [[("На Znana Mama", "https://znanamama.com.ua/khity")]])
        except Exception as e:
            print("znana", e)
            DB.execute("delete from gifts where chat_id=? and gift=?", (chat_id, gift)); DB.commit()
            send(chat_id, "Не вдалось видати код 🙏 Спробуйте інший подарунок або напишіть менеджеру."); return
    elif gift == "antiage":
        code = os.environ.get("ANTIAGE_CODE", "")
        if not code:
            DB.execute("delete from gifts where chat_id=? and gift=?", (chat_id, gift)); DB.commit()
            return send(chat_id, T["gift_mam150_empty"])
        send(chat_id, T["gift_antiage"].format(code=code, desc=os.environ.get("ANTIAGE_DESC", "−10%")),
             [[("На AntiAge Cosmetics", "https://antiagecosmetics.com.ua")]])
    elif gift == "freeship":
        send(chat_id, T["gift_freeship"])
    elif gift == "referral":
        send(chat_id, T["gift_referral"].format(bot=BOT_NAME, chat_id=chat_id))
    elif gift == "mam150":
        # ponytail: Image CMS без API — один статичний код у env; персональні коди, якщо колись зʼявиться API
        code = os.environ.get("MAM150_CODE", "")
        if not code:
            DB.execute("delete from gifts where chat_id=? and gift=?", (chat_id, gift)); DB.commit()
            return send(chat_id, T["gift_mam150_empty"])
        send(chat_id, T["gift_mam150"].format(code=code), [[("На Mamulya", "https://mamulya.lviv.ua")]])

def send_support(chat_id):
    tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
       text=T["support"] + "\n\n📞 Viber: +38 063 632 40 10",
       reply_markup={"inline_keyboard": [
           [{"text": "💬 Telegram", "url": "https://t.me/+380636324010"}],
           [{"text": "💚 WhatsApp", "url": "https://wa.me/380636324010"}],
           [{"text": "❓ Часті питання", "callback_data": "faq"}]]})

def level_of(total):
    lvls = [(25000, 10, "Діамант 💎"), (15000, 7, "VIP 👑"), (9000, 5, "Смарт 🧠"), (4500, 3, "Базовий 💙")]
    cur = next(((t, p, n) for t, p, n in lvls if total >= t), None)
    nxt = ([l for l in reversed(lvls) if total < l[0]] or [None])[0]
    return cur, nxt

def show_menu(chat_id, stage):
    picked = DB.execute("select count(*) from gifts where chat_id=?", (chat_id,)).fetchone()[0]
    limit = 2 + (DB.execute("select coalesce(bonus,0) from customers where chat_id=?", (chat_id,)).fetchone() or [0])[0]
    if picked >= limit:
        send(chat_id, T["gifts_done"])
        row = DB.execute("select stage,dob from customers where chat_id=?", (chat_id,)).fetchone()
        if row and not row[1] and row[0] in ("pregnant", "unknown"):
            send(chat_id, T["ask_dob"])
        return
    options = [g for g in gifts_for(stage) if not DB.execute("select 1 from gifts where chat_id=? and gift=?", (chat_id, g["id"])).fetchone()]
    if not os.environ.get("MM_SECRET"):
        options = [g for g in options if g["id"] != "coupon"]
    if not os.environ.get("ZNANA_SECRET"):
        options = [g for g in options if g["id"] != "znana10"]  # ponytail: без секрета кнопку не показуємо
    if not os.environ.get("MAM150_CODE"):
        options = [g for g in options if g["id"] != "mam150"]  # код не заданий — кнопку ховаємо
    if not os.environ.get("ANTIAGE_CODE"):
        options = [g for g in options if g["id"] != "antiage"]
    send(chat_id, T["menu_header"].format(left=2 - picked), [[(g["label"], "gift:" + g["id"])] for g in options])

# ---------- handlers ----------
def on_start(chat_id, arg):
    if arg.startswith("ref"):
        DB.execute("insert or ignore into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, arg, "", "unknown", time.time())); DB.commit()
        return send(chat_id, T["ref_welcome"], [[("Mamulya", "https://mamulya.lviv.ua"), ("Modnamama −300 ₴", "https://modnamama.ua/?c=FRIEND300")]])
    src = "sms" if arg.isdigit() else (arg or "direct")  # sms / qr / web / migrate / direct
    phone, items, store = fetch_order(arg) if arg.isdigit() else (None, [], "")
    if not phone:
        DB.execute("insert or ignore into customers(chat_id,order_id,phone,stage,created,src) values(?, '', '', 'unknown', ?, ?)", (chat_id, time.time(), src))
        DB.execute("update customers set src=? where chat_id=? and coalesce(src,'')=''", (src, chat_id)); DB.commit()
        # без замовлення в посиланні — просимо підтвердити номер кнопкою Telegram
        return tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
            text=T["ask_phone"],
            reply_markup={"keyboard": [[{"text": "📱 Підтвердити номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True})
    stage = infer_stage(items)
    if phone and DB.execute("select 1 from b2b where phone=?", (phone,)).fetchone(): stage = "b2b"
    old = DB.execute("select order_id, coalesce(bonus,0) from customers where chat_id=?", (chat_id,)).fetchone()
    if old and old[0] and old[0] != arg:
        # повторне замовлення: +1 вибір, купонні подарунки знову доступні (буде новий код)
        DB.execute("update customers set order_id=?, phone=?, stage=?, created=?, store=?, bonus=? where chat_id=?",
                   (arg, phone, stage, time.time(), store, old[1] + 1, chat_id))
        DB.execute("delete from gifts where chat_id=? and gift in ('coupon','znana10')", (chat_id,)); DB.commit()
        total = DB.execute("select coalesce(sum(amount),0) from orders where phone=? and status not in (6,7,13,15,8)", (phone,)).fetchone()[0]
        cur, nxt = level_of(total)
        lvl = f"рівень {cur[2]}, ваша постійна знижка {cur[1]}%" if cur else (f"до знижки {nxt[1]}% лишилось {nxt[0]-total:,.0f} ₴".replace(",", " ") if nxt else "")
        send(chat_id, T["welcome_repeat"].format(store=store or "нашому магазині", total=f"{total:,.0f}".replace(",", " "), lvl=lvl))
        return show_menu(chat_id, stage)
    DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created,store,src) values(?,?,?,?,?,?,?)", (chat_id, arg, phone, stage, time.time(), store, src)); DB.commit()
    send(chat_id, T["welcome_store"].format(store=store) if store else T["welcome"])
    show_menu(chat_id, stage)

ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x}

def stage_from_dob(dob):
    try: d, mth, y = map(int, dob.split("."))
    except Exception: return None
    import datetime
    bd = datetime.date(y, mth, d); today = datetime.date.today()
    if bd > today: return "pregnant"
    months = (today - bd).days / 30.44
    return "m0_3" if months < 3 else "m3_6" if months < 6 else "m6_12" if months < 12 else "lipoland"

def on_text(chat_id, text):
    t = text.strip()
    if t == "🎁 Подарунки":
        row = DB.execute("select stage from customers where chat_id=?", (chat_id,)).fetchone()
        return show_menu(chat_id, row[0] if row else "unknown")
    if t == "🎟 Мої купони":
        rows = DB.execute("select code,expires from coupons where chat_id=? and expires>?", (chat_id, time.time())).fetchall()
        rows += DB.execute("select code,ts+30*86400 from pool where chat_id=?", (chat_id,)).fetchall()
        if not rows: return send(chat_id, T["coupons_none"])
        return send(chat_id, "\n".join(f"🎟 <code>{c}</code> — до {time.strftime('%d.%m', time.localtime(e))}" for c, e in rows))
    if t == "💎 Мій рівень":
        row = DB.execute("select phone from customers where chat_id=?", (chat_id,)).fetchone()
        if not row or not row[0]: return send(chat_id, "Спершу підтвердіть номер телефону: /start")
        # ponytail: сума всіх замовлень без фільтра статусу — скасовані завищать; уточнимо, коли зберігатимемо статус
        total = DB.execute("select coalesce(sum(amount),0) from orders where phone=? and status not in (6,7,13,15,8)", (row[0],)).fetchone()[0]
        cur, nxt = level_of(total)
        msg = f"💎 Ваші покупки в наших магазинах разом: <b>{total:,.0f} ₴</b>\n".replace(",", " ")
        msg += f"Рівень: <b>{cur[2]}</b> — постійна знижка {cur[1]}%\n" if cur else "Рівень: на старті програми 🚀\n"
        if nxt: msg += f"До рівня «{nxt[2]}» ({nxt[1]}%) лишилось {nxt[0]-total:,.0f} ₴".replace(",", " ")
        else: msg += "Це максимальний рівень — вітаємо! 🎉"
        return send(chat_id, msg)
    if t == "🛍 Добірка для малюка":
        row = DB.execute("select stage from customers where chat_id=?", (chat_id,)).fetchone()
        st = row[0] if row and row[0] in LIFECYCLE else "unknown"
        url = next((u for _, k, _, u in LIFECYCLE.get(st, []) if u and "modnamama" in u), "https://modnamama.ua")
        return send(chat_id, STAGE_PITCH.get(st, T["stage_link"]) + "\n\nЗібрали все в одному місці 👇", [[("Відкрити добірку", url)]])
    if t == "💬 Менеджер":
        return send_support(chat_id)
    if chat_id in ADMINS and t.startswith("/demo"):
        st = (t.split() + ["pregnant"])[1]
        if st not in LIFECYCLE: return send(chat_id, "Стадії: " + ", ".join(LIFECYCLE))
        send(chat_id, f"🔎 Демо для стадії «{STAGE_UA.get(st, st)}». Так це побачить клієнт:")
        DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, "demo", "", st, time.time())); DB.execute("delete from gifts where chat_id=?", (chat_id,)); DB.commit()
        send(chat_id, "Дякуємо за замовлення 💗 Ми підготували подарунки — оберіть два, які вам зараз корисні.")
        show_menu(chat_id, st)
        for days, key, text, url in LIFECYCLE[st]:
            send(chat_id, f"⏰ <i>через {days} дн:</i>\n{text}", [[("Подивитись", url)]] if url else None)
        return
    if chat_id in ADMINS and t == "/stats":
        n = lambda q: DB.execute(q).fetchone()[0]
        live = n("select count(*) from coupons where expires>" + str(int(time.time())))
        return send(chat_id, f"👥 Клієнтів у боті: {n('select count(*) from customers')}\n"
            f"🎁 Подарунків видано: {n('select count(*) from gifts')}\n"
            f"🎟 Активних купонів: {live}\n"
            f"🎟 Вільних кодів −150: {n('select count(*) from pool where chat_id is null')}\n"
            f"📦 Замовлень у базі: {n('select count(*) from orders')}")
    if chat_id in ADMINS and t.startswith("/b2b "):
        ph = norm_phone(t.split()[1])
        if DB.execute("select 1 from b2b where phone=?", (ph,)).fetchone():
            DB.execute("delete from b2b where phone=?", (ph,))
            DB.execute("update customers set stage='unknown' where phone=?", (ph,)); DB.commit()
            return send(chat_id, f"🏢 {ph} — позначку «Організація» знято")
        DB.execute("insert or ignore into b2b values(?)", (ph,))
        DB.execute("update customers set stage='b2b' where phone=?", (ph,)); DB.commit()
        return send(chat_id, f"🏢 {ph} — позначено як «Організація»: без вікових розсилок")
    if chat_id in ADMINS and t.startswith("/pool "):
        DB.executemany("insert or ignore into pool(code) values(?)", [(c,) for c in t.split()[1:]]); DB.commit()
        return send(chat_id, f"Додано. У пулі вільних: {DB.execute('select count(*) from pool where chat_id is null').fetchone()[0]}")
    if chat_id in ADMINS and t.startswith("/post"):
        # /post текст — усім; /post m3_6 текст — тільки стадії
        parts = t.split(" ", 2)
        STORE_ARG = {"mamulya": "Mamulya.lviv", "modnamama": "Modnamama", "znana": "Znana Mama"}
        stage = parts[1] if len(parts) > 2 and parts[1] in LIFECYCLE else None
        store = STORE_ARG.get(parts[1].lower()) if len(parts) > 2 else None
        body = parts[2] if (stage or store) else t[5:].strip()
        if stage: ids = [r[0] for r in DB.execute("select chat_id from customers where stage=?", (stage,))]
        elif store: ids = [r[0] for r in DB.execute("select chat_id from customers where store=?", (store,))]
        else: ids = [r[0] for r in DB.execute("select chat_id from customers")]
        cur = DB.execute("insert into posts(ts,target,text) values(?,?,?)", (time.time(), stage or store or "всі", body))
        pid = cur.lastrowid; DB.commit()
        ok = 0
        for cid in ids:
            try:
                send(cid, body); ok += 1
                DB.execute("insert or ignore into sent values(?,?,?)", (cid, f"post:{pid}", time.time()))
            except Exception as e: print("post", e)
        DB.commit()
        return send(chat_id, f"Надіслано {ok}/{len(ids)}")
    if t.lower().strip("!. ") in ("подарунок", "це подарунок", "на подарунок", "купувала на подарунок"):
        DB.execute("update customers set stage='unknown', dob='' where chat_id=?", (chat_id,)); DB.commit()
        return send(chat_id, "Зрозуміла 🎁 Вікових порад не надсилатиму — лише найкорисніше зрідка. Подарунки і купони працюють як завжди!")
    digits = "".join(c for c in t if c.isdigit())
    if len(digits) >= 10 and len(digits) <= 13 and not ("." in t or "," in t):
        return on_contact(chat_id, digits)
    if len(t) == 10 and t[2] == "." and t[5] == ".":
        st = stage_from_dob(t)
        if not st: return send(chat_id, "Не розібрала дату 😅 Напишіть у форматі 15.11.2026")
        DB.execute("update customers set dob=?, stage=? where chat_id=?", (t, st, chat_id)); DB.commit()
        return send(chat_id, T["dob_saved"] + "\n" + STAGE_PITCH.get(st, "").split("\n")[0])
    send_support(chat_id)

def on_contact(chat_id, phone):
    ph = norm_phone(phone)
    row = DB.execute("select order_id,items,store from orders where phone=? order by ts desc limit 1", (ph,)).fetchone()
    if not row:
        DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, "", ph, "unknown", time.time())); DB.commit()
        send(chat_id, T["order_missing"])
        return show_menu(chat_id, "unknown")
    items = json.loads(row[1]); stage = infer_stage(items)
    if DB.execute("select 1 from b2b where phone=?", (ph,)).fetchone(): stage = "b2b"
    DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created,store) values(?,?,?,?,?,?)", (chat_id, row[0], ph, stage, time.time(), row[2] or "")); DB.commit()
    send(chat_id, T["order_found"].format(order_id=row[0], item=items[0][:60]) if items else T["order_missing"])
    show_menu(chat_id, stage)

def on_callback(cb):
    chat_id, data = cb["message"]["chat"]["id"], cb["data"]
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data == "faq":
        row = DB.execute("select coalesce(store,'') from customers where chat_id=?", (chat_id,)).fetchone()
        store = row[0] if row else ""
        return send(chat_id, T.get(f"faq_{store}", T["faq"]))
    if data.startswith("gift:"):
        give(chat_id, data[5:])
        stage = DB.execute("select stage from customers where chat_id=?", (chat_id,)).fetchone()[0]
        show_menu(chat_id, stage)

def poll():
    offset = 0
    while True:
        try:
            for u in tg("getUpdates", offset=offset, timeout=50)["result"]:
                offset = u["update_id"] + 1
                if "callback_query" in u: on_callback(u["callback_query"])
                elif "message" in u and "contact" in u["message"]:
                    m = u["message"]; c = m["contact"]
                    if c.get("user_id") != m["chat"]["id"]:
                        send(m["chat"]["id"], T["wrong_contact"])
                    else: on_contact(m["chat"]["id"], c["phone_number"])
                elif "message" in u and "text" in u["message"]:
                    m = u["message"]; txt = m["text"]
                    if txt.startswith("/start"): on_start(m["chat"]["id"], txt.split(" ", 1)[1] if " " in txt else "")
                    else: on_text(m["chat"]["id"], txt)
        except Exception as e:
            print("poll", e); time.sleep(5)

# ---------- lifecycle cron ----------
def sync_orders(pages, limit=50):
    if not os.environ.get("SALESDRIVE_KEY"): return 0
    tot = 0
    for page in range(1, pages + 1):
        req = urllib.request.Request(f"https://aleyana.salesdrive.me/api/order/list/?limit={limit}&page={page}",
                                     headers={"Form-Api-Key": os.environ["SALESDRIVE_KEY"]})
        for attempt in range(4):
            try:
                resp = json.load(urllib.request.urlopen(req, timeout=30)); break
            except urllib.error.HTTPError as e:
                if e.code != 400 or attempt == 3: raise
                time.sleep(65)  # ponytail: ліміт 10 запитів/хв — чекаємо нове вікно
        names = product_names(resp)
        for o in resp.get("data", []): save_order(o, names); tot += 1
        if len(resp.get("data", [])) < limit: break
        time.sleep(7)  # ponytail: ліміт SalesDrive 10 запитів/хв на order/list
    return tot

def cron():
    while True:
        now = time.time()
        for chat_id, dob, cur_stage in DB.execute("select chat_id,dob,stage from customers where dob is not null and dob!='' and stage!='b2b'"):
            st = stage_from_dob(dob)
            if st and st != cur_stage:
                DB.execute("update customers set stage=? where chat_id=?", (st, chat_id))
        DB.commit()
        for chat_id, stage, created, store in DB.execute("select chat_id,stage,created,coalesce(store,'') from customers where picked>=0"):
            for days, key, text, url in LIFECYCLE.get(stage, []):
                if key == "p3" and store == "Znana Mama": continue  # ponytail: не рекламуємо Znana її ж покупцям
                if now - created >= days * DAY and not DB.execute("select 1 from sent where chat_id=? and key=?", (chat_id, key)).fetchone():
                    try: send(chat_id, text, [[("Подивитись", url)]] if url else None)
                    except Exception as e: print("send", e)
                    DB.execute("insert into sent values(?,?,?)", (chat_id, key, now))
        for code, chat_id, exp in DB.execute("select code,chat_id,expires from coupons where reminded=0 and expires-? < ?", (now, 5 * DAY)):
            try:
                send(chat_id, T["coupon_left"].format(code=code), [[("Modnamama", f"https://modnamama.ua/?c={code}")]])
                DB.execute("insert or ignore into sent values(?,?,?)", (chat_id, f"coupexp:{code}", now))
            except Exception as e: print("remind", e)
            DB.execute("update coupons set reminded=1 where code=?", (code,))
        DB.commit()
        try: sync_orders(1)
        except Exception as e: print("sync", e)
        time.sleep(3600)

# ---------- SalesDrive webhook ----------
HTTPServer.allow_reuse_address = True

class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
        o = body.get("data", body)
        if isinstance(o, list): o = o[0]
        save_order(o, product_names(body))
        self.send_response(200); self.end_headers()
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        authed = qs.get("key", [""])[0] == os.environ.get("ADMIN_KEY", "")
        if u.path == "/sync" and authed:
            pages = int(qs.get("pages", ["1"])[0])
            threading.Thread(target=lambda: print("manual sync:", sync_orders(pages)), daemon=True).start()
            self.send_response(200); self.end_headers(); self.wfile.write(b"sync started"); return
        if u.path == "/segments.csv" and authed:
            self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8"); self.end_headers()
            rows = ["phone;name;total;level;discount;next_level;to_next"]
            for ph, total, lvl, pc, nx, need in base_levels():
                nm = (DB.execute("select name from names where phone=?", (ph,)).fetchone() or [""])[0]
                rows.append(f"{ph};{nm};{total:.0f};{lvl};{pc};{nx};{need:.0f}")
            self.wfile.write("\n".join(rows).encode()); return
        if u.path == "/b2b" and authed:
            ph = qs.get("phone", [""])[0]
            if DB.execute("select 1 from b2b where phone=?", (ph,)).fetchone():
                DB.execute("delete from b2b where phone=?", (ph,))
                DB.execute("update customers set stage='unknown' where phone=?", (ph,))
            else:
                DB.execute("insert or ignore into b2b values(?)", (ph,))
                DB.execute("update customers set stage='b2b' where phone=?", (ph,))
            DB.commit()
            cid = qs.get("id", ["0"])[0]
            self.send_response(302); self.send_header("Location", f"/client?key={os.environ.get('ADMIN_KEY','')}&id={cid}"); self.end_headers(); return
        if u.path == "/near" and authed:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(near_page().encode()); return
        if u.path == "/client" and authed:
            cid = int(qs.get("id", ["0"])[0])
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(client_page(cid).encode()); return
        if u.path != "/admin" or not authed:
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(admin_page().encode())
    def log_message(self, *a): pass

STAGE_UA = {"b2b": "Організація 🏢", "pregnant": "Вагітність/0–1", "m0_3": "0–3 міс", "m3_6": "3–6 міс", "m6_12": "6–12 міс", "lipoland": "Lipoland", "unknown": "Невідомо"}
GIFT_UA = {"dila": "Dila −20%", "coupon": "−300 ₴ Modnamama", "mam150": "−150 ₴ Mamulya.lviv", "freeship": "Безкошт. доставка", "referral": "Реферальна", "znana10": "−10% Znana", "antiage": "AntiAge догляд"}

LVL = [(25000, 10, "Діамант"), (15000, 7, "VIP"), (9000, 5, "Смарт"), (4500, 3, "Базовий")]

def base_levels():
    rows = DB.execute("select phone, sum(amount) s from orders where phone!='' and status not in (6,7,13,15,8) group by phone").fetchall()
    out = []
    for ph, total in rows:
        cur = next(((t, p, n) for t, p, n in LVL if total >= t), (0, 0, "—"))
        nxt = ([l for l in reversed(LVL) if total < l[0]] or [None])[0]
        out.append((ph, total, cur[2], cur[1], nxt[2] if nxt else "", nxt[0] - total if nxt else 0))
    return out

def client_page(cid):
    c = DB.execute("select phone,stage,dob,created,coalesce(store,''),order_id from customers where chat_id=?", (cid,)).fetchone()
    if not c: return "<p>Клієнта не знайдено</p>"
    phone, stage, dob, created, store, oid = c
    name = (DB.execute("select name from names where phone=?", (phone,)).fetchone() or ["—"])[0]
    total = DB.execute("select coalesce(sum(amount),0) from orders where phone=? and status not in (6,7,13,15,8)", (phone,)).fetchone()[0] if phone else 0
    gifts = [GIFT_UA.get(g, g) for (g,) in DB.execute("select gift from gifts where chat_id=?", (cid,))]
    coup = DB.execute("select code, datetime(expires,'unixepoch','localtime') from coupons where chat_id=?", (cid,)).fetchall()
    static_map = {"mam150": ("MAM150_CODE", "Mamulya"), "freeship": (None, "FREESHIP · Mamulya"), "antiage": ("ANTIAGE_CODE", "AntiAge")}
    taken = {g for (g,) in DB.execute("select gift from gifts where chat_id=?", (cid,))}
    statics = []
    if "freeship" in taken: statics.append("<code>FREESHIP</code> (безстроковий · Mamulya.lviv)")
    if "mam150" in taken and os.environ.get("MAM150_CODE"): statics.append(f"<code>{os.environ['MAM150_CODE']}</code> (статичний · Mamulya.lviv)")
    if "antiage" in taken and os.environ.get("ANTIAGE_CODE"): statics.append(f"<code>{os.environ['ANTIAGE_CODE']}</code> (статичний · AntiAge)")
    lif_texts = {k: t for st in LIFECYCLE.values() for _, k, t, _ in st}
    sent_rows = DB.execute("select key, ts from sent where chat_id=? order by coalesce(ts,0)", (cid,)).fetchall()
    hist = []
    for k, ts in sent_rows:
        when = time.strftime("%d.%m %H:%M", time.localtime(ts)) if ts else "—"
        if k.startswith("post:"):
            row = DB.execute("select text from posts where id=?", (k[5:],)).fetchone()
            hist.append((when, "розсилка", (row[0] if row else "?")[:120]))
        elif k.startswith("coupexp:"):
            hist.append((when, "службове", f"⏳ Нагадування: купон {k[8:]} діє ще 5 днів"))
        else:
            hist.append((when, "автонагадування", lif_texts.get(k, k)[:120]))
    plan = []
    done = {k for k, _ in sent_rows}
    for days, k, txt, url in LIFECYCLE.get(stage, []):
        if k in done or (k == "p3" and store == "Znana Mama"): continue
        plan.append((created + days * DAY, txt[:120]))
    for code, exp, rem in DB.execute("select code, expires, reminded from coupons where chat_id=? and expires>?", (cid, time.time())):
        if not rem and f"coupexp:{code}" not in done:
            plan.append((exp - 5 * DAY, f"⏳ Службове: купон {code} діє ще 5 днів"))
    plan = [(time.strftime("%d.%m.%Y", time.localtime(ts)), txt) for ts, txt in sorted(plan)]
    tr = lambda cells: "<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>"
    money = f"{total:,.0f}".replace(",", " ")
    coup_html = "<br>".join([f"<code>{c}</code> до {e[:10]}" for c, e in coup] + statics) or "—"
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Клієнт {cid}</title>
<style>body{{font:14px/1.5 -apple-system,sans-serif;margin:0;background:#FBF7F5;color:#2B2226;padding:24px}}h1{{font-size:20px}}h2{{font-size:15px;margin:22px 0 8px}}
table{{border-collapse:collapse;background:#fff;border:1px solid #E8DCD8;border-radius:10px;width:100%;font-size:13px;max-width:760px}}
td,th{{padding:7px 12px;border-bottom:1px solid #E8DCD8;text-align:left;vertical-align:top}}a{{color:#B8325A}}</style>
<p><a href="javascript:history.back()">← назад до кабінету</a></p>
<h1>{name} · {phone or "без телефону"}</h1>
<table>
{tr(("Магазин", store or "—"))}{tr(("Стадія", STAGE_UA.get(stage, stage) + (f' · <a href="/b2b?key={os.environ.get("ADMIN_KEY","")}&phone={phone}&id={cid}">{"зняти позначку організації" if stage=="b2b" else "позначити як організацію 🏢"}</a>' if phone else "")))}{tr(("Дата народження/ПДР", dob or "—"))}
{tr(("Останнє замовлення", oid or "—"))}{tr(("Сума покупок", money + " ₴"))}
{tr(("У боті з", time.strftime("%d.%m.%Y", time.localtime(created))))}
{tr(("Подарунки", ", ".join(gifts) or "ще не обрано"))}
{tr(("Купони", coup_html))}
</table>
<h2>📨 Вже отримано ({len(hist)})</h2>
<table><tr><th>Коли</th><th>Тип</th><th>Повідомлення</th></tr>{"".join(tr(r) for r in hist) or tr(("—","—","поки нічого"))}</table>
<h2>📅 Заплановано ({len(plan)})</h2>
<table><tr><th>Дата</th><th>Повідомлення</th></tr>{"".join(tr(r) for r in plan) or tr(("—","для цієї стадії все надіслано"))}</table>
<p style="color:#A1939A">Плюс службові: нагадування про купон за 5 днів до кінця дії (якщо є активний купон).</p>"""

def near_page():
    AK = os.environ.get("ADMIN_KEY", "")
    base = base_levels()
    near = sorted([b for b in base if 0 < b[5] <= 1000], key=lambda b: b[5])
    getname = lambda ph: (DB.execute("select name from names where phone=?", (ph,)).fetchone() or ["—"])[0]
    rows = "".join(f"<tr><td>{b[0]}</td><td>{getname(b[0])}</td><td class=n>{b[1]:,.0f} ₴</td><td>{b[2]}</td><td class=n>{b[5]:,.0f} ₴</td><td>{b[4]}</td></tr>".replace(",", " ") for b in near)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Трішки до рівня</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💗</text></svg>">
<style>body{{font:13.5px/1.5 "Golos Text",system-ui,sans-serif;margin:0;background:#F7F2F0;color:#2B2226;padding:24px}}
h1{{font-size:18px}}table{{border-collapse:collapse;background:#fff;border:1px solid #EADFDB;border-radius:12px;width:100%;max-width:860px;font-size:13px}}
td,th{{padding:6px 12px;border-bottom:1px solid #EADFDB;text-align:left}}th{{font-size:10.5px;text-transform:uppercase;color:#A1939A}}
td.n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}a{{color:#B8325A}}</style>
<p><a href="/admin?key={AK}">← кабінет</a></p>
<h1>«Трішки до рівня» ≤1000 ₴ — {len(near)} клієнтів</h1>
<p style=color:#6E5F65;font-size:13px>Найгарячіший сегмент для SMS: маленька сума до постійної знижки. <a href="/segments.csv?key={AK}">Вивантажити CSV ↓</a></p>
<table><tr><th>Телефон</th><th>Імʼя</th><th>Сума</th><th>Рівень</th><th>До наступного</th><th>Наступний</th></tr>{rows}</table>"""

def admin_page():
    AK = os.environ.get("ADMIN_KEY", "")
    q = lambda sql, *a: DB.execute(sql, a).fetchall()
    n = lambda sql: q(sql)[0][0]
    now = time.time()
    LAUNCH = 1789045200  # 10.09.2026 — старт SMS
    orders_since = n(f"select count(*) from orders where ts>={LAUNCH} and status not in (6,7,13,15,8)")
    entered = n(f"select count(*) from customers where created>={LAUNCH}")
    conv = f"{entered/orders_since*100:.0f}%" if orders_since else "—"
    nc = n("select count(*) from customers")
    picks = {r[0]: r[1] for r in q("select cnt, count(*) from (select c.chat_id, (select count(*) from gifts g where g.chat_id=c.chat_id) cnt from customers c) group by cnt")}
    p0 = picks.get(0, 0); p1 = picks.get(1, 0); p2 = sum(v for k, v in picks.items() if k >= 2)
    pickers = nc - p0
    bso = dict(q(f"select coalesce(nullif(store,''),'інше'), count(*) from orders where ts>={LAUNCH} and status not in (6,7,13,15,8) group by 1"))
    bse = dict(q(f"select coalesce(nullif(store,''),'інше'), count(*) from customers where created>={LAUNCH} group by 1"))
    daily_o = dict(q(f"select date(ts,'unixepoch','localtime') d, count(*) from orders where ts>={LAUNCH} and status not in (6,7,13,15,8) group by d"))
    daily_e = dict(q(f"select date(created,'unixepoch','localtime') d, count(*) from customers where created>={LAUNCH} group by d"))
    daily_rows = ""
    for d in sorted(set(daily_o) | set(daily_e), reverse=True)[:14]:
        o, e = daily_o.get(d, 0), daily_e.get(d, 0)
        c = f"{e/o*100:.0f}%" if o else "—"
        daily_rows += f"<tr><td>{d[8:10]}.{d[5:7]}</td><td class=n>{o}</td><td class=n>{e}</td><td class=n>{c}</td></tr>"
    stages = q("select stage,count(*) from customers group by stage order by 2 desc")
    stores = q("select coalesce(nullif(store,''),'інше'), count(*) from orders group by 1 order by 2 desc")
    srcs = q("select coalesce(nullif(src,''),'—'), count(*) from customers group by 1 order by 2 desc")
    gifts = q("select gift,count(*) from gifts group by gift order by 2 desc")
    base = base_levels()
    lvl_counts = {}
    for _, _, name, *_ in base: lvl_counts[name] = lvl_counts.get(name, 0) + 1
    near_all = sorted([b for b in base if 0 < b[5] <= 1000], key=lambda b: b[5])
    near = near_all[:10]
    getname = lambda ph: (DB.execute("select name from names where phone=?", (ph,)).fetchone() or ["—"])[0]
    cptype = lambda pfx: (n(f"select count(*) from coupons where code like '{pfx}%'"), n(f"select count(*) from coupons where code like '{pfx}%' and expires>{now}"))
    mm_all, mm_live = cptype("MMBOT"); zn_all, zn_live = cptype("ZNBOT")
    cpn = q("select c.code, coalesce(nullif(cu.phone,''),c.chat_id), datetime(c.expires,'unixepoch','localtime'), c.expires>?, c.reminded from coupons c left join customers cu on cu.chat_id=c.chat_id order by c.expires desc limit 50", now)
    cust = q("select c.chat_id, coalesce(nullif(c.phone,''),'—'), coalesce((select name from names nm where nm.phone=c.phone),'—'), c.stage, c.dob, datetime(c.created,'unixepoch','localtime'), (select count(*) from gifts g where g.chat_id=c.chat_id), coalesce(nullif(c.src,''),'—'), coalesce(nullif(c.store,''),'—') from customers c order by c.created desc limit 100")
    cards = [("Клієнтів у боті", nc), ("З номером", n("select count(*) from customers where phone!=''")),
             ("Замовлень у базі", n("select count(*) from orders")), ("Подарунків", n("select count(*) from gifts")),
             ("Активних купонів", n(f"select count(*) from coupons where expires>{now}")), ("Нагадувань", n("select count(*) from sent"))]

    def rows(data, names=None, pct_of=None):
        mx = max([r[1] for r in data], default=1) or 1
        tot = pct_of or sum(r[1] for r in data) or 1
        out = ""
        for k, v in data:
            label = (names or {}).get(k, k)
            out += f"<tr><td>{label}</td><td class=n>{v}</td><td class=n>{v/tot*100:.0f}%</td><td class=b><i style=width:{int(v/mx*100)}%></i></td></tr>"
        return out

    SRC_UA = {"sms": "SMS", "qr": "QR з пакування", "web": "сайт", "migrate": "міграція", "direct": "самі знайшли", "—": "—"}
    fun = f"""<tr><td>Замовлень з 10.09</td><td class=n>{orders_since}</td><td></td></tr>
<tr><td><b>Перейшли в бот</b></td><td class=n><b>{entered}</b></td><td class=n><b>{conv}</b></td></tr>"""
    for st in sorted(set(bso) | set(bse), key=lambda x: -bso.get(x, 0)):
        o, e = bso.get(st, 0), bse.get(st, 0)
        c = f"{e/o*100:.0f}%" if o else "—"
        fun += f"<tr class=sub><td>{st}</td><td class=n>{o} → {e}</td><td class=n>{c}</td></tr>"
    fun += f"""<tr><td>Нічого не обрали</td><td class=n>{p0}</td><td class=n>{(p0/nc*100 if nc else 0):.0f}%</td></tr>
<tr><td>Обрали 1</td><td class=n>{p1}</td><td class=n>{(p1/nc*100 if nc else 0):.0f}%</td></tr>
<tr><td>Обрали 2+</td><td class=n>{p2}</td><td class=n>{(p2/nc*100 if nc else 0):.0f}%</td></tr>"""

    coup_sum = f"""<tr><td>🛍 Modnamama −300</td><td class=n>{mm_all}</td><td class=n>акт. {mm_live}</td></tr>
<tr><td>🤍 Znana −10%</td><td class=n>{zn_all}</td><td class=n>акт. {zn_live}</td></tr>
<tr><td>🎟 −150 (натискань)</td><td class=n>{n("select count(*) from gifts where gift='mam150'")}</td><td></td></tr>"""
    coup_list = "".join(f"<tr><td><code>{c}</code></td><td>{who}</td><td class=n>{exp[:10]}</td><td>{'🟢' if live else '⚪'}{' 🔔' if rem else ''}</td></tr>" for c, who, exp, live, rem in cpn)

    lvl_rows = rows([(nm, lvl_counts.get(nm, 0)) for nm in ["Діамант", "VIP", "Смарт", "Базовий", "—"]], pct_of=len(base) or 1)
    near_rows = "".join(f"<tr><td>{b[0]}</td><td>{getname(b[0])}</td><td class=n>{b[1]:,.0f} ₴</td><td class=n>{b[5]:,.0f} ₴ до «{b[4]}»</td></tr>".replace(",", " ") for b in near)
    cust_rows = "".join(f"<tr><td><a href=/client?key={AK}&id={r[0]}>{r[2] if r[2]!='—' else r[0]}</a></td><td>{r[1]}</td><td>{r[8]}</td><td>{STAGE_UA.get(r[3], r[3])}</td><td>{r[4] or '—'}</td><td>{SRC_UA.get(r[7], r[7])}</td><td class=n>{r[5][5:16]}</td><td class=n>{r[6]}</td></tr>" for r in cust)

    cfg_stage = "".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td>{', '.join(kws)}</td></tr>" for st, kws in STAGE_RULES)
    cfg_gifts = "".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td>{' → '.join(g['label'] for g in gs)}</td></tr>" for st, gs in GIFTS.items())
    cfg_life = "".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td class=n>+{d}д</td><td>{txt}</td><td>{(u or '—').replace('https://','')}</td></tr>" for st, items in LIFECYCLE.items() for d, k, txt, u in items)
    cfg_texts = "".join(f"<tr><td><code>{k}</code></td><td>{v.replace(chr(10),'<br>')}</td></tr>" for k, v in T.items())

    def panel(title, inner, wide=False, extra=""):
        return f'<section class="p{" wide" if wide else ""}"><h2>{title}{extra}</h2>{inner}</section>'
    def det(title, inner):
        return f'<details class="p wide"><summary>{title}</summary>{inner}</details>'

    return f"""<!doctype html><html lang=uk><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Mamulya Bot — кабінет</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💗</text></svg>">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700&display=swap">
<style>
:root{{--bg:#F7F2F0;--card:#FFF;--line:#EADFDB;--ink:#2B2226;--ink2:#6E5F65;--ink3:#A1939A;--acc:#B8325A;--acc-dim:#F8E4EA}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13.5px/1.45 "Golos Text",system-ui,sans-serif;padding:20px}}
.top{{display:flex;align-items:baseline;gap:12px;max-width:1100px;margin:0 auto 14px}}
h1{{font-size:19px;font-weight:700;margin:0}}.upd{{color:var(--ink3);font-size:12px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;max-width:1100px;margin:0 auto 14px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px}}
.tile b{{display:block;font-size:20px;font-variant-numeric:tabular-nums}}.tile span{{font-size:10.5px;color:var(--ink3);text-transform:uppercase;letter-spacing:.04em}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;max-width:1100px;margin:0 auto}}
.p{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow-x:auto}}
.p.wide{{grid-column:1/-1}}
h2{{font-size:13px;font-weight:600;margin:0 0 8px;color:var(--ink2)}}
h2 small{{font-weight:400;color:var(--ink3)}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
td,th{{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
tr:last-child td{{border-bottom:0}}th{{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink3)}}
td.n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
td.b{{width:34%}}td.b i{{display:block;height:6px;background:var(--acc);border-radius:3px;min-width:2px}}
tr.sub td{{color:var(--ink2);font-size:12px;padding-left:20px}}
a{{color:var(--acc);text-decoration:none}}a:hover{{text-decoration:underline}}
code{{font-size:11.5px;background:var(--acc-dim);padding:0 4px;border-radius:4px}}
details.p summary{{cursor:pointer;font-size:13px;font-weight:600;color:var(--ink2)}}
details.p[open] summary{{margin-bottom:8px}}
</style>
<div class=top><h1>💗 Mamulya Bot</h1><span class=upd>оновлено {time.strftime("%d.%m %H:%M")}</span>
<span class=upd style=margin-left:auto><a href="/segments.csv?key={AK}">CSV сегментів ↓</a></span></div>
<div class=tiles>{"".join(f"<div class=tile><b>{v}</b><span>{k}</span></div>" for k, v in cards)}</div>
<div class=grid>
{panel("Воронка · SMS → бот → подарунки", f"<table>{fun}</table>")}
{panel("Звідки прийшли в бот", f"<table>{rows(srcs, SRC_UA)}</table>")}
{panel("По днях", f"<table><tr><th>Дата</th><th>Замовл.</th><th>У бот</th><th>Конв.</th></tr>{daily_rows}</table>", extra=" <small>останні 14 днів</small>")}
{panel("Обрані подарунки", f"<table>{rows(gifts, GIFT_UA, pct_of=pickers or 1)}</table>", extra=f" <small>% від {pickers} з подарунками</small>")}
{panel("Купони", f"<table>{coup_sum}</table>")}
{panel("Замовлення за магазинами", f"<table>{rows(stores)}</table>")}
{panel("Клієнти за стадіями", f"<table>{rows(stages, STAGE_UA)}</table>")}
{panel("Рівні бази", f"<table>{lvl_rows}</table>", extra=f" <small>{len(base)} клієнтів з покупками</small>")}
{panel("«Трішки до рівня» ≤1000 ₴", f"<table><tr><th>Телефон</th><th>Імʼя</th><th>Сума</th><th>До рівня</th></tr>{near_rows}</table><p style=margin:8px 0 0;font-size:12.5px><a href=/near?key={AK}>Відкрити всіх {len(near_all)} →</a></p>", extra=f" <small>топ-10 з {len(near_all)}</small>")}
{panel("Останні клієнти", f"<table><tr><th>Клієнт</th><th>Телефон</th><th>Магазин</th><th>Стадія</th><th>ДН/ПДР</th><th>Джерело</th><th>Зайшла</th><th>🎁</th></tr>{cust_rows}</table>", wide=True)}
{det("🎟 Останні видані купони", f"<table><tr><th>Код</th><th>Кому</th><th>До</th><th></th></tr>{coup_list or '<tr><td>поки нема</td></tr>'}</table>")}
{det("⚙️ Стадія ← товар", f"<table>{cfg_stage}</table>")}
{det("⚙️ Подарунки за стадією", f"<table>{cfg_gifts}</table>")}
{det("⚙️ Автонагадування", f"<table><tr><th>Стадія</th><th>Коли</th><th>Текст</th><th>Куди</th></tr>{cfg_life}</table><p style=color:var(--ink3);font-size:12px>Плюс службові: нагадування про купон за 5 днів до кінця. Тексти правляться у rules.py. Демо: /demo стадія в боті.</p>")}
{det("⚙️ Усі тексти повідомлень", f"<table>{cfg_texts}</table>")}
</div></html>"""

if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=cron, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Hook).serve_forever()

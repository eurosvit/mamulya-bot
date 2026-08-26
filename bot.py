"""Mamulya TG-бот лояльності. Тільки stdlib: long-polling Telegram + HTTP-вебхук SalesDrive + sqlite.
ENV: BOT_TOKEN, SALESDRIVE_KEY, MEDUSA_URL, MEDUSA_KEY, DILA_CODE, BOT_NAME, PORT
"""
import json, os, sqlite3, threading, time, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from rules import infer_stage, gifts_for, LIFECYCLE, STAGE_RULES, GIFTS, TEXTS as T

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
create table if not exists sent(chat_id int, key text, primary key(chat_id,key));
create table if not exists pool(code text primary key, chat_id int, ts real);
create table if not exists names(phone text primary key, name text);
""")
DAY = 86400

# ---------- helpers ----------
def tg(method, **kw):
    req = urllib.request.Request(API + method, json.dumps(kw).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

KB = {"keyboard": [[{"text": "🎁 Подарунки"}, {"text": "🎟 Мої купони"}],
                   [{"text": "🛍 Добірка для малюка"}, {"text": "💬 Менеджер"}]],
      "resize_keyboard": True, "is_persistent": True}

def send(chat_id, text, buttons=None):
    kw = dict(chat_id=chat_id, text=text, parse_mode="HTML")
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

def create_coupon(chat_id, pct=10, days=30):
    code = f"MAM{chat_id % 100000:05d}{int(time.time()) % 1000:03d}"
    exp = time.time() + days * DAY
    # ponytail: Medusa Admin API — POST /admin/promotions; без MEDUSA_URL просто пишемо код локально
    if os.environ.get("MEDUSA_URL"):
        body = {"code": code, "type": "standard", "application_method": {"type": "percentage", "value": pct, "target_type": "order"},
                "campaign": {"name": code, "campaign_identifier": code, "ends_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))}}
        req = urllib.request.Request(os.environ["MEDUSA_URL"] + "/admin/promotions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "x-medusa-access-token": os.environ.get("MEDUSA_KEY", "")})
        try: urllib.request.urlopen(req, timeout=20)
        except Exception as e: print("medusa", e)
    DB.execute("insert into coupons values(?,?,?,0)", (code, chat_id, exp)); DB.commit()
    return code, exp

def product_names(resp):
    try: return {o["value"]: o["text"] for o in resp["meta"]["fields"]["products"]["options"]}
    except Exception: return {}

def fetch_order(order_id):
    row = DB.execute("select phone,items from orders where order_id=?", (order_id,)).fetchone()
    if row: return row[0], json.loads(row[1])
    # ponytail: fallback — тягнемо з SalesDrive API, якщо вебхук не встиг
    if os.environ.get("SALESDRIVE_KEY"):
        try:
            req = urllib.request.Request(f"https://aleyana.salesdrive.me/api/order/list/?filter[id]={order_id}",
                                         headers={"Form-Api-Key": os.environ["SALESDRIVE_KEY"]})
            resp = json.load(urllib.request.urlopen(req, timeout=20))
            return save_order(resp["data"][0], product_names(resp))
        except Exception as e: print("salesdrive", e)
    return None, []

def save_order(o, names=None):
    c0 = (o.get("contacts") or [{}])[0] if isinstance(o.get("contacts"), list) else {}
    phone = norm_phone((c0.get("phone") or [""])[0] if c0 else o.get("phone", ""))
    full = (str(c0.get("fName") or "") + " " + str(c0.get("lName") or "")).strip()
    if phone and full: DB.execute("insert or replace into names values(?,?)", (phone, full))
    names = names or {}
    items = [p.get("name") or names.get(p.get("productId"), "") for p in o.get("products", [])]
    DB.execute("insert or replace into orders values(?,?,?,?)", (str(o.get("id")), phone, json.dumps(items, ensure_ascii=False), time.time())); DB.commit()
    return phone, items

# ---------- gifts ----------
def give(chat_id, gift):
    DB.execute("insert into gifts values(?,?,?)", (chat_id, gift, time.time())); DB.commit()
    if gift == "dila":
        send_photo(chat_id, "assets/dila_qr.png", T["gift_dila"].format(code=DILA_CODE))
    elif gift == "coupon":
        code, exp = create_coupon(chat_id)
        send(chat_id, T["gift_coupon"].format(code=code, date=time.strftime("%d.%m", time.localtime(exp))),
             [[("Обрати на Modnamama", f"https://modnamama.ua/?c={code}")]])
    elif gift == "freeship":
        send(chat_id, T["gift_freeship"])
    elif gift == "referral":
        send(chat_id, T["gift_referral"].format(bot=BOT_NAME, chat_id=chat_id))
    elif gift == "mam150":
        # ponytail: Image CMS без API — пул кодів створюється руками в адмінці, бот роздає по одному
        row = DB.execute("select code from pool where chat_id is null limit 1").fetchone()
        if not row: return send(chat_id, T["gift_mam150_empty"])
        DB.execute("update pool set chat_id=?, ts=? where code=?", (chat_id, time.time(), row[0])); DB.commit()
        send(chat_id, T["gift_mam150"].format(code=row[0]), [[("На Mamulya", "https://mamulya.lviv.ua")]])

def send_support(chat_id):
    tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
       text=T["support"],
       reply_markup={"inline_keyboard": [
           [{"text": "💬 Telegram", "url": "https://t.me/+380636324010"}],
           [{"text": "📞 Viber", "url": "viber://chat?number=%2B380636324010"}],
           [{"text": "💚 WhatsApp", "url": "https://wa.me/380636324010"}],
           [{"text": "❓ Часті питання", "callback_data": "faq"}]]})

def show_menu(chat_id, stage):
    picked = DB.execute("select count(*) from gifts where chat_id=?", (chat_id,)).fetchone()[0]
    if picked >= 2:
        send(chat_id, T["gifts_done"])
        row = DB.execute("select stage,dob from customers where chat_id=?", (chat_id,)).fetchone()
        if row and not row[1] and row[0] in ("pregnant", "unknown"):
            send(chat_id, T["ask_dob"])
        return
    options = [g for g in gifts_for(stage) if not DB.execute("select 1 from gifts where chat_id=? and gift=?", (chat_id, g["id"])).fetchone()]
    send(chat_id, T["menu_header"].format(left=2 - picked), [[(g["label"], "gift:" + g["id"])] for g in options])

# ---------- handlers ----------
def on_start(chat_id, arg):
    if arg.startswith("ref"):
        DB.execute("insert or ignore into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, arg, "", "unknown", time.time())); DB.commit()
        return send(chat_id, T["ref_welcome"], [[("Mamulya", "https://mamulya.lviv.ua"), ("Modnamama −10%", "https://modnamama.ua/?c=FRIEND10")]])
    phone, items = fetch_order(arg) if arg and arg != "web" else (None, [])
    if not phone:
        # без замовлення в посиланні — просимо підтвердити номер кнопкою Telegram
        return tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
            text=T["ask_phone"],
            reply_markup={"keyboard": [[{"text": "📱 Підтвердити номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True})
    stage = infer_stage(items)
    DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, arg, phone, stage, time.time())); DB.commit()
    send(chat_id, T["welcome"])
    show_menu(chat_id, stage)

ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x}

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
    if t == "🛍 Добірка для малюка":
        row = DB.execute("select stage from customers where chat_id=?", (chat_id,)).fetchone()
        st = row[0] if row and row[0] in LIFECYCLE else "unknown"
        url = (LIFECYCLE[st][0][3] if LIFECYCLE.get(st) else None) or "https://modnamama.ua"
        return send(chat_id, T["stage_link"], [[("Відкрити", url)]])
    if t == "💬 Менеджер":
        return send_support(chat_id)
    if chat_id in ADMINS and t.startswith("/demo"):
        st = (t.split() + ["pregnant"])[1]
        if st not in LIFECYCLE: return send(chat_id, "Стадії: " + ", ".join(LIFECYCLE))
        send(chat_id, f"🔎 Демо для стадії «{STAGE_UA.get(st, st)}». Так це побачить клієнт:")
        DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, "demo", "", st, time.time())); DB.execute("delete from gifts where chat_id=?", (chat_id,)); DB.commit()
        send(chat_id, "Дякуємо за замовлення 💛 Ми підготували подарунки — оберіть два, які вам зараз корисні.")
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
    if chat_id in ADMINS and t.startswith("/pool "):
        DB.executemany("insert or ignore into pool(code) values(?)", [(c,) for c in t.split()[1:]]); DB.commit()
        return send(chat_id, f"Додано. У пулі вільних: {DB.execute('select count(*) from pool where chat_id is null').fetchone()[0]}")
    if chat_id in ADMINS and t.startswith("/post"):
        # /post текст — усім; /post m3_6 текст — тільки стадії
        parts = t.split(" ", 2); stage = parts[1] if len(parts) > 2 and parts[1] in LIFECYCLE else None
        body = parts[2] if stage else t[5:].strip()
        ids = [r[0] for r in DB.execute("select chat_id from customers" + (" where stage=?" if stage else ""), (stage,) if stage else ())]
        ok = 0
        for cid in ids:
            try: send(cid, body); ok += 1
            except Exception as e: print("post", e)
        return send(chat_id, f"Надіслано {ok}/{len(ids)}")
    if len(t) == 10 and t[2] == "." and t[5] == ".":
        DB.execute("update customers set dob=? where chat_id=?", (t, chat_id)); DB.commit()
        return send(chat_id, T["dob_saved"])
    send_support(chat_id)

def on_contact(chat_id, phone):
    ph = norm_phone(phone)
    row = DB.execute("select order_id,items from orders where phone=? order by ts desc limit 1", (ph,)).fetchone()
    if not row:
        DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, "", ph, "unknown", time.time())); DB.commit()
        send(chat_id, T["order_missing"])
        return show_menu(chat_id, "unknown")
    items = json.loads(row[1]); stage = infer_stage(items)
    DB.execute("insert or replace into customers(chat_id,order_id,phone,stage,created) values(?,?,?,?,?)", (chat_id, row[0], ph, stage, time.time())); DB.commit()
    send(chat_id, T["order_found"].format(order_id=row[0], item=items[0][:60]) if items else T["order_missing"])
    show_menu(chat_id, stage)

def on_callback(cb):
    chat_id, data = cb["message"]["chat"]["id"], cb["data"]
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data == "faq":
        return send(chat_id, T["faq"])
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
        for chat_id, stage, created in DB.execute("select chat_id,stage,created from customers where picked>=0"):
            for days, key, text, url in LIFECYCLE.get(stage, []):
                if now - created >= days * DAY and not DB.execute("select 1 from sent where chat_id=? and key=?", (chat_id, key)).fetchone():
                    try: send(chat_id, text, [[("Подивитись", url)]] if url else None)
                    except Exception as e: print("send", e)
                    DB.execute("insert into sent values(?,?)", (chat_id, key))
        for code, chat_id, exp in DB.execute("select code,chat_id,expires from coupons where reminded=0 and expires-? < ?", (now, 5 * DAY)):
            try: send(chat_id, T["coupon_left"].format(code=code), [[("Modnamama", f"https://modnamama.ua/?c={code}")]])
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
        if u.path != "/admin" or not authed:
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(admin_page().encode())
    def log_message(self, *a): pass

STAGE_UA = {"pregnant": "Вагітність/0–1", "m0_3": "0–3 міс", "m3_6": "3–6 міс", "m6_12": "6–12 міс", "lipoland": "Lipoland", "unknown": "Невідомо"}
GIFT_UA = {"dila": "Dila −20%", "coupon": "−10% Modnamama", "mam150": "−150 ₴ Mamulya", "freeship": "Безкошт. доставка", "referral": "Реферальна"}

def admin_page():
    q = lambda sql, *a: DB.execute(sql, a).fetchall()
    n = lambda sql: q(sql)[0][0]
    now = time.time()
    def bar(rows, names):
        mx = max([r[1] for r in rows], default=1) or 1
        return "".join(f"<tr><td>{names.get(r[0], r[0])}</td><td class=n>{r[1]}</td>"
                       f"<td class=b><i style=width:{int(r[1]/mx*100)}%></i></td></tr>" for r in rows)
    stages = q("select stage,count(*) from customers group by stage order by 2 desc")
    gifts = q("select gift,count(*) from gifts group by gift order by 2 desc")
    cust = q("select c.chat_id, coalesce(nullif(c.phone,''),'—'), coalesce((select name from names n where n.phone=c.phone),'—'), c.stage, c.dob, datetime(c.created,'unixepoch','localtime'), (select count(*) from gifts g where g.chat_id=c.chat_id) from customers c order by c.created desc limit 100")
    cards = [("Клієнтів у боті", n("select count(*) from customers")),
             ("З підтвердженим номером", n("select count(*) from customers where phone!=''")),
             ("Замовлень у базі", n("select count(*) from orders")),
             ("Подарунків видано", n("select count(*) from gifts")),
             ("Активних купонів", n(f"select count(*) from coupons where expires>{now}")),
             ("Вільних кодів −150", n("select count(*) from pool where chat_id is null")),
             ("Нагадувань надіслано", n("select count(*) from sent"))]
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Mamulya Bot — кабінет</title><style>
body{{font:14px/1.5 -apple-system,sans-serif;margin:0;background:#FBF7F5;color:#2B2226;padding:24px}}
h1{{font-size:22px}}h2{{font-size:16px;margin:28px 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.card{{background:#fff;border:1px solid #E8DCD8;border-radius:10px;padding:12px 16px}}
.card b{{font-size:26px;display:block}}.card span{{font-size:11px;color:#A1939A;text-transform:uppercase}}
table{{border-collapse:collapse;background:#fff;border:1px solid #E8DCD8;border-radius:10px;width:100%;font-size:13px}}
td,th{{padding:7px 12px;border-bottom:1px solid #E8DCD8;text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td.b{{width:40%}}td.b i{{display:block;height:8px;background:#B8325A;border-radius:4px}}
</style>
<h1>Mamulya Bot — кабінет</h1>
<p style=color:#6E5F65>Оновлено {time.strftime("%d.%m %H:%M")} · автооновлення при перезавантаженні сторінки</p>
<div class=cards>{"".join(f"<div class=card><b>{v}</b><span>{k}</span></div>" for k, v in cards)}</div>
<h2>Клієнти за стадіями</h2><table>{bar(stages, STAGE_UA)}</table>
<h2>Обрані подарунки</h2><table>{bar(gifts, GIFT_UA)}</table>
<h2>Що налаштовано: стадія ← товар</h2>
<table><tr><th>Стадія</th><th>Ключові слова в назві товару</th></tr>
{"".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td>{', '.join(kws)}</td></tr>" for st, kws in STAGE_RULES)}</table>
<h2>Що налаштовано: подарунки за стадією (порядок у меню)</h2>
<table>{"".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td>{' → '.join(g['label'] for g in gs)}</td></tr>" for st, gs in GIFTS.items())}</table>
<h2>Усі тексти повідомлень (rules.py → TEXTS)</h2>
<table><tr><th>Ключ</th><th>Текст</th></tr>
{"".join(f"<tr><td><code>{k}</code></td><td>{v.replace(chr(10),'<br>')}</td></tr>" for k, v in T.items())}</table>
<h2>Що налаштовано: автонагадування</h2>
<table><tr><th>Стадія</th><th>Коли</th><th>Текст</th><th>Посилання</th></tr>
{"".join(f"<tr><td>{STAGE_UA.get(st, st)}</td><td class=n>+{d} дн</td><td>{txt}</td><td>{(u or '—').replace('https://','')}</td></tr>" for st, items in LIFECYCLE.items() for d, k, txt, u in items)}</table>
<p style=color:#6E5F65>Плюс службові: нагадування про купон за 5 днів до кінця. Змінюється все у файлі rules.py. Побачити очима клієнта: команда <b>/demo стадія</b> в боті.</p>
<h2>Останні клієнти (100)</h2>
<table><tr><th>chat_id</th><th>Телефон</th><th>Імʼя</th><th>Стадія</th><th>Дата нар.</th><th>Зайшов у бот</th><th>Подарунків</th></tr>
{"".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{STAGE_UA.get(r[3], r[3])}</td><td>{r[4] or '—'}</td><td>{r[5]}</td><td class=n>{r[6]}</td></tr>" for r in cust)}</table>"""

if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=cron, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Hook).serve_forever()

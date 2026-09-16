# -*- coding: utf-8 -*-
"""AntiAge Cosmetics бот (@AntiAgeCosmetics_Bot) — квіз-підбір догляду, перенесений із SendPulse.
Тільки stdlib. ENV: BOT_TOKEN, ADMIN_IDS, ADMIN_KEY, PEER_ADMIN (URL кабінету Mamulya), DB, PORT
"""
import json, os, sqlite3, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x}
DB = sqlite3.connect(os.environ.get("DB", "antiage.db"), check_same_thread=False)
DB.executescript("""
create table if not exists users(chat_id integer primary key, src text default '', cat text default '', concern text default '', priority text default '', created real);
create table if not exists sent(chat_id int, key text, ts real, primary key(chat_id,key));
create table if not exists posts(id integer primary key autoincrement, ts real, text text);
""")
DAY = 86400
SITE = "https://antiagecosmetics.com.ua"
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

def send(chat_id, text, buttons=None):
    kw = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if buttons:
        kw["reply_markup"] = {"inline_keyboard": [[
            {"text": t, **({"url": d} if d.startswith("http") else {"callback_data": d})} for t, d in row] for row in buttons]}
    else:
        kw["reply_markup"] = {"keyboard": [[{"text": "🎁 Мій промокод"}, {"text": "🛍 Каталог"}], [{"text": "🔄 Пройти підбір заново"}, {"text": "💬 Підтримка"}]],
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
    start_quiz(chat_id)

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
    if t == "💬 Підтримка":
        return send(chat_id, "Напишіть нам — підкажемо із засобом і складом 💛\n📩 Instagram/сайт: antiagecosmetics.com.ua\n🕐 Пн–Пт 10:00–17:00")
    send(chat_id, "Натисніть кнопку внизу — або «🔄 Пройти підбір заново», щоб отримати рекомендації 😊")

def poll():
    offset = 0
    while True:
        try:
            for u in tg("getUpdates", offset=offset, timeout=50)["result"]:
                offset = u["update_id"] + 1
                if "callback_query" in u: on_callback(u["callback_query"])
                elif "message" in u and "text" in u["message"]:
                    m = u["message"]; txt = m["text"]
                    if txt.startswith("/start"): on_start(m["chat"]["id"], txt.split(" ", 1)[1] if " " in txt else "")
                    else: on_text(m["chat"]["id"], txt)
        except Exception as e:
            print("poll", e); time.sleep(5)

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
        DB.commit()
        time.sleep(3600)

def admin_page():
    q = lambda sql: DB.execute(sql).fetchall()
    n = lambda sql: q(sql)[0][0]
    CAT = {"face": "Обличчя", "body": "Тіло", "hair": "Волосся", "intimate": "Інтимний", "complex": "Комплексний", "": "—"}
    cats = q("select cat, count(*) from users group by cat order by 2 desc")
    srcs = q("select coalesce(nullif(src,''),'—'), count(*) from users group by 1 order by 2 desc")
    total = n("select count(*) from users"); done = n("select count(*) from sent where key='quiz_done'")
    peer = os.environ.get("PEER_ADMIN", "")
    rows = lambda data, names: "".join(f"<tr><td>{names.get(k, k)}</td><td class=n>{v}</td><td class=n>{(v/total*100 if total else 0):.0f}%</td></tr>" for k, v in data)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AntiAge Bot — кабінет</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌿</text></svg>">
<style>body{{font:13.5px/1.5 "Golos Text",system-ui,sans-serif;margin:0;background:#F2F5F1;color:#22301F;padding:20px}}
h1{{font-size:19px}}h2{{font-size:13px;color:#5F7057;margin:18px 0 8px}}
.tile{{display:inline-block;background:#fff;border:1px solid #DFE7DB;border-radius:10px;padding:8px 14px;margin:0 8px 8px 0}}
.tile b{{display:block;font-size:20px}}.tile span{{font-size:10.5px;color:#93A28C;text-transform:uppercase}}
table{{border-collapse:collapse;background:#fff;border:1px solid #DFE7DB;border-radius:10px;width:100%;max-width:560px;font-size:12.5px}}
td{{padding:5px 10px;border-bottom:1px solid #DFE7DB}}td.n{{text-align:right}}a{{color:#4E7A63}}</style>
<h1>🌿 AntiAge Bot {"· <a href='" + peer + "'>💗 кабінет Mamulya</a>" if peer else ""}</h1>
<div><span class=tile><b>{total}</b><span>у боті</span></span>
<span class=tile><b>{done}</b><span>пройшли квіз ({(done/total*100 if total else 0):.0f}%)</span></span></div>
<h2>Категорії інтересу</h2><table>{rows(cats, CAT)}</table>
<h2>Звідки прийшли</h2><table>{rows(srcs, {"promo": "попап сайту", "direct": "самі знайшли", "qr": "QR"})}</table>"""

HTTPServer.allow_reuse_address = True
class Hook(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/admin" and parse_qs(u.query).get("key", [""])[0] == os.environ.get("ADMIN_KEY", ""):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(admin_page().encode()); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=cron, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Hook).serve_forever()

// Cloudflare Worker: завжди-онлайн редирект кліків розсилок Mamulya.
// Клієнт ніколи не залежить від рестартів бота; клік логиться у бота best-effort (у фоні).
// Деплой: Cloudflare → Workers & Pages → Create Worker → вставити цей код → Deploy.
// Потім на Render (mamulya-bot) додати env CLICK_BASE = <URL цього воркера>.

const ALLOWED = ["mamulya.lviv.ua", "modnamama.ua", "znanamama.com.ua", "antiagecosmetics.com.ua", "lipoland.fun"];
const BOT = "https://mamulya-bot.onrender.com"; // куди логити клік

export default {
  async fetch(request, ctx_env, ctx) {
    const url = new URL(request.url);
    const p = url.searchParams.get("p") || "0";
    const c = url.searchParams.get("c") || "0";
    const dest = url.searchParams.get("u") || "";

    // захист від відкритого редиректу: лише наші домени
    let target = "https://mamulya.lviv.ua";
    try {
      const d = new URL(dest);
      if ((d.protocol === "https:" || d.protocol === "http:") && ALLOWED.includes(d.hostname)) target = dest;
    } catch (e) {}

    // лог кліку у фоні — НІКОЛИ не блокує редирект клієнта
    ctx.waitUntil(
      fetch(`${BOT}/clicklog?p=${encodeURIComponent(p)}&c=${encodeURIComponent(c)}`).catch(() => {})
    );

    return Response.redirect(target, 302);
  },
};

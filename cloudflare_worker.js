// Cloudflare Worker - Proxy AI untuk Gold Signal Bot
// Hanya menerima request dengan API key yang benar (aman, bukan proxy terbuka)

const ALLOWED_KEY = "sk-4zICkuMwLhkD190yKGNFklmb8DD3sfweivGR0WiCIUesMjCV";
const UPSTREAM = "https://tabitoken.com";

export default {
  async fetch(request) {
    // hanya izinkan POST ke /v1/*
    const url = new URL(request.url);
    if (request.method !== "POST" || !url.pathname.startsWith("/v1/")) {
      return new Response("Not found", { status: 404 });
    }
    // validasi API key
    const auth = request.headers.get("Authorization") || "";
    if (auth !== "Bearer " + ALLOWED_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }
    // teruskan ke upstream (jaringan Cloudflare internal -> tidak diblok)
    const headers = new Headers(request.headers);
    headers.delete("Host");
    headers.delete("Origin");
    headers.delete("Referer");
    headers.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36");
    headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");

    const resp = await fetch(UPSTREAM + url.pathname, {
      method: "POST",
      headers: headers,
      body: request.body,
    });
    return new Response(resp.body, {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};

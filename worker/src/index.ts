export interface Env {
  DB: D1Database;
  MEDIA: R2Bucket;

  META_CLIENT_ID?: string;
  META_CLIENT_SECRET?: string;
  META_REDIRECT_URI?: string;

  X_CLIENT_ID?: string;
  X_CLIENT_SECRET?: string;
  X_REDIRECT_URI?: string;

  GOOGLE_CLIENT_ID?: string;
  GOOGLE_CLIENT_SECRET?: string;
  YOUTUBE_REDIRECT_URI?: string;

  TIKTOK_CLIENT_KEY?: string;
  TIKTOK_CLIENT_SECRET?: string;
  TIKTOK_REDIRECT_URI?: string;

  PINTEREST_APP_ID?: string;
  PINTEREST_APP_SECRET?: string;
  PINTEREST_REDIRECT_URI?: string;

  REDDIT_CLIENT_ID?: string;
  REDDIT_CLIENT_SECRET?: string;
  REDDIT_REDIRECT_URI?: string;

  TELEGRAM_BOT_TOKEN?: string;

  NBSA_FRONTEND_URL?: string;
  PUBLIC_MEDIA_BASE_URL?: string;
}

const json = (data: unknown, status = 200, origin = "*") =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
    }
  });

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": env.NBSA_FRONTEND_URL || "*",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
          "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        }
      });
    }

    if (url.pathname === "/health") {
      return json({
        status: "ok",
        service: "NAYEM BOSS SOCIAL AUTOMATION API",
        runtime: "cloudflare-worker"
      });
    }

    if (url.pathname === "/api/providers") {
      return json({
        facebook: !!(env.META_CLIENT_ID && env.META_CLIENT_SECRET),
        instagram: !!(env.META_CLIENT_ID && env.META_CLIENT_SECRET),
        telegram: !!env.TELEGRAM_BOT_TOKEN,
        x: !!(env.X_CLIENT_ID && env.X_CLIENT_SECRET),
        youtube: !!(env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET),
        tiktok: !!(env.TIKTOK_CLIENT_KEY && env.TIKTOK_CLIENT_SECRET),
        pinterest: !!(env.PINTEREST_APP_ID && env.PINTEREST_APP_SECRET),
        reddit: !!(env.REDDIT_CLIENT_ID && env.REDDIT_CLIENT_SECRET)
      });
    }

    return json({
      status: "ok",
      message: "NBSA production API scaffold is online"
    });
  },

  async scheduled(
    _controller: ScheduledController,
    _env: Env,
    _ctx: ExecutionContext
  ) {
    console.log("NBSA scheduler heartbeat");
  }
};

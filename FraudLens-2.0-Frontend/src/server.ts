import { applySecurityHeaders } from "./lib/security-headers.server";
export default {
  async fetch(request: Request, env: unknown, ctx: unknown) {
    try {
      const url = new URL(request.url);
      if (url.pathname !== "/" && url.pathname.endsWith("/")) {
        url.pathname = url.pathname.slice(0, -1);
        return applySecurityHeaders(Response.redirect(url.href, 301));
      }
      const m = await import("@tanstack/react-start/server-entry");
      const handler = (m.default ?? m) as {
        fetch: (r: Request, e: unknown, c: unknown) => Promise<Response>;
      };
      return applySecurityHeaders(await handler.fetch(request, env, ctx));
    } catch {
      return applySecurityHeaders(
        new Response("The page is temporarily unavailable. Please try again.", {
          status: 503,
          headers: { "Content-Type": "text/plain" },
        }),
      );
    }
  },
};

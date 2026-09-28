import { createFileRoute } from "@tanstack/react-router";
import { siteUrl } from "../lib/site-url";
export const Route = createFileRoute("/robots.txt")({
  server: {
    handlers: {
      GET: () =>
        new Response(
          "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nDisallow: /track\nDisallow: /dashboard\nSitemap: " +
            siteUrl("/sitemap.xml"),
          { headers: { "Content-Type": "text/plain" } },
        ),
    },
  },
});

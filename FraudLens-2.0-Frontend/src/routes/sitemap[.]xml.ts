import { createFileRoute } from "@tanstack/react-router";
import { siteUrl } from "../lib/site-url";
export const Route = createFileRoute("/sitemap.xml")({
  server: {
    handlers: {
      GET: () =>
        new Response(
          '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            ["/", "/claims", "/underwriting", "/about"]
              .map((p) => "<url><loc>" + siteUrl(p) + "</loc></url>")
              .join("") +
            "</urlset>",
          { headers: { "Content-Type": "application/xml" } },
        ),
    },
  },
});

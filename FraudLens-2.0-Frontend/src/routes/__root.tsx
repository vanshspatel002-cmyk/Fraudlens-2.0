import { siteUrl } from "../lib/site-url";
import { useCardHover } from "../hooks/use-card-hover";
import { useScrollReveal } from "../hooks/use-scroll-reveal";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, createRootRouteWithContext, HeadContent, Scripts } from "@tanstack/react-router";
import { type ReactNode } from "react";
import css from "../styles.css?url";
import enterprise from "../experience/enterprise.css?url";
import meta from "../app-meta.json";
export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: meta.og_title },
      { name: "description", content: meta.og_description },
      { name: "theme-color", content: "#070A0F" },
      { property: "og:title", content: meta.og_title },
      { property: "og:description", content: meta.og_description },
      { property: "og:type", content: "website" },
      { property: "og:image", content: siteUrl(meta.og_image_url) },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:title", content: meta.og_title },
      { name: "twitter:description", content: meta.og_description },
      { name: "twitter:image", content: siteUrl(meta.og_image_url) },
      { property: "og:site_name", content: "FraudLens 2.0" },
      { property: "og:url", content: siteUrl("/") },
    ],
    links: [
      { rel: "stylesheet", href: css },
      { rel: "stylesheet", href: enterprise },
      { rel: "icon", href: "/favicon.svg" },
      { rel: "apple-touch-icon", href: "/apple-touch-icon.png" },
      { rel: "manifest", href: "/site.webmanifest" },
    ],
  }),
  shellComponent: Shell,
  component: Root,
  notFoundComponent: () => (
    <main className="tracker wrap">
      <h1>Page not found.</h1>
      <p>This page does not exist. Return to FraudLens 2.0 to choose a service.</p>
      <a href="/">Return home →</a>
    </main>
  ),
  errorComponent: ({ reset }) => (
    <main className="tracker wrap">
      <h1>This page could not load.</h1>
      <p>Please try again.</p>
      <button onClick={reset}>Try again</button>
    </main>
  ),
});
function Shell({ children }: { children: ReactNode }) {
  return (
    <html lang="en" style={{ colorScheme: "dark" }}>
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}
function Root() {
  useCardHover();
  useScrollReveal();
  const { queryClient } = Route.useRouteContext();
  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
    </QueryClientProvider>
  );
}

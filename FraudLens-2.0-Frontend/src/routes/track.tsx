import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Tracker";
export const Route = createFileRoute("/track")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/track") },
      { title: "Track a case | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Track a case. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
      { name: "robots", content: "noindex,nofollow" },
    ],
    links: [{ rel: "canonical", href: siteUrl("/track") }],
  }),
  component: () => <Page />,
});

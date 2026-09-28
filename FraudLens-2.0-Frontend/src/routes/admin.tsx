import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Admin";
export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/admin") },
      { title: "Admin workspace | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Admin workspace. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
      { name: "robots", content: "noindex,nofollow" },
    ],
    links: [{ rel: "canonical", href: siteUrl("/admin") }],
  }),
  component: () => <Page />,
});

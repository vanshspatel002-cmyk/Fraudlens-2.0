import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/About";
export const Route = createFileRoute("/about")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/about") },
      { title: "About | FraudLens 2.0" },
      {
        name: "description",
        content:
          "About. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/about") }],
  }),
  component: () => <Page />,
});

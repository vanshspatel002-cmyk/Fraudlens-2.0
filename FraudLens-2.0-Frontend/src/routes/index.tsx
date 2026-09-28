import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Home";
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/") },
      { title: "Home | FraudLens 2.0" },
      {
        name: "description",
        content: "Home. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/") }],
  }),
  component: () => <Page />,
});

import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Agent";
export const Route = createFileRoute("/claims")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/claims") },
      { title: "Claims | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Claims. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/claims") }],
  }),
  component: () => <Page kind="claims" />,
});

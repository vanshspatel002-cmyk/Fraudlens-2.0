import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Agent";
export const Route = createFileRoute("/underwriting")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/underwriting") },
      { title: "Underwriting | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Underwriting. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/underwriting") }],
  }),
  component: () => <Page kind="underwriting" />,
});

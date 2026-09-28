import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Intake";
export const Route = createFileRoute("/apply/underwriting")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/apply/underwriting") },
      { title: "Apply for Underwriting | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Apply for Underwriting. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/apply/underwriting") }],
  }),
  component: () => <Page kind="underwriting" />,
});

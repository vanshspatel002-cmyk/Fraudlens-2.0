import { siteUrl } from "../lib/site-url";
import { createFileRoute } from "@tanstack/react-router";
import Page from "../experience/Intake";
export const Route = createFileRoute("/apply/claims")({
  head: () => ({
    meta: [
      { property: "og:url", content: siteUrl("/apply/claims") },
      { title: "Apply for Claims | FraudLens 2.0" },
      {
        name: "description",
        content:
          "Apply for Claims. Explainable motor insurance photo-evidence review. Human judgment, always.",
      },
    ],
    links: [{ rel: "canonical", href: siteUrl("/apply/claims") }],
  }),
  component: () => <Page kind="claims" />,
});

import { createFileRoute } from "@tanstack/react-router";
import Dashboard from "../experience/Dashboard";
export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Your dashboard | FraudLens 2.0" },
      {
        name: "description",
        content: "Your motor insurance applications, case status and updates in one place.",
      },
      { name: "robots", content: "noindex,nofollow" },
    ],
  }),
  component: Dashboard,
});

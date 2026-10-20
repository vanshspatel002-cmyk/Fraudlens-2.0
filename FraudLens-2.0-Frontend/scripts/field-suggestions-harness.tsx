// Loaded only by verify_field_suggestions.py through the development server.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import Field from "../src/experience/FieldSuggestions";
import {
  sampleSuggestions,
  todayForInput,
  vehicleDependencyWarning,
} from "../src/experience/sampleSuggestions";

function Harness() {
  const [vehicle, setVehicle] = useState({ make: "", model: "", variant: "" });
  const kind =
    new URLSearchParams(location.search).get("kind") === "underwriting" ? "underwriting" : "claims";
  const names = [
    "name",
    "email",
    "phone",
    "license",
    "address",
    "make",
    "model",
    "variant",
    "year",
    "registration",
    "engine",
    "chassis",
    "idv",
    "policy",
    "previousPolicy",
    "ncb",
    "incidentDate",
    "incidentTime",
    "location",
    "amount",
    "garage",
    "description",
  ];
  return (
    <main style={{ maxWidth: 680, margin: "0 auto", padding: 16 }}>
      <h1>Field suggestion verification fixture</h1>
      <form>
        {names.map((name) => (
          <Field
            key={name}
            name={name}
            label={name}
            type={
              name === "incidentDate"
                ? "date"
                : name === "incidentTime"
                  ? "time"
                  : ["year", "idv", "ncb", "amount"].includes(name)
                    ? "number"
                    : name === "email"
                      ? "email"
                      : "text"
            }
            multiline={["address", "description"].includes(name)}
            maxLength={name === "description" ? 3000 : name === "address" ? 500 : undefined}
            max={name === "incidentDate" ? todayForInput() : undefined}
            suggestions={sampleSuggestions(name, { kind, ...vehicle })}
            warning={
              name === "model"
                ? vehicleDependencyWarning(vehicle.make, vehicle.model, vehicle.variant)
                : ""
            }
            onValueChange={
              name in vehicle
                ? (value) => setVehicle((previous) => ({ ...previous, [name]: value }))
                : undefined
            }
          />
        ))}
        <Field
          name="policyType"
          label="policyType"
          options={["Comprehensive", "Own damage", "Third party"]}
        />
        <Field
          name="bankLast4"
          label="bankLast4"
          suggestions={sampleSuggestions("bankLast4", { kind })}
        />
        <label>
          <input name="consent" type="checkbox" />
          Consent
        </label>
        <input name="evidence" type="file" />
        <button type="button" id="outside">
          Outside interaction
        </button>
      </form>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Harness />);

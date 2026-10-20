export type SampleSuggestion = { value: string; label?: string };

// Fictional presentation inputs only. This catalog is never sent with a case;
// a value enters FormData only after a user selects or types it.
const catalog: Record<string, string[]> = {
  name: ["Aarav Example", "Mira Sample", "Dev Testperson"],
  email: ["aarav@example.test", "mira@example.test", "dev@example.test"],
  phone: ["9000000101", "9000000102", "9000000103"],
  license: ["MH1220200012345", "MH1220210054321", "MH1220220098765"],
  address: [
    "12 Sample Lane, Example Nagar, Pune, Maharashtra 411001",
    "24 Fictional Avenue, Example Nagar, Pune, Maharashtra 411001",
    "36 Test Residency, Example Nagar, Pune, Maharashtra 411001",
  ],
  make: ["Maruti Suzuki", "Tata Motors", "Hyundai"],
  registration: ["MH12EX1201", "MH12EX1202", "MH12EX1203"],
  engine: ["SAMPLEENGINE1201", "SAMPLEENGINE1202", "SAMPLEENGINE1203"],
  chassis: ["SAMPLECHASSIS12001", "SAMPLECHASSIS12002", "SAMPLECHASSIS12003"],
  idv: ["500000", "650000", "800000"],
  policy: ["SAMPLE-MOTOR-1201", "SAMPLE-MOTOR-1202", "SAMPLE-MOTOR-1203"],
  previousPolicy: ["SAMPLE-PREV-1201", "SAMPLE-PREV-1202", "SAMPLE-PREV-1203"],
  ncb: ["0", "20", "25", "35", "50"],
  incidentTime: ["09:30", "12:00", "16:15"],
  location: [
    "Sample Lane, Example Nagar, Pune, Maharashtra",
    "Fictional Avenue car park, Example Nagar, Pune, Maharashtra",
    "Test Residency entrance, Example Nagar, Pune, Maharashtra",
  ],
  amount: ["18000", "35000", "72000"],
  garage: [
    "Example Motor Workshop, Pune",
    "Sample Auto Care, Pune",
    "Fictional Vehicle Services, Pune",
  ],
};

const vehicles = [
  {
    make: "Maruti Suzuki",
    aliases: ["maruti", "maruti suzuki"],
    model: "Swift",
    variants: ["VXI", "ZXI"],
  },
  {
    make: "Maruti Suzuki",
    aliases: ["maruti", "maruti suzuki"],
    model: "Baleno",
    variants: ["Delta", "Zeta"],
  },
  {
    make: "Tata Motors",
    aliases: ["tata", "tata motors"],
    model: "Nexon",
    variants: ["Creative", "Fearless"],
  },
  {
    make: "Tata Motors",
    aliases: ["tata", "tata motors"],
    model: "Punch",
    variants: ["Adventure", "Accomplished"],
  },
  { make: "Hyundai", aliases: ["hyundai"], model: "i20", variants: ["Magna", "Sportz"] },
  { make: "Hyundai", aliases: ["hyundai"], model: "Grand i10 Nios", variants: ["Magna", "Sportz"] },
];

function normalized(value = "") {
  return value.trim().toLowerCase();
}
function dateBeforeToday(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, "0"),
    String(value.getDate()).padStart(2, "0"),
  ].join("-");
}
export function todayForInput() {
  return dateBeforeToday(0);
}

export function sampleSuggestions(
  name: string,
  context: { kind: "claims" | "underwriting"; make?: string; model?: string },
): SampleSuggestion[] {
  if (name === "incidentDate")
    return [1, 3, 7].map((days) => ({
      value: dateBeforeToday(days),
      label: `${days === 1 ? "Yesterday" : `${days} days ago`} · ${dateBeforeToday(days)}`,
    }));
  if (name === "year")
    return [1, 3, 5].map((years) => ({ value: String(new Date().getFullYear() - years) }));
  if (name === "model") {
    const make = normalized(context.make);
    return vehicles
      .filter((vehicle) => !make || vehicle.aliases.includes(make))
      .map((vehicle) => ({ value: vehicle.model, label: `${vehicle.model} · ${vehicle.make}` }));
  }
  if (name === "variant") {
    const make = normalized(context.make),
      model = normalized(context.model);
    const matching = vehicles.filter(
      (vehicle) =>
        (!make || vehicle.aliases.includes(make)) &&
        (!model || normalized(vehicle.model) === model),
    );
    return [...new Set(matching.flatMap((vehicle) => vehicle.variants))].map((value) => ({
      value,
    }));
  }
  if (name === "description") {
    return (
      context.kind === "claims"
        ? [
            "Fictional example: while manoeuvring at low speed in the Example Nagar car park, the front-left bumper contacted a parking barrier. I noticed scratches and a small dent. The photographs show the visible damage; the repair estimate is provisional.",
            "Fictional example: I found a dent on the rear-right door after the vehicle had been parked on Sample Lane. I did not witness the contact and cannot confirm its cause. I am requesting inspection and an estimate.",
            "Fictional example: the left mirror contacted a gate while entering Test Residency. The mirror housing is cracked. I have included an overview and a close-up and request an assessment of the repair cost.",
          ]
        : [
            "Fictional example: the vehicle is used for private commuting and occasional family trips. I have not observed visible damage. Please inspect the uploaded views; this declaration is not an independent condition assessment.",
            "Fictional example: I am applying to renew cover. There are existing scratches on the rear-left bumper, which I have disclosed and photographed. The vehicle is used for personal travel.",
            "Fictional example: the vehicle is used for private travel. I am unsure whether marks on the front bumper require repair and request an inspection. The uploaded views document the current visible condition.",
          ]
    ).map((value) => ({ value }));
  }
  // Banking details, consent, authentication, and file controls deliberately
  // have no catalog entry and always require explicit manual input.
  return (catalog[name] || []).map((value) => ({ value }));
}

export function vehicleDependencyWarning(make: string, model: string, variant: string) {
  const selected = vehicles.find((vehicle) => normalized(vehicle.model) === normalized(model));
  if (!selected) return "";
  if (
    make &&
    vehicles.some((vehicle) => vehicle.aliases.includes(normalized(make))) &&
    !selected.aliases.includes(normalized(make))
  ) {
    return `${model} is listed in the sample catalog under ${selected.make}. Check the make and model; your entries have been kept.`;
  }
  if (
    variant &&
    vehicles.some((vehicle) =>
      vehicle.variants.some((item) => normalized(item) === normalized(variant)),
    ) &&
    !selected.variants.some((item) => normalized(item) === normalized(variant))
  ) {
    return `${variant} is not a sample variant for ${model}. Check the model and variant; your entries have been kept.`;
  }
  return "";
}

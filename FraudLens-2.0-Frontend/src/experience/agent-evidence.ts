type EvidenceCard = [title: string, category: string, description: string, limitation: string];
export const reconEvidence: EvidenceCard[] = [
  [
    "Case Memory (Internal Duplicate)",
    "History",
    "Searches every image ever submitted, to either agent, for a match.",
    "The strongest signal in the system — but reuse is a lead, not proof of intent.",
  ],
  [
    "Threshold Gaming",
    "Economic",
    "Flags a garage whose claims cluster just under ₹50,000, the line where a surveyor becomes mandatory.",
    "Attributed to the garage. Never an accusation against the claimant sitting in front of it.",
  ],
  [
    "External Corpus Search",
    "History",
    "Checks whether the image originates outside this claim entirely.",
    "Coverage is only as wide as the index behind it.",
  ],
  [
    "EXIF Metadata",
    "Provenance",
    "Reads whatever capture information the file still carries.",
    "Absence is neutral — WhatsApp and most upload paths strip it by default.",
  ],
  [
    "Sun & Shadow Consistency",
    "Context",
    "Calculates where the sun actually stood at the declared time and place, and checks it against the shadows in the photo.",
    "Needs a real time, a real location, and a shadow to measure.",
  ],
  [
    "Historical Weather",
    "Context",
    "Cross-references the declared conditions against what was actually recorded that day.",
    "Regional weather data doesn't always resolve to street level.",
  ],
  [
    "Plate Verification",
    "Identity",
    "Matches the visible registration against the declaration.",
    "OCR goes quiet on an obscured or low-resolution plate.",
  ],
  [
    "AI-Generation Detection",
    "Provenance",
    "Screens the image for signs it was synthetically produced rather than photographed.",
    "Measured against our own data, it flagged genuine photos more often than synthetic ones. Held at zero weight — recorded, never acted on, until it's trustworthy.",
  ],
  [
    "Digital Edit Detection",
    "Provenance",
    "Looks for compression and pixel-level traces of splicing or retouching.",
    "On our corpus it couldn't tell an edited image from an untouched one. Held at zero weight until it can.",
  ],
  [
    "Entity Graph",
    "History",
    "Looks for a phone number, bank account, or address repeating across claims that shouldn't be connected.",
    "A shared identifier is a thread to pull, not a verdict.",
  ],
];
export const sentinelEvidence: EvidenceCard[] = [
  [
    "Plate Verification",
    "Identity",
    "Matches the visible registration against the declaration.",
    "OCR goes quiet on an obscured or low-resolution plate.",
  ],
  [
    "View Completeness",
    "Identity",
    "Requires all four corners, the odometer, and the plate before an inspection counts as complete.",
    "A missing angle doesn't fail the case — it triggers a specific request for what's absent.",
  ],
  [
    "Case Memory (Internal Duplicate)",
    "History",
    "Checks this inspection's photos against everything ever submitted — including future claims on the same vehicle.",
    "The same engine Recon runs. Underwriting and claims share one memory.",
  ],
  [
    "EXIF Metadata",
    "Provenance",
    "Reads whatever capture information the file still carries.",
    "Absence is neutral — most upload paths strip it by default.",
  ],
  [
    "AI-Generation Detection",
    "Provenance",
    "Screens the image for signs it was synthetically produced rather than photographed.",
    "Measured against our own data, it flagged genuine photos more often than synthetic ones. Held at zero weight — recorded, never acted on, until it's trustworthy.",
  ],
  [
    "Digital Edit Detection",
    "Provenance",
    "Looks for compression and pixel-level traces of splicing or retouching.",
    "On our corpus it couldn't tell an edited image from an untouched one. Held at zero weight until it can.",
  ],
];

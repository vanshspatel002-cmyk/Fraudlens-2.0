type EvidenceCard = [title: string, category: string, description: string, limitation: string];
export const reconEvidence: EvidenceCard[] = [
  [
    "Case Memory (Internal Duplicate)",
    "History",
    "Searches every image ever submitted, to either agent, for a match.",
    "Verify matched evidence and legitimate reuse before attributing intent.",
  ],
  [
    "Threshold Gaming",
    "Economic",
    "Examines garage billing clustered below the preserved ₹50,000 research benchmark.",
    "Attributed to the garage. Never an accusation against the claimant sitting in front of it.",
  ],
  [
    "External Corpus Search",
    "History",
    "Searches the stored external image index for similarity matches.",
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
    "Six upload slots collect declared inspection views; actual view coverage requires review.",
    "Experimental check: zero weight and excluded from production routing. Same-vehicle views are not automatically verified.",
  ],
  [
    "Case Memory (Internal Duplicate)",
    "History",
    "Compares this inspection's photos with other submitted inspections and claims.",
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

import { createHash } from "node:crypto";
import { createInterface } from "node:readline/promises";
const rl = createInterface({ input: process.stdin, output: process.stdout });
console.log(
  "Enter a strong unique password. Input is visible locally; do not share your terminal.",
);
const password = await rl.question("Password: ");
rl.close();
if (!password) throw new Error("Password cannot be empty");
console.log("ADMIN_PASSWORD_SHA256=" + createHash("sha256").update(password).digest("hex"));

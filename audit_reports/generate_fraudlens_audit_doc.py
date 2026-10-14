from __future__ import annotations

import ast
import csv
import datetime as dt
import html
import json
import os
import re
import sqlite3
import subprocess
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "FraudLens-2.0-Backend"
FRONTEND = ROOT / "FraudLens-2.0-Frontend"
OUT = ROOT / "audit_reports" / "FraudLens_2_Project_Audit.docx"


def run(cmd: list[str], cwd: Path = ROOT) -> str:
    try:
        return subprocess.check_output(cmd, cwd=str(cwd), text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:  # noqa: BLE001 - report generator should keep going
        return f"OBSERVED FAILURE: {exc}"


def read(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"UNREADABLE: {exc}"
    return text if limit is None else text[:limit]


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def file_size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{n} B"
        value /= 1024
    return str(n)


def package_json() -> dict[str, Any]:
    return json.loads(read(FRONTEND / "package.json"))


def py_symbols(path: Path) -> dict[str, Any]:
    text = read(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"classes": [], "functions": [], "error": str(exc)}
    classes: list[str] = []
    funcs: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(f"{node.name} (line {node.lineno})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(f"{node.name} (line {node.lineno})")
    return {"classes": classes, "functions": funcs}


def ts_symbols(path: Path) -> list[str]:
    symbols: list[str] = []
    for i, line in enumerate(read(path).splitlines(), 1):
        s = line.strip()
        if re.search(r"createFileRoute|createRootRoute|export default function|export function|export const|function [A-Z]|const [A-Z][A-Za-z0-9_]+\s*=", s):
            symbols.append(f"line {i}: {s[:160]}")
    return symbols


def source_files() -> list[Path]:
    paths: list[Path] = []
    for base in [BACKEND / "src", BACKEND / "scripts", FRONTEND / "src", FRONTEND / "scripts"]:
        if base.exists():
            paths.extend(p for p in sorted(base.rglob("*")) if p.is_file())
    extras = [
        ROOT / ".gitignore",
        BACKEND / "app.py",
        BACKEND / "requirements.txt",
        BACKEND / "runtime.txt",
        BACKEND / "railway.json",
        BACKEND / "DEPLOYMENT.md",
        BACKEND / ".env.example",
        FRONTEND / "package.json",
        FRONTEND / "vite.config.ts",
        FRONTEND / "vercel.json",
        FRONTEND / "tsconfig.json",
        FRONTEND / "README.md",
        FRONTEND / "INTEGRATION.md",
        FRONTEND / "EXPORT_NOTES.md",
        FRONTEND / ".env.example",
    ]
    paths.extend(p for p in extras if p.exists())
    return sorted(set(paths))


def dir_summary() -> list[tuple[str, int, int, list[str]]]:
    exclude = {".git", "node_modules", "venv", ".output", "dist", "build", "__pycache__", ".tanstack"}
    rows: list[tuple[str, int, int, list[str]]] = []
    for base in [BACKEND, FRONTEND]:
        for d, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in exclude]
            size = 0
            count = 0
            for name in files:
                fp = Path(d) / name
                try:
                    size += fp.stat().st_size
                    count += 1
                except OSError:
                    pass
            rows.append((rel(Path(d)), count, size, dirs[:10]))
    return rows


def db_schema() -> list[dict[str, Any]]:
    db = BACKEND / "fraudlens.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    rows = []
    for (name,) in cur.execute("select name from sqlite_master where type='table' order by name").fetchall():
        count = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        cols = [
            {"name": r[1], "type": r[2], "not_null": bool(r[3]), "pk": bool(r[5])}
            for r in cur.execute(f'PRAGMA table_info("{name}")').fetchall()
        ]
        rows.append({"table": name, "count": count, "columns": cols})
    conn.close()
    return rows


def api_endpoints() -> list[dict[str, str]]:
    openapi = BACKEND / "outputs" / "openapi.json"
    out: list[dict[str, str]] = []
    if openapi.exists():
        data = json.loads(read(openapi))
        for path, methods in data.get("paths", {}).items():
            for method, spec in methods.items():
                out.append({
                    "method": method.upper(),
                    "path": path,
                    "operation": spec.get("summary") or spec.get("operationId") or "",
                })
    return out


def env_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in read(path).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" in line:
            names.append(line.split("=", 1)[0].strip())
    return names


def tracked_files_count() -> str:
    return run(["git", "ls-files"]).count("\n") + 1 if run(["git", "ls-files"]) else "unknown"


def xml_text(text: str, style: str | None = None) -> str:
    text = str(text)
    parts = []
    for chunk in text.split("\n"):
        runs = ""
        for i, seg in enumerate(chunk.split("\t")):
            if i:
                runs += "<w:r><w:tab/></w:r>"
            runs += f"<w:r><w:t xml:space=\"preserve\">{html.escape(seg)}</w:t></w:r>"
        ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
        parts.append(f"<w:p>{ppr}{runs}</w:p>")
    return "".join(parts)


def bullet(text: str) -> str:
    return xml_text("• " + text)


def heading(text: str, level: int = 1) -> str:
    return xml_text(text, f"Heading{level}")


def table(rows: list[list[Any]]) -> str:
    out = ["<w:tbl><w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/><w:tblBorders>"
           "<w:top w:val=\"single\" w:sz=\"4\"/><w:left w:val=\"single\" w:sz=\"4\"/>"
           "<w:bottom w:val=\"single\" w:sz=\"4\"/><w:right w:val=\"single\" w:sz=\"4\"/>"
           "<w:insideH w:val=\"single\" w:sz=\"4\"/><w:insideV w:val=\"single\" w:sz=\"4\"/>"
           "</w:tblBorders></w:tblPr>"]
    for row in rows:
        out.append("<w:tr>")
        for cell in row:
            out.append("<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>")
            out.append(xml_text(str(cell)))
            out.append("</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def docx(parts: list[str]) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14"><w:body>'
        + "".join(parts)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        '</w:body></w:document>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>'
        '</w:styles>'
    )
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)


def main() -> None:
    pkg = package_json()
    parts: list[str] = [xml_text("FraudLens 2.0 Complete Project Audit", "Title")]
    parts.append(xml_text(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')} local time"))
    parts.append(xml_text(f"Workspace root: {ROOT}"))
    parts.append(xml_text("Evidence labels used: VERIFIED, INFERRED, UNKNOWN / NOT FOUND, NOT TESTED, OBSERVED FAILURE, DOCUMENTED PLAN. Secrets and .env values are intentionally redacted."))

    branch = run(["git", "branch", "--show-current"])
    commit = run(["git", "rev-parse", "HEAD"])
    log = run(["git", "log", "--oneline", "--decorate", "--date=short", "--pretty=format:%h %ad %d %s", "--max-count=10"])
    status = run(["git", "status", "--short"]) or "(no uncommitted tracked changes reported)"

    parts += [
        heading("1. Project At A Glance"),
        table([
            ["Field", "Verified value / evidence"],
            ["Project", "FraudLens 2.0"],
            ["Workspace", str(ROOT)],
            ["Shape", "Two sibling applications: Python backend and React/TanStack frontend."],
            ["Backend", "FastAPI service in FraudLens-2.0-Backend/src/api.py; Streamlit analyst UI in app.py."],
            ["Frontend", f"{pkg.get('name')} {pkg.get('version')} using React {pkg['dependencies'].get('react')}, TanStack Router/Start, Vite, Tailwind CSS."],
            ["Database", "SQLite files in backend root; primary local DB fraudlens.db."],
            ["Deployment", "Backend Railway via railway.json; frontend Vercel via vercel.json."],
            ["Git", f"branch {branch}; HEAD {commit[:12] if len(commit) > 12 else commit}; tracked files {tracked_files_count()}"],
            ["Working tree", status],
        ]),
        bullet("VERIFIED purpose: insurance fraud/risk review for vehicle claims and underwriting evidence. Evidence: backend checks, API contract, frontend intake/admin/tracker pages, and project notes."),
        bullet("VERIFIED current DB state: 800 cases, 1,395 images, 13,839 findings, 878 agent_decisions, 130 perception_records in fraudlens.db."),
        bullet("INFERRED users: claimants/applicants submit evidence and track status; analysts/admin users review queues, evidence, findings, traces, reports and human actions."),
    ]

    parts += [heading("2. Technology Stack")]
    parts.append(table([
        ["Area", "Evidence"],
        ["Python runtime", read(BACKEND / "runtime.txt").strip()],
        ["Backend dependencies", "FastAPI, Streamlit, sqlite3, Pydantic, Pillow, OpenCV, EasyOCR, CLIP/open_clip, Torch, Transformers, Google GenAI/Gemini, scikit-image/learn, pandas, matplotlib."],
        ["Frontend runtime", f"Node {read(FRONTEND / '.nvmrc').strip()}; package engines {pkg.get('engines')}"],
        ["Frontend dependencies", ", ".join(sorted([k for k in pkg.get("dependencies", {}).keys()])[:35]) + " ..."],
        ["Build/dev scripts", json.dumps(pkg.get("scripts", {}), ensure_ascii=False)],
        ["Hosting", "Railway backend startCommand uvicorn src.api:app --host 0.0.0.0 --port $PORT; Vercel frontend framework tanstack-start."],
    ]))

    parts += [heading("3. Directory Inventory")]
    parts.append(xml_text("Large generated/dependency directories are summarized, not dumped: .git, node_modules, backend venv, frontend dist/.output/.tanstack, Python caches, raw image corpora, database backups, and output logs."))
    rows = [["Directory", "Immediate files", "Immediate bytes", "Important subdirectories"]]
    for d, count, size, dirs in dir_summary()[:120]:
        rows.append([d, count, size, ", ".join(dirs)])
    parts.append(table(rows))

    parts += [heading("4. File Inventory")]
    rows = [["Path", "Size", "Purpose / key symbols"]]
    for path in source_files():
        purpose = ""
        if path.suffix == ".py":
            sy = py_symbols(path)
            purpose = "Classes: " + ", ".join(sy.get("classes", [])[:8])
            if sy.get("functions"):
                purpose += "; Functions: " + ", ".join(sy["functions"][:10])
        elif path.suffix in {".ts", ".tsx"}:
            syms = ts_symbols(path)
            purpose = "; ".join(syms[:6])
        elif path.name == "package.json":
            purpose = "Frontend manifest with scripts, dependencies, devDependencies, engines."
        elif path.name in {"requirements.txt", "runtime.txt", "railway.json", "vercel.json", "tsconfig.json", "vite.config.ts"}:
            purpose = "Runtime/build/deployment configuration."
        elif path.suffix in {".md", ".example", ".json", ".css"}:
            purpose = "Documentation, configuration, styles, or metadata."
        rows.append([rel(path), file_size(path), purpose[:900]])
    parts.append(table(rows))

    parts += [heading("5. Backend Architecture")]
    parts.append(bullet("FastAPI app is created in src/api.py and exposes 18 OpenAPI path/method pairs. Important security and runtime code includes dotenv loading, CORS origin parsing, client IP detection, rate limiting, middleware, API error envelopes, admin bearer-password validation, and DB dependency creation."))
    parts.append(bullet("Domain models live in src/models.py as dataclasses/enums: CheckCategory, Verdict, Recommendation, AdminAction, RiskBand, Finding, AgentDecision, PerceptionRecord, Case, AdminActionRecord, Claimant, ImageArtifact, Image, AuditEvent."))
    parts.append(bullet("Persistence is a plain sqlite3 layer in src/db.py, with CREATE TABLE statements, migration helpers, insert/get helpers, audit logging, and cache_entries helpers. The file explicitly documents a possible Postgres migration path."))
    parts.append(bullet("Case processing flow: API submission saves uploads, ingests image hashes/EXIF/embeddings, runs registered checks, adjudicates via agent policy/provider, persists decisions/audit events, and exposes status through an in-memory job store."))
    parts.append(bullet("LLM/provider layer in src/llm.py supports Gemini and Ollama, cache keys, usage stats, key discovery/rotation, retry/error classification, and quota-budget integration."))
    parts.append(bullet("Agent layer in src/agent/* builds prompts/policies, declares tools, calls the provider, parses JSON decisions, executes tool calls, and falls back to desk review when provider/reasoning fails."))
    parts.append(bullet("Streamlit app.py is a separate analyst/debugging interface that calls the FastAPI service and renders queues, details, traces and dashboard/ablation views."))

    parts += [heading("6. API Reference")]
    parts.append(table([["Method", "Path", "Operation"]] + [[e["method"], e["path"], e["operation"]] for e in api_endpoints()]))
    parts.append(xml_text("Endpoint decorator evidence from src/api.py includes /v1/cases at line 933, /v1/cases/{case_id} at line 1016, /v1/images/{image_id} at line 1293, /health and /v1/health at lines 1566-1568, POST /v1/cases at line 1697, job polling at line 1874, and admin action at line 1883."))
    api_ref = read(BACKEND / "outputs" / "api_reference.md", 8000)
    parts.append(xml_text("Existing generated API reference excerpt: " + api_ref.replace("\n", " ")[:4500]))

    parts += [heading("7. Database And Persistence")]
    db_rows = [["Table", "Rows", "Columns"]]
    for t in db_schema():
        db_rows.append([t["table"], t["count"], ", ".join([c["name"] + " " + c["type"] + (" PK" if c["pk"] else "") for c in t["columns"]])])
    parts.append(table(db_rows))
    parts.append(bullet("VERIFIED storage files: fraudlens.db, fraudlens_repeat.db, fraudlens_ring.db, fraudlens_scenarios.db and DB backups exist in the backend root. Values are not embedded in the report."))
    parts.append(bullet("VERIFIED data directories include curated, raw, generated, external corpus, uploads, backups, cache and outputs. The largest image corpora are summarized by directory counts rather than enumerated individually."))

    parts += [heading("8. Frontend Architecture")]
    parts.append(bullet("Routes are file-based TanStack routes under src/routes: /, /about, /admin, /apply/claims, /apply/underwriting, /claims, /dashboard, /track, /underwriting, /robots.txt, /sitemap.xml. routeTree.gen.ts is generated."))
    parts.append(bullet("Application shell/root route uses QueryClient context in src/routes/__root.tsx. Router construction is in src/router.tsx. TanStack Start entry is src/start.ts; server fetch adapter with security headers is src/server.ts."))
    parts.append(bullet("Experience components under src/experience implement home/product narrative, claims/underwriting intake, tracker, user dashboard, admin workspace, admin overview, evidence viewer, intro video, agent personas and shared API helpers."))
    parts.append(bullet("shared.tsx centralizes navigation, logos, CTA/footer blocks, categories/check display metadata, VITE_API_BASE_URL handling, localStorage admin credentials, API request mapping, case detail mapping, image URL helpers and config loading."))
    parts.append(bullet("components/ui contains 46 reusable Radix/shadcn-style primitives; styles.css plus enterprise/admin/user CSS files carry the visual system."))

    parts += [heading("9. Features And Status")]
    parts.append(table([
        ["Feature", "Status", "Evidence / limitation"],
        ["Public claims and underwriting intake", "Partially implemented / requires live verification", "Frontend Intake.tsx validates forms/uploads and calls POST /v1/cases. Backend route exists. Full workflow was not completed during audit."],
        ["Case tracking", "Implemented and evidenced", "GET /v1/track and Tracker.tsx/Dashboard link flows; requires case id plus registration or policy number."],
        ["Admin queue/detail workspace", "Implemented and evidenced", "Admin.tsx, AdminOverview.tsx, GET /v1/cases, /v1/cases/{id}, /v1/images, /v1/stats."],
        ["Human action recording", "Implemented and evidenced", "POST /v1/cases/{case_id}/action; admin_actions table has 2 rows."],
        ["Image serving/thumbnails", "Implemented and evidenced", "GET /v1/images/{image_id}?thumb=1; thumbnail cache directory exists."],
        ["Rules/check battery", "Implemented with limitations", "15 active registered checks plus retired vehicle_consistency per current_state.md."],
        ["Agent adjudication", "Partially implemented / quota-limited", "Agent engine, policy, tools, LLM provider, traces; known incomplete ablation and provider/quota issues."],
        ["Reports", "Implemented as structured API; PDF export unknown", "GET /v1/cases/{case_id}/report returns structured report; later PDF export mentioned in API text but not verified."],
        ["Deployment", "Configured, not verified live", "Railway and Vercel config/docs exist; no production deploy executed."],
        ["SaaS multi-tenancy/auth/billing", "DOCUMENTED PLAN", "outputs/saas_roadmap.md lists future work; current system has shared admin password, SQLite, process-local jobs."],
    ]))

    parts += [heading("10. Check Battery")]
    current = read(BACKEND / "outputs" / "current_state.md", 12000)
    parts.append(xml_text(current))

    parts += [heading("11. Configuration And Secrets")]
    parts.append(bullet("VERIFIED backend env example names: " + ", ".join(env_names(BACKEND / ".env.example"))))
    parts.append(bullet("VERIFIED frontend env example names: " + ", ".join(env_names(FRONTEND / ".env.example"))))
    parts.append(bullet("SENSITIVE: .env files exist in backend and frontend directories but values were not copied into this report. .gitignore excludes .env, DB files, data, outputs, venv, node_modules and generated builds."))
    parts.append(bullet("Admin authentication today uses ADMIN_EMAIL plus bearer password hashed to ADMIN_PASSWORD_SHA256; frontend stores entered admin email/password in localStorage for requests."))

    parts += [heading("12. Git And History")]
    parts.append(xml_text(f"Branch: {branch}\nHEAD: {commit}\nStatus: {status}\nRecent log:\n{log}"))
    parts.append(bullet("Only one commit was observed in git log: f30cd20 dated 2026-09-28, 'Initial FraudLens 2.0 full-stack project'. Earlier project evolution is present mainly through generated outputs, backups, logs and dated documents, not through commit history."))

    parts += [heading("13. Verification Commands")]
    parts.append(table([
        ["Command", "Observed result"],
        ["git status --short", status],
        ["git branch --show-current / git rev-parse HEAD", f"{branch}; {commit}"],
        ["SQLite schema/count inspection", "Succeeded; table counts included above."],
        ["Global python import checks", "docx False; pytest False; fastapi False. Therefore docx generated with stdlib OOXML package."],
        [r".\venv\Scripts\python.exe -m pytest -q", "Started from backend venv. Partial output showed E................EFFFFFFFFFFFFFFF, then command remained long-running and was interrupted. NOT PASSED / NOT COMPLETED."],
        ["npm run build", "Started in frontend; printed script header 'tsc --noEmit && vite build', then remained long-running and was interrupted. NOT PASSED / NOT COMPLETED."],
    ]))

    parts += [heading("14. Known Issues, Risks, Roadmap")]
    parts.append(xml_text(read(BACKEND / "outputs" / "known_issues.md", 16000)))
    parts.append(xml_text(read(BACKEND / "outputs" / "saas_roadmap.md", 12000)))

    parts += [heading("15. Prioritized Continuation Roadmap")]
    for item in [
        "Finish/validate the interrupted backend test suite and frontend production build; preserve exact failure logs.",
        "Complete the agent ablation arm or clearly freeze the current research claim until quota/provider availability allows completion.",
        "After ablation consistency constraints are satisfied, fix known stale prompt reliability text and threshold_gaming claimant/garage wording.",
        "Add API filters documented as gaps: decided filter and policy_version filtering for case decisions.",
        "Replace process-local job store and rate limiter before multi-worker deployment.",
        "Move production persistence from local SQLite/data directories to durable volume/object storage or Postgres plus object storage.",
        "Implement real authentication/roles before any external multi-user pilot.",
        "Increase perception coverage or integrate local vision fallback before relying heavily on perception-dependent checks.",
    ]:
        parts.append(bullet(item))

    parts += [heading("16. Missing Information And Audit Limits")]
    for item in [
        "No live Railway or Vercel deployment was contacted or verified.",
        "No external Gemini/Ollama provider call was made during this audit.",
        "No production credentials or .env values are included.",
        "Generated data/images/database rows were summarized rather than fully embedded.",
        "The broad pytest/build commands were interrupted after prolonged execution; final pass/fail status remains unknown beyond observed partial output.",
        "Git history before the initial full-stack commit is unavailable in this repository.",
    ]:
        parts.append(bullet(item))

    docx(parts)
    print(OUT)


if __name__ == "__main__":
    main()

# FraudLens file inventory appendix

Companion to [FraudLens_Mentor_Guide.md](FraudLens_Mentor_Guide.md) and [FraudLens_Mentor_Guide.pdf](FraudLens_Mentor_Guide.pdf). Audit date: **21 October 2026** (Asia/Calcutta). Branch: `repair/analysis-pipeline-20261020`; inspected commit: `a72e4fdc2d15b47de6c0da623a76df56ff9a8fe0`.

This inventory includes current source/configuration and eight pre-existing staged documentation changes, which were read and left untouched. No application imports, tests, providers, live database connections, migrations, case processing or deployment were executed to build the inventory. Python abstract syntax trees (ASTs), TypeScript/JavaScript imports, manifests, migration SQL and explicit entrypoints were inspected as text. No applicable AGENTS.md was found in the workspace or its parents.

**Status words.** Active means a registered route, production entrypoint or statically reachable implementation exists; it is not a fresh successful execution claim. Tooling/research means explicitly invoked utilities, experimental/control-arm implementations or fixtures. Legacy means retained compatibility/retired code. Unconfirmed means no product import/call was established. Dated saved verification records are distinguished from implementation in the mentor guide.

All paths are repository-relative. Full file rows live here to keep the main PDF readable. “Main dependencies/callers” lists representative static relationships, not every standard-library import. Framework-discovered routes/configuration may execute without normal imports. Reachability does not mean every optional/research branch executes during customer intake.

## Scope, counts and exclusions

- **322 tracked files** are covered individually below, including small tracked generated route metadata, first-party docs and public assets. Binary media are named but not copied.
- **Three generated documentation deliverables** are included after the source inventory. No additional relevant untracked source/configuration existed at the initial git inspection.
- Pre-existing staged docs: `AUTONOMOUS_PROGRESS.md`, `CHECK_VERIFICATION_MATRIX.md`, `DEMO_READINESS_CHECKLIST.md`, `DEMO_RUNBOOK.md`, `GEMINI_DIAGNOSIS.md`, `LATENCY_MEASUREMENTS.md`, `PILOT_HANDOVER.md`, `POSTGRES_MIGRATION.md`.

| Grouped/excluded category | Purpose and reason for grouping |
|---|---|
| `.git/` | Version-control internals; inspected through Git commands, not object-by-object. |
| `FraudLens-2.0-Frontend/node_modules/` | Third-party installed JS dependency tree; direct declarations and lockfile inventoried separately. |
| `FraudLens-2.0-Backend/venv/` | Python interpreter and third-party packages; requirements are the first-party inputs. |
| Frontend `.output/`, `dist/`, `.tanstack/`, `.wrangler/`, `.browser-check/` | Generated builds/router/cache/browser outputs, grouped rather than enumerated. Tracked `src/routeTree.gen.ts` is explicitly retained as useful route metadata. |
| `**/__pycache__/`, `.pytest_cache/`, `.cache/`, `.tmp/`, `temp/`, coverage directories | Interpreter/test/download/temporary caches and diagnostics; not first-party application source. |
| Backend `models/` and external model caches | Downloaded CLIP/OCR/classifier weights/checkpoints; third-party artifacts, not authored source. |
| `FraudLens-2.0-Backend/data/` | Raw/reference photos, generated synthetic datasets, answer keys and corpus indices. Data generators/audits are listed; private/licensed datasets are not expanded. |
| `FraudLens-2.0-Backend/outputs/` | Runtime/research artifacts, provider ledgers, receipts, manifests, reports, verification evidence and timings. No private filenames/applicant details are reproduced. |
| Configured private upload/thumbnail storage | Original evidence and previews shared by API/worker; private files, separate from public frontend assets. |
| Backend `backups/`, database files and backup archives | Private PostgreSQL/SQLite/filesystem snapshots; management scripts listed, contents excluded. |
| `.env*` except `.env.example`, `.dev.vars*`, logs and worker locks | Secrets/config values, provider controls and process state are never copied. Variable names may be documented. |
| `.vscode/`, `.idea/`, OS metadata | Local editor/host state, outside application source. |

## Entrypoints and import tracing

- Frontend: `src/router.tsx` → `src/routeTree.gen.ts` → `src/routes/*` → `src/experience/*`. TanStack Start also loads `src/start.ts` and configured `src/server.ts`. CSS/public assets enter through those components and root metadata.
- Backend: `src.api:app` installs runtime, customer/evidence/report workflows. Worker entry: `scripts/run_worker.py` → `src/durable_worker.py`; deployment wrapper: `scripts/start_deployment.py`.
- `src/checks/__init__.py` explicitly imports registered checks and excludes `retired/`. Product experience components do not import `src/components/ui/*`; installed template/chart/form packages do not prove product use.

## Frontend routes and product components

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Frontend/src/experience/About.tsx` | Active project/engine explanation page. | `About` | Imported by `src/routes/about.tsx`; Uses `src/experience/IntelligenceEngine.tsx`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/Admin.tsx` | Active reviewer login/session, queue filtering/polling, selected-case fetching and workspace composition. | `Admin`, `Garage` | Imported by `src/routes/admin.tsx`; Uses `src/experience/AdminOverview.tsx`, `src/experience/CaseReview.tsx`, `src/experience/EvidenceViewer.tsx`, `src/experience/HistoricalReport.tsx` + 3 more |
| `FraudLens-2.0-Frontend/src/experience/AdminOverview.tsx` | Active queue metrics and returned-data volume/risk summaries. | `AdminOverview` | Imported by `src/experience/Admin.tsx`; Uses `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/Agent.tsx` | Active reusable claims/underwriting service presentation with authored examples. | `Agent` | Imported by `src/routes/claims.tsx`, `src/routes/underwriting.tsx`; Uses `src/experience/after-apply.ts`, `src/experience/agent-evidence.ts`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/CaseReview.tsx` | Active vertical workspace: application facts, photos, three-sentence Desk Review/PDF controls, human actions, timeline and collapsed diagnostics. | `CaseReview` | Imported by `src/experience/Admin.tsx`; Uses `src/experience/ReportPanel.tsx`, `src/experience/case-review.css`, `src/experience/reviewPresentation.ts` |
| `FraudLens-2.0-Frontend/src/experience/CustomerSession.tsx` | Active CustomerGate registration/login and expiry handling around protected screens. | `CustomerGate` | Imported by `src/experience/Dashboard.tsx`, `src/experience/Intake.tsx`; Uses `src/experience/customer-api.ts`, `src/experience/customer-session.css`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/Dashboard.tsx` | Active customer case list/detail, supplementary evidence, polling and reviewer outcome presentation. | `Dashboard`, `Photograph`, `AdditionalEvidence`, `Workspace` | Imported by `src/routes/dashboard.tsx`; Uses `src/experience/CustomerSession.tsx`, `src/experience/customer-api.ts`, `src/experience/shared.tsx`, `src/experience/user-dashboard.css` |
| `FraudLens-2.0-Frontend/src/experience/EvidenceViewer.tsx` | Active authenticated image modal, navigation and keyboard/focus handling. | `EvidenceViewer` | Imported by `src/experience/Admin.tsx`; Uses `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/FieldSuggestions.tsx` | Active optional accessible field suggestions; examples are fictional sample values. | `FieldSuggestions` | Imported by `scripts/field-suggestions-harness.tsx`, `src/experience/Intake.tsx`; Uses `src/experience/field-suggestions.css`, `src/experience/sampleSuggestions.ts` |
| `FraudLens-2.0-Frontend/src/experience/HistoricalReport.tsx` | Active saved-run dialog and ReportPanel; no new analysis request. | `HistoricalReport` | Imported by `src/experience/Admin.tsx`; Uses `src/experience/ReportPanel.tsx`, `src/experience/reviewPresentation.ts` |
| `FraudLens-2.0-Frontend/src/experience/Home.tsx` | Active landing page connecting service choices, engine explanation and intro video. | `Home` | Imported by `src/routes/index.tsx`; Uses `src/experience/IntelligenceEngine.tsx`, `src/experience/IntroVideo.tsx`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/Intake.tsx` | Active customer forms, native/custom validation, explicit upload slots/previews and multipart submission. | `Intake`, `IntakeForm` | Imported by `src/routes/apply.claims.tsx`, `src/routes/apply.underwriting.tsx`; Uses `src/experience/CustomerSession.tsx`, `src/experience/FieldSuggestions.tsx`, `src/experience/sampleSuggestions.ts`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/IntelligenceEngine.tsx` | Active authored engine explainer used by Home/About; presentation copy is not verification evidence. | `IntelligenceEngine` | Imported by `src/experience/About.tsx`, `src/experience/Home.tsx`; Uses `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/IntroVideo.tsx` | Active bundled video visibility/playback/reduced-motion behavior. | `IntroVideo` | Imported by `src/experience/Home.tsx` |
| `FraudLens-2.0-Frontend/src/experience/ReportPanel.tsx` | Active run-specific PDF versions, Blob preview/download and loading/error/modal handling. | `ReportPanel` | Imported by `src/experience/CaseReview.tsx`, `src/experience/HistoricalReport.tsx`; Uses `src/experience/report-panel.css`, `src/experience/reportClient.ts` |
| `FraudLens-2.0-Frontend/src/experience/Tracker.tsx` | Active case ID/receipt lookup and status/evidence-request presentation. | `Tracker` | Imported by `src/routes/track.tsx`; Uses `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/shared.tsx` | Active header/footer, brand/SVG icons, fields, service copy and customer session controls. | `categories`, `recommendations`, `checks`, `Icon`, `Mark`, `Logo`, `Header`, `Footer`, `Shell`; further helpers | Imported by `src/experience/About.tsx`, `src/experience/Admin.tsx`, `src/experience/AdminOverview.tsx`, `src/experience/Agent.tsx` + 7 more; Uses `src/experience/customer-api.ts` |
| `FraudLens-2.0-Frontend/src/routes/__root.tsx` | Active SSR shell, page metadata, root query context, shared styles, outlet and error/404 views. | `Route`, `Shell`, `Root` | Imported by `src/routeTree.gen.ts`; Uses `src/app-meta.json`, `src/experience/enterprise.css`, `src/hooks/use-card-hover.ts`, `src/hooks/use-scroll-reveal.ts` + 2 more |
| `FraudLens-2.0-Frontend/src/routes/about.tsx` | Active /about route rendering About. | `Route` /about | Imported by `src/routeTree.gen.ts`; Uses `src/experience/About.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/admin.tsx` | Active /admin reviewer workspace route. | `Route` /admin | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Admin.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/apply.claims.tsx` | Active /apply/claims route rendering IntakeForm in claims mode. | `Route` /apply/claims | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Intake.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/apply.underwriting.tsx` | Active /apply/underwriting route rendering IntakeForm in underwriting mode. | `Route` /apply/underwriting | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Intake.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/claims.tsx` | Active /claims service introduction rendering Agent in claims mode. | `Route` /claims | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Agent.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/dashboard.tsx` | Active /dashboard customer account/case/outcome route. | `Route` /dashboard | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Dashboard.tsx` |
| `FraudLens-2.0-Frontend/src/routes/index.tsx` | Active / route rendering Home. | `Route` / | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Home.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/robots[.]txt.ts` | Active /robots.txt server crawl-policy route. | `Route` /robots.txt | Imported by `src/routeTree.gen.ts`; Uses `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/sitemap[.]xml.ts` | Active /sitemap.xml public-route server index. | `Route` /sitemap.xml | Imported by `src/routeTree.gen.ts`; Uses `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/track.tsx` | Active /track case ID/receipt tracker route. | `Route` /track | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Tracker.tsx`, `src/lib/site-url.ts` |
| `FraudLens-2.0-Frontend/src/routes/underwriting.tsx` | Active /underwriting service introduction rendering Agent in underwriting mode. | `Route` /underwriting | Imported by `src/routeTree.gen.ts`; Uses `src/experience/Agent.tsx`, `src/lib/site-url.ts` |

## Frontend reusable UI primitives (templates)

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Frontend/src/components/ui/accordion.tsx` | Reusable accordion UI template; outside product entrypoint import graph. | `Accordion`, `AccordionItem`, `AccordionTrigger`, `AccordionContent` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/alert-dialog.tsx` | Reusable alert dialog UI template; outside product entrypoint import graph. | `AlertDialog`, `AlertDialogTrigger`, `AlertDialogPortal`, `AlertDialogOverlay`, `AlertDialogContent`, `AlertDialogHeader`; further helpers | No product import found; Uses `src/components/ui/button.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/alert.tsx` | Reusable alert UI template; outside product entrypoint import graph. | `alertVariants`, `Alert`, `AlertTitle`, `AlertDescription` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/aspect-ratio.tsx` | Reusable aspect ratio UI template; outside product entrypoint import graph. | `AspectRatio` | No product import found |
| `FraudLens-2.0-Frontend/src/components/ui/avatar.tsx` | Reusable avatar UI template; outside product entrypoint import graph. | `Avatar`, `AvatarImage`, `AvatarFallback` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/badge.tsx` | Reusable badge UI template; outside product entrypoint import graph. | `Badge` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/breadcrumb.tsx` | Reusable breadcrumb UI template; outside product entrypoint import graph. | `Breadcrumb`, `BreadcrumbList`, `BreadcrumbItem`, `BreadcrumbLink`, `Comp`, `BreadcrumbPage`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/button.tsx` | Reusable button UI template; outside product entrypoint import graph. | `buttonVariants`, `Button`, `Comp` | Imported by `src/components/ui/alert-dialog.tsx`, `src/components/ui/calendar.tsx`, `src/components/ui/carousel.tsx`, `src/components/ui/pagination.tsx` + 1 more; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/calendar.tsx` | Reusable calendar UI template; outside product entrypoint import graph. | `Calendar`, `CalendarDayButton` | No product import found; Uses `src/components/ui/button.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/card.tsx` | Reusable card UI template; outside product entrypoint import graph. | `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/carousel.tsx` | Reusable carousel UI template; outside product entrypoint import graph. | `useCarousel` | No product import found; Uses `src/components/ui/button.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/chart.tsx` | Reusable chart UI template; outside product entrypoint import graph. | `useChart`, `getPayloadConfigFromPayload` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/checkbox.tsx` | Reusable checkbox UI template; outside product entrypoint import graph. | `Checkbox` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/collapsible.tsx` | Reusable collapsible UI template; outside product entrypoint import graph. | `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` | No product import found |
| `FraudLens-2.0-Frontend/src/components/ui/command.tsx` | Reusable command UI template; outside product entrypoint import graph. | `Command`, `CommandDialog`, `CommandInput`, `CommandList`, `CommandEmpty`, `CommandGroup`; further helpers | No product import found; Uses `src/components/ui/dialog.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/context-menu.tsx` | Reusable context menu UI template; outside product entrypoint import graph. | `ContextMenu`, `ContextMenuTrigger`, `ContextMenuGroup`, `ContextMenuPortal`, `ContextMenuSub`, `ContextMenuRadioGroup`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/dialog.tsx` | Reusable dialog UI template; outside product entrypoint import graph. | `Dialog`, `DialogTrigger`, `DialogPortal`, `DialogClose`, `DialogOverlay`, `DialogContent`; further helpers | Imported by `src/components/ui/command.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/drawer.tsx` | Reusable drawer UI template; outside product entrypoint import graph. | `Drawer`, `DrawerTrigger`, `DrawerPortal`, `DrawerClose`, `DrawerOverlay`, `DrawerContent`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/dropdown-menu.tsx` | Reusable dropdown menu UI template; outside product entrypoint import graph. | `DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuGroup`, `DropdownMenuPortal`, `DropdownMenuSub`, `DropdownMenuRadioGroup`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/form.tsx` | Reusable form UI template; outside product entrypoint import graph. | `Form`, `FormFieldContext`, `FormField`, `useFormField`, `fieldContext`, `itemContext`; further helpers | No product import found; Uses `src/components/ui/label.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/hover-card.tsx` | Reusable hover card UI template; outside product entrypoint import graph. | `HoverCard`, `HoverCardTrigger`, `HoverCardContent` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/input-otp.tsx` | Reusable input otp UI template; outside product entrypoint import graph. | `InputOTP`, `InputOTPGroup`, `InputOTPSlot`, `inputOTPContext`, `InputOTPSeparator` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/input.tsx` | Reusable input UI template; outside product entrypoint import graph. | `Input` | Imported by `src/components/ui/sidebar.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/label.tsx` | Reusable label UI template; outside product entrypoint import graph. | `labelVariants`, `Label` | Imported by `src/components/ui/form.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/menubar.tsx` | Reusable menubar UI template; outside product entrypoint import graph. | `MenubarMenu`, `MenubarGroup`, `MenubarPortal`, `MenubarRadioGroup`, `MenubarSub` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/navigation-menu.tsx` | Reusable navigation menu UI template; outside product entrypoint import graph. | `NavigationMenu`, `NavigationMenuList`, `NavigationMenuItem`, `navigationMenuTriggerStyle`, `NavigationMenuTrigger`, `NavigationMenuContent`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/pagination.tsx` | Reusable pagination UI template; outside product entrypoint import graph. | `Pagination`, `PaginationContent`, `PaginationItem`, `PaginationLink`, `PaginationPrevious`, `PaginationNext`; further helpers | No product import found; Uses `src/components/ui/button.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/popover.tsx` | Reusable popover UI template; outside product entrypoint import graph. | `Popover`, `PopoverTrigger`, `PopoverAnchor`, `PopoverContent` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/progress.tsx` | Reusable progress UI template; outside product entrypoint import graph. | `Progress` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/radio-group.tsx` | Reusable radio group UI template; outside product entrypoint import graph. | `RadioGroup`, `RadioGroupItem` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/resizable.tsx` | Reusable resizable UI template; outside product entrypoint import graph. | `ResizablePanelGroup`, `ResizablePanel`, `ResizableHandle` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/scroll-area.tsx` | Reusable scroll area UI template; outside product entrypoint import graph. | `ScrollArea`, `ScrollBar` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/select.tsx` | Reusable select UI template; outside product entrypoint import graph. | `Select`, `SelectGroup`, `SelectValue`, `SelectTrigger`, `SelectScrollUpButton`, `SelectScrollDownButton`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/separator.tsx` | Reusable separator UI template; outside product entrypoint import graph. | `Separator` | Imported by `src/components/ui/sidebar.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/sheet.tsx` | Reusable sheet UI template; outside product entrypoint import graph. | `Sheet`, `SheetTrigger`, `SheetClose`, `SheetPortal`, `SheetOverlay`, `sheetVariants`; further helpers | Imported by `src/components/ui/sidebar.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/sidebar.tsx` | Reusable sidebar UI template; outside product entrypoint import graph. | `useSidebar` | No product import found; Uses `src/components/ui/button.tsx`, `src/components/ui/input.tsx`, `src/components/ui/separator.tsx`, `src/components/ui/sheet.tsx` + 4 more |
| `FraudLens-2.0-Frontend/src/components/ui/skeleton.tsx` | Reusable skeleton UI template; outside product entrypoint import graph. | `Skeleton` | Imported by `src/components/ui/sidebar.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/slider.tsx` | Reusable slider UI template; outside product entrypoint import graph. | `Slider` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/sonner.tsx` | Reusable sonner UI template; outside product entrypoint import graph. | `Toaster` | No product import found |
| `FraudLens-2.0-Frontend/src/components/ui/switch.tsx` | Reusable switch UI template; outside product entrypoint import graph. | `Switch` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/table.tsx` | Reusable table UI template; outside product entrypoint import graph. | `Table`, `TableHeader`, `TableBody`, `TableFooter`, `TableRow`, `TableHead`; further helpers | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/tabs.tsx` | Reusable tabs UI template; outside product entrypoint import graph. | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/textarea.tsx` | Reusable textarea UI template; outside product entrypoint import graph. | `Textarea` | No product import found; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/toggle-group.tsx` | Reusable toggle group UI template; outside product entrypoint import graph. | `ToggleGroupContext`, `ToggleGroup`, `ToggleGroupItem`, `context` | No product import found; Uses `src/components/ui/toggle.tsx`, `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/toggle.tsx` | Reusable toggle UI template; outside product entrypoint import graph. | `toggleVariants`, `Toggle` | Imported by `src/components/ui/toggle-group.tsx`; Uses `src/lib/utils.ts` |
| `FraudLens-2.0-Frontend/src/components/ui/tooltip.tsx` | Reusable tooltip UI template; outside product entrypoint import graph. | `TooltipProvider`, `Tooltip`, `TooltipTrigger`, `TooltipContent` | Imported by `src/components/ui/sidebar.tsx`; Uses `src/lib/utils.ts` |

## Frontend clients, state, styling and configuration

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Frontend/.env.example` | Browser-safe build-time variable examples; never credentials. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/.gitignore` | Frontend generated/local configuration/cache exclusions. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/.nvmrc` | Local Node 22 version selection. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/.prettierignore` | Formatter generated/dependency exclusions. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/.prettierrc` | Code formatter settings. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/components.json` | Reusable UI generator configuration; does not activate the template collection. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/eslint.config.js` | Static lint settings and generated/build exclusions. | — | Imports `@eslint/js`, `eslint-plugin-prettier`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals` |
| `FraudLens-2.0-Frontend/package-lock.json` | Resolved npm dependency tree, including transitive version pins. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/package.json` | Explicit direct runtime/development dependencies, Node engine and npm commands. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/src/app-meta.json` | Active public SEO/title/social-preview metadata read by root route. | — | Imported by `src/routes/__root.tsx` |
| `FraudLens-2.0-Frontend/src/components/StructuredData.tsx` | Unconfirmed JSON-LD helper; no current route/component import found. | `StructuredData` | No product import found |
| `FraudLens-2.0-Frontend/src/experience/admin-workspace.css` | Active admin workspace styles imported by corresponding experience component. | — | Imported by `src/experience/Admin.tsx` |
| `FraudLens-2.0-Frontend/src/experience/after-apply.ts` | Active authored post-application copy; intent does not establish processing success. | `claimsAfterApply`, `underwritingAfterApply` | Imported by `src/experience/Agent.tsx` |
| `FraudLens-2.0-Frontend/src/experience/agent-evidence.ts` | Active authored evidence-card examples used by service presentations. | `reconEvidence`, `sentinelEvidence` | Imported by `src/experience/Agent.tsx` |
| `FraudLens-2.0-Frontend/src/experience/case-review.css` | Active case review styles imported by corresponding experience component. | — | Imported by `src/experience/CaseReview.tsx` |
| `FraudLens-2.0-Frontend/src/experience/customer-api.ts` | Active customer bearer fetch/error helpers and separate customer sessionStorage key. | `customerToken`, `clearCustomerSession`, `customerFetch`, `customerRequest`, `customerLogin`, `customerLogout` | Imported by `src/experience/CustomerSession.tsx`, `src/experience/Dashboard.tsx`, `src/experience/shared.tsx` |
| `FraudLens-2.0-Frontend/src/experience/customer-session.css` | Active customer session styles imported by corresponding experience component. | — | Imported by `src/experience/CustomerSession.tsx` |
| `FraudLens-2.0-Frontend/src/experience/enterprise.css` | Active enterprise styles imported by corresponding experience component. | — | Imported by `src/routes/__root.tsx` |
| `FraudLens-2.0-Frontend/src/experience/field-suggestions.css` | Active field suggestions styles imported by corresponding experience component. | — | Imported by `src/experience/FieldSuggestions.tsx` |
| `FraudLens-2.0-Frontend/src/experience/report-panel.css` | Active report panel styles imported by corresponding experience component. | — | Imported by `src/experience/ReportPanel.tsx` |
| `FraudLens-2.0-Frontend/src/experience/reportClient.ts` | Active reviewer report/version API client with bearer session, timeout and PDF binary response handling. | `reportVersions`, `prepareReport`, `fetchReportPdf`, `reportRequest` | Imported by `src/experience/ReportPanel.tsx` |
| `FraudLens-2.0-Frontend/src/experience/reviewPresentation.ts` | Active typed helpers for readable findings/status, money/dates and cautious assessment explanations. | `readable`, `reviewMoney`, `reviewDate`, `processingLabel`, `deskReviewSentences`, `applicationDetails`, `readableTimeline`, `firstStatement` | Imported by `src/experience/Admin.tsx`, `src/experience/CaseReview.tsx`, `src/experience/HistoricalReport.tsx` |
| `FraudLens-2.0-Frontend/src/experience/sampleSuggestions.ts` | Active fictional suggestion catalog and dependent vehicle field guidance. | `todayForInput`, `sampleSuggestions`, `vehicleDependencyWarning`, `normalized`, `dateBeforeToday` | Imported by `scripts/field-suggestions-harness.tsx`, `src/experience/FieldSuggestions.tsx`, `src/experience/Intake.tsx` |
| `FraudLens-2.0-Frontend/src/experience/user-dashboard.css` | Active user dashboard styles imported by corresponding experience component. | — | Imported by `src/experience/Dashboard.tsx` |
| `FraudLens-2.0-Frontend/src/hooks/use-card-hover.ts` | Active pointer hover effect installed by root route. | `useCardHover` | Imported by `src/routes/__root.tsx` |
| `FraudLens-2.0-Frontend/src/hooks/use-mobile.tsx` | Reusable UI-template breakpoint hook referenced by the unused sidebar template. | `useIsMobile` | Imported by `src/components/ui/sidebar.tsx` |
| `FraudLens-2.0-Frontend/src/hooks/use-scroll-reveal.ts` | Active observer-based scroll reveal with reduced-motion support installed by root route. | `useScrollReveal` | Imported by `src/routes/__root.tsx` |
| `FraudLens-2.0-Frontend/src/hooks/use-touch-highlight.ts` | Unconfirmed optional touch-effect hook; no current product import found. | `useTouchHighlight` | No product import found |
| `FraudLens-2.0-Frontend/src/lib/error-page.ts` | Active generic server HTML error helper. | `renderErrorPage` | Imported by `src/start.ts` |
| `FraudLens-2.0-Frontend/src/lib/security-headers.server.ts` | Active security-header/content-security-policy construction using configured API origin. | `applySecurityHeaders` | Imported by `src/server.ts` |
| `FraudLens-2.0-Frontend/src/lib/site-url.ts` | Active public-origin helper for metadata/canonical URLs/robots/sitemap. | `siteUrl` | Imported by `src/routes/__root.tsx`, `src/routes/about.tsx`, `src/routes/admin.tsx`, `src/routes/apply.claims.tsx` + 7 more |
| `FraudLens-2.0-Frontend/src/lib/utils.ts` | UI template cn utility using clsx/tailwind-merge; only reusable UI primitives import it. | `cn` | Imported by `src/components/ui/accordion.tsx`, `src/components/ui/alert-dialog.tsx`, `src/components/ui/alert.tsx`, `src/components/ui/avatar.tsx` + 39 more |
| `FraudLens-2.0-Frontend/src/routeTree.gen.ts` | Tracked generated TanStack route registry/types; retained as an essential small generated-source exception. | `routeTree` | Imported by `src/router.tsx`; Uses `src/router.tsx`, `src/routes/__root.tsx`, `src/routes/about.tsx`, `src/routes/admin.tsx` + 10 more |
| `FraudLens-2.0-Frontend/src/router.tsx` | Active TanStack Router creation, QueryClient context, scroll restoration and generated route registration. | `getRouter` | Imported by `src/routeTree.gen.ts`; Uses `src/routeTree.gen.ts` |
| `FraudLens-2.0-Frontend/src/server.ts` | Active server entry, trailing-slash redirect and HTTP security-header wrapper. | `url`, `m`, `handler` | Uses `src/lib/security-headers.server.ts` |
| `FraudLens-2.0-Frontend/src/start.ts` | Active TanStack Start server middleware returning generic HTML failure output. | `startInstance` | Imported by `src/routeTree.gen.ts`; Uses `src/lib/error-page.ts` |
| `FraudLens-2.0-Frontend/src/styles.css` | Active global/Tailwind styles imported by root route. | — | Imported by `src/routes/__root.tsx` |
| `FraudLens-2.0-Frontend/src/svg.d.ts` | Build-time SVG module typing for TypeScript/SVGR. | `Component` | Imports `react` |
| `FraudLens-2.0-Frontend/tsconfig.json` | TypeScript checking, JSX/module settings and path aliases. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/vercel.json` | Vercel TanStack Start framework hint; not deployment health evidence. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/vite.config.ts` | Active Vite/TanStack Start/React/Tailwind/SVGR configuration; Nitro is added for builds. | — | Imports `@tailwindcss/vite`, `@tanstack/react-start`, `@vitejs/plugin-react`, `nitro`, `vite` |

## Backend API and authentication

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/src/analysis_diagnostics.py` | Active sanitized operational error classification; no provider bodies, secrets or hidden reasoning. | `safe_message`, `failure_detail` | Imported by `scripts/recover_provider.py`, `src/agent/engine.py`, `src/agent/tools.py`, `src/api.py` + 4 more |
| `FraudLens-2.0-Backend/src/api.py` | Active FastAPI HTTP entrypoint: validation, reviewer authentication, intake, case/job/readiness endpoints and workflow installers. | `lifespan`, `require_admin`, `require_reviewer`, `submit_case`, `_run_pipeline`, `record_action`, `ready`, `health` | Imported by `scripts/export_api_contract.py`, `scripts/manage_reviewer.py`, `scripts/pilot_preflight.py`, `scripts/run_worker.py` + 13 more; Uses `scripts/drive_ablation.py`, `src/__init__.py`, `src/agent/policy.py`, `src/agent/production_policy.py` + 16 more |
| `FraudLens-2.0-Backend/src/customer_auth.py` | Active customer registration/login, bearer authentication, ownership enforcement and receipt-based historical linking; installed by API. | `install`, `authenticate`, `require_case`, `attach`, `register`, `login`, `link`, `detail` | Imported by `src/api.py`, `src/evidence_workflow.py`, `src/runtime_store.py`; Uses `src/__init__.py`, `src/api.py`, `src/db.py`, `src/models.py` + 1 more |
| `FraudLens-2.0-Backend/src/evidence_workflow.py` | Active supplementary evidence intake and reviewer organization/user routes, installed by API. | `install`, `submit_evidence`, `accounts`, `save_account` | Imported by `src/api.py`; Uses `src/__init__.py`, `src/api.py`, `src/customer_auth.py`, `src/db.py` + 3 more |

## Database and migrations

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/migrations/postgresql/001_initial.sql` | Initial domain/pilot PostgreSQL schema and constraints. | `claimants`, `cases`, `findings`, `perception_records`, `image_artifacts`, `agent_decisions`, `images`, `audit_log`; 12 more tables | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/migrations/postgresql/002_customer_workflow.sql` | Additive customer accounts/sessions/ownership and workflow migration. | `customer_accounts`, `customer_sessions`, `case_owners`, `report_artifacts` | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/db.py` | Active domain persistence and parameterized SQLite/PostgreSQL operations; SQLite schema initialization remains available. | `connect`, `init_db`, `session`, `insert_case`, `save_image`, `insert_finding`, `insert_agent_decision`, `log_audit_event` | Imported by `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/audit_analysis_history.py`, `scripts/audit_clean_labels.py` + 84 more; Uses `src/models.py`, `src/postgres.py` |
| `FraudLens-2.0-Backend/src/pg_migrations.py` | Explicit checksum-tracked transactional PostgreSQL install/upgrade and private grants; management-script entrypoint. | `checksum`, `versions`, `installed_versions`, `upgrade`, `schema_exists`, `install`; further helpers | Imported by `scripts/migrate_postgres.py`, `scripts/postgres_backup.py`, `scripts/prepare_analysis_rehearsal.py`, `scripts/upgrade_postgres.py` + 2 more |
| `FraudLens-2.0-Backend/src/postgres.py` | Active PostgreSQL pooling, compatible row/parameter bridge, schema validation and leadership support. | `Row`, `row_factory`, `parameters`, `schema_name`, `Connection`, `connect`; further helpers | Imported by `src/db.py`; Uses `src/pg_migrations.py` |
| `FraudLens-2.0-Backend/src/runtime_store.py` | Active durable queue, leases, immutable runs/reports, account/session persistence and human-decision concurrency. | `password_hash`, `password_matches`, `create_session`, `session_actor`, `enqueue`, `claim_next`, `fence` | Imported by `scripts/manage_reviewer.py`, `scripts/prepare_analysis_rehearsal.py`, `scripts/reprocess_history.py`, `scripts/run_worker.py` + 14 more; Uses `src/__init__.py`, `src/customer_auth.py`, `src/db.py`, `src/models.py` + 1 more |

## Evidence, processing, checks and agents

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/src/__init__.py` | Core package re-exports for domain dataclasses and enums. | — | Imported by `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/audit_analysis_history.py`, `scripts/audit_clean_labels.py` + 89 more; Uses `src/models.py` |
| `FraudLens-2.0-Backend/src/agent/__init__.py` | Agent public exports for common engine, policy and tools. | — | Imported by `src/agent/engine.py`, `test_durable_pilot.py`, `test_engine_reliability.py`, `test_postgres.py`; Uses `src/agent/engine.py`, `src/agent/policy.py`, `src/agent/tools.py` |
| `FraudLens-2.0-Backend/src/agent/engine.py` | Active bounded model/tool execution loop, parsed routing decision and recorded action trace; reused by research. | `AgentResponseSchemaError`, `TraceStep`, `AdjudicationResult`, `describe_case`, `build_messages`, `parse_decision`; further helpers | Imported by `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/run_ablation.py`, `scripts/verify_integration.py` + 7 more; Uses `src/__init__.py`, `src/agent/__init__.py`, `src/agent/policy.py`, `src/agent/tools.py` + 4 more |
| `FraudLens-2.0-Backend/src/agent/policy.py` | Shared policy dataclass and frozen research claims/underwriting prompts extended by production policy. | `AgentPolicy`, `policy_for` | Imported by `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/run_ablation.py`, `scripts/verify_integration.py` + 7 more |
| `FraudLens-2.0-Backend/src/agent/production_policy.py` | Active versioned production interpretation overrides, separate from frozen research prompts. | `production_policy_v1`, `production_policy_v2`, `production_policy` | Imported by `scripts/verify_check_inventory.py`, `scripts/verify_live_pilot.py`, `src/api.py`, `src/report_pdf.py` + 5 more; Uses `src/agent/policy.py` |
| `FraudLens-2.0-Backend/src/agent/tools.py` | Active allowed follow-up tools: similarity, claimant/garage history and perception requery. | `widen_similarity_search`, `get_claimant_history`, `get_garage_history`, `requery_perception`, `schemas_for`, `call_tool`; further helpers | Imported by `src/agent/__init__.py`, `src/agent/engine.py`, `test_agent.py`, `test_engine_reliability.py` + 1 more; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/db.py`, `src/ingest.py` + 2 more |
| `FraudLens-2.0-Backend/src/assessment_explanation.py` | Active frozen explanation of check parameters, execution status and routing basis; invents no production score. | `execution_state`, `rule_parameters`, `explain_assessment` | Imported by `src/orchestrator.py`, `test_assessment_explanation.py`, `test_report_pdf.py`; Uses `src/__init__.py`, `src/baseline.py`, `src/checks/__init__.py` |
| `FraudLens-2.0-Backend/src/baseline.py` | Research/control-arm weighted rules scorer; callable alternative, not the normal production risk formula. | `score_case`, `band_for`, `narrate`, `decide`, `run_case` | Imported by `scripts/run_ablation.py`, `scripts/run_baseline.py`, `src/assessment_explanation.py`, `src/orchestrator.py` + 3 more; Uses `src/checks/__init__.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/__init__.py` | Active registry population through explicit check imports; excludes retired vehicle consistency. | — | Imported by `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/analyse_check_correlation.py`, `scripts/evaluate_checks.py` + 27 more; Uses `src/checks/ai_detection.py`, `src/checks/base.py`, `src/checks/baseline_corruption.py`, `src/checks/baseline_linkage.py` + 12 more |
| `FraudLens-2.0-Backend/src/checks/ai_detection.py` | Registered local AI-image classifier; experimental, with zero baseline weight. | `get_pipeline`, `AIGenerationCheck` | Imported by `scripts/measure_ai_detector.py`, `src/checks/__init__.py`, `test_checks.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/base.py` | Active Check/CheckContext protocol, execution guards/timing and inconclusive error conversion. | `CheckContext`, `Check`, `register_check`, `run_checks` | Imported by `scripts/investigate_threshold_fp.py`, `scripts/measure_baseline_linkage.py`, `scripts/measure_baseline_signals.py`, `scripts/measure_entity_graph.py` + 26 more; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/db.py`, `src/models.py` + 2 more |
| `FraudLens-2.0-Backend/src/checks/baseline_corruption.py` | Registered experimental underwriting declaration comparison; weight zero and production forces inconclusive. | `BaselineCorruptionCheck` | Imported by `src/checks/__init__.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/baseline_linkage.py` | Registered claim linkage to prior underwriting baseline and chronology. | `BaselineLinkageCheck` | Imported by `src/checks/__init__.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/ingest.py` + 2 more |
| `FraudLens-2.0-Backend/src/checks/damage_plausibility.py` | Registered claim amount versus perceived damage severity rules. | `normalise_severity`, `worst_severity`, `DamagePlausibilityCheck` | Imported by `src/checks/__init__.py`, `test_checks.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/digital_edit.py` | Registered local JPEG/noise/edge edit heuristics; experimental and calibration dependent. | `get_calibration`, `ghost_score`, `noise_score`, `edge_score`, `analyse`, `DigitalEditCheck` | Imported by `scripts/measure_digital_edit.py`, `src/checks/__init__.py`, `test_checks.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/duplicate.py` | Registered internal reuse detection using exact/perceptual hashes and CLIP similarity. | `InternalDuplicateCheck` | Imported by `src/checks/__init__.py`, `test_demo_readiness.py`, `test_durable_pilot.py`, `test_postgres.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/ingest.py` + 1 more |
| `FraudLens-2.0-Backend/src/checks/entity_graph.py` | Registered garage/claimant/vehicle relationship analysis for collusion leads. | `EntityGraphCheck` | Imported by `src/checks/__init__.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/ingest.py` + 1 more |
| `FraudLens-2.0-Backend/src/checks/external_corpus.py` | Registered local reference-corpus comparison; evaluation simulation, not production reverse-image search. | `CorpusIndex`, `get_index`, `ExternalCorpusCheck` | Imported by `src/checks/__init__.py`, `test_checks.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/ingest.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/metadata.py` | Registered EXIF software/time/location comparison; missing metadata is neutral. | `MetadataCheck` | Imported by `src/checks/__init__.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/plate_ocr.py` | Registered EasyOCR plate extraction, normalization/comparison and versioned local cache. | `get_reader`, `normalise`, `coerce_to_plate`, `edit_distance`, `PlateOCRCheck` | Imported by `scripts/run_worker.py`, `scripts/verify_ocr_cache.py`, `scripts/verify_readable_plate.py`, `src/checks/__init__.py` + 3 more; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/models.py` + 1 more |
| `FraudLens-2.0-Backend/src/checks/provenance.py` | Registered optional C2PA signed provenance inspection; absence remains inconclusive. | `C2PACheck` | Imported by `src/checks/__init__.py`, `test_checks.py`, `test_engine_reliability.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/retired/__init__.py` | Legacy/retired package marker; excluded from current check registry. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/checks/retired/vehicle_consistency.py` | Legacy/retired embedding experiment; no current registration or execution. | `VehicleConsistencyCheck` | Imported by `test_checks.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/scene_consistency.py` | Registered solar/shadow and cached historical-weather consistency checks. | `local_wallclock_to_utc`, `solar_position`, `bearing_to_compass`, `compass_to_bearing`, `angular_difference`, `expected_shadow_length`; further helpers | Imported by `src/checks/__init__.py`, `test_checks.py`, `test_demo_readiness.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/checks/severity_progression.py` | Registered cross-claim damage chronology and repair consistency. | `SeverityProgressionCheck` | Imported by `src/checks/__init__.py`, `test_severity_chronology.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/ingest.py` + 2 more |
| `FraudLens-2.0-Backend/src/checks/threshold.py` | Registered garage-level threshold clustering; not individual proof of fraud. | `ThresholdGamingCheck` | Imported by `src/checks/__init__.py`, `test_checks.py`; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py`, `src/ingest.py` + 1 more |
| `FraudLens-2.0-Backend/src/checks/view_completeness.py` | Registered experimental zero-weight view/embedding check, selected by neither production policy; slot labels do not establish same-vehicle identity. | `ViewCompletenessCheck` | Imported by `scripts/measure_view_completeness.py`, `src/checks/__init__.py`; Uses `src/checks/base.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/durable_worker.py` | Active job worker: leadership, ownership fencing, polling, retries and restart recovery. | `DurableWorker`, `start`, `_loop`, `_postgres_loop`, `stop` | Imported by `scripts/run_worker.py`, `src/api.py`, `test_durable_pilot.py`, `test_postgres.py`; Uses `src/__init__.py`, `src/db.py`, `src/runtime_store.py` |
| `FraudLens-2.0-Backend/src/ingest.py` | Active SHA-256/perceptual hashes, CLIP embeddings, EXIF, image persistence and corpus similarity. | `compute_sha256`, `compute_hashes`, `hamming_distance`, `CLIPEmbedder`, `cosine_similarity`, `extract_exif`; further helpers | Imported by `scripts/pilot_preflight.py`, `scripts/profile_similarity.py`, `src/agent/tools.py`, `src/api.py` + 16 more; Uses `src/__init__.py`, `src/db.py`, `src/models.py`, `src/timing.py` |
| `FraudLens-2.0-Backend/src/llm.py` | Active provider abstraction: Gemini call path, optional Ollama HTTP adapter, quota/session guards and usage accounting. | `usage_stats`, `reset_key_state`, `ToolCall`, `LLMResponse`, `LLMProvider`, `get_provider`; further helpers | Imported by `scripts/_await_quota_smoke.py`, `scripts/ab_test_prompt.py`, `scripts/agent_smoke_test.py`, `scripts/benchmark_perception.py` + 17 more; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/db.py`, `src/quota_budget.py` + 1 more |
| `FraudLens-2.0-Backend/src/models.py` | Active shared dataclasses/enums for cases, images, findings, perceptions, routing decisions and human actions. | `CheckCategory`, `Verdict`, `Recommendation`, `AdminAction`, `RiskBand`, `Finding`; further helpers | Imported by `scripts/agent_smoke_test.py`, `scripts/backfill_findings.py`, `scripts/benchmark_perception.py`, `scripts/evaluate_checks.py` + 57 more |
| `FraudLens-2.0-Backend/src/orchestrator.py` | Active case checks, routing decision and audit persistence; supports alternate research baseline execution. | `adjudication_event`, `process_case`, `already_decided`, `process_all`, `parse_args`, `main` | Imported by `scripts/run_ablation.py`, `scripts/verify_integration.py`, `src/api.py`, `test_api.py` + 5 more; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/assessment_explanation.py` + 7 more |
| `FraudLens-2.0-Backend/src/perception.py` | Active structured vision-provider perception, schema validation and hash-keyed cache; also has research batch CLI. | `PerceptionSchemaError`, `perception_record_usable`, `log_failure`, `parse_stats`, `perceive_image`, `select_stratified`; further helpers | Imported by `scripts/audit_analysis_history.py`, `scripts/benchmark_perception.py`, `scripts/find_working_model.py`, `scripts/reprocess_history.py` + 12 more; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/checks/__init__.py`, `src/db.py` + 2 more |
| `FraudLens-2.0-Backend/src/quota_budget.py` | Active daily provider-attempt reservation budget shared across consumers. | `QuotaBudgetExhausted`, `pacific_quota_day`, `state_path`, `daily_per_key`, `infer_consumer`, `reserve_call`; further helpers | Imported by `src/llm.py`, `src/session_budget.py`, `test_analysis_recovery.py`, `test_durable_pilot.py` |
| `FraudLens-2.0-Backend/src/session_budget.py` | Active persisted session stop and explicit bounded recovery/validation allowances surviving restarts. | `ProviderCircuitOpen`, `authorize_recovery`, `authorize_validation`, `check`, `reserve`, `outcome` | Imported by `scripts/recover_provider.py`, `src/llm.py`, `test_analysis_recovery.py`, `test_durable_pilot.py`; Uses `src/quota_budget.py` |
| `FraudLens-2.0-Backend/src/storage_health.py` | Active private evidence directory read/write readiness checks; no provider endpoint calls. | `check_storage_ready` | Imported by `src/api.py`, `test_deployment_storage.py` |
| `FraudLens-2.0-Backend/src/timing.py` | Active optional content-free timing spans and memory telemetry. | `measured`, `windows_memory`, `span` | Imported by `scripts/profile_local_ocr.py`, `scripts/verify_readable_plate.py`, `src/api.py`, `src/checks/base.py` + 4 more |
| `FraudLens-2.0-Backend/src/vehicle_gate.py` | Active local CLIP admission check for likely vehicle content, separate from provider perception. | `VehicleGateScore`, `classify_image`, `classify_uploads` | Imported by `src/api.py`, `test_api.py`, `test_durable_pilot.py`, `test_pilot_workflow.py` + 1 more; Uses `src/ingest.py`, `src/timing.py` |

## Reports

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/src/report_pdf.py` | Active immutable report enrichment, ReportLab rendering, database PDF versions and protected report routes. | `enrich_snapshot`, `render_pdf`, `install`, `list_reports`, `prepare_report`, `download_report` | Imported by `src/api.py`, `src/runtime_store.py`, `test_report_pdf.py`; Uses `src/__init__.py`, `src/agent/production_policy.py`, `src/api.py`, `src/checks/__init__.py` + 2 more |

## Scripts and operational tooling

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/scripts/__init__.py` | Tooling package marker for python -m scripts… imports. | — | Imported by `test_deployment_storage.py`, `test_reprocess_history.py`, `test_verify_live_analysis.py` |
| `FraudLens-2.0-Backend/scripts/_await_quota_smoke.py` | Research utility: Wait for the free-tier quota window to roll over, then run the smoke test. Explicit CLI, outside request/worker startup. | `quota_available`, `main` | Explicit CLI only; Uses `src/llm.py` |
| `FraudLens-2.0-Backend/scripts/ab_test_prompt.py` | Research utility: A/B the underwriting prompt's "an all-clear set of findings is weak evidence" paragraph. Explicit CLI, outside request/worker startup. | `build_variant_b`, `policy_for_variant`, `load_done`, `load_rows`, `main`, `write_report` | Explicit CLI only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/checks/__init__.py` + 3 more |
| `FraudLens-2.0-Backend/scripts/agent_smoke_test.py` | Research utility: Smoke-test the agent on real cases with real quota. Explicit CLI, outside request/worker startup. | `select_cases`, `main`, `write_report` | Explicit CLI only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/checks/__init__.py` + 3 more |
| `FraudLens-2.0-Backend/scripts/analyse_check_correlation.py` | Research utility: Do the checks fire independently, or does the weighted sum double-count? Explicit CLI, outside request/worker startup. | `load`, `phi`, `main` | Explicit CLI only; Uses `src/checks/__init__.py` |
| `FraudLens-2.0-Backend/scripts/apply_post_ablation_patches.py` | Research utility: Apply the two changes that are queued behind the ablation. Explicit CLI, outside request/worker startup. | `agent_progress`, `apply`, `main` | Explicit CLI only; Imports `io`, `subprocess` |
| `FraudLens-2.0-Backend/scripts/archive_superseded.py` | Research utility: Move superseded documents into outputs/archive/ with a header saying so. Explicit CLI, outside request/worker startup. | `main` | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/assemble_report.py` | Research utility: Assemble outputs/report_full_draft.md from the section drafts. Explicit CLI, outside request/worker startup. | `read`, `strip_preamble`, `figure_block`, `insert_figures`, `renumber`, `words`; further helpers | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/audit_analysis_history.py` | Read-only history audit producing new private manifests; not run for this guide. | `audit`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/perception.py` |
| `FraudLens-2.0-Backend/scripts/audit_clean_labels.py` | Research utility: Audit every CLEAN case for evidence that it is not clean. Explicit CLI, outside request/worker startup. | `get_reader`, `load_cache`, `ocr_image`, `main`, `write_report` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/sampling.py` |
| `FraudLens-2.0-Backend/scripts/audit_corpus_geography.py` | Research utility: Audit the CLEAN corpus for imagery that is not consistent with an honest Indian motor claim. Explicit CLI, outside request/worker startup. | `main`, `write_report` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/audit_evidence_paths.py` | Read-only evidence reconciliation; not run for this guide. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/audit_numbers.py` | Research utility: Audit every load-bearing number in outputs/ against its source artefact. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `claim_corpus_size`, `claim_duplicate_fp`, `claim_threshold_fp`, `claim_corpus_defects`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/backfill_findings.py` | Research utility: Load the cached findings into the database. Explicit CLI, outside request/worker startup. | `parse_dt`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/scripts/benchmark_perception.py` | Research utility: Times the vision API on a handful of never-before-perceived images to find the real achievable throughput, before src/perception.py's full ~1,326-image pass gets scheduled. Two things distinguish… Explicit CLI, outside request/worker startup. | `resolve_db_path`, `summarize`, `print_summary`, `parse_args`, `main` | Imported by `scripts/find_working_model.py`; Uses `src/__init__.py`, `src/db.py`, `src/llm.py`, `src/models.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/build_report_draft.py` | Research utility: Draft the report's Results and Discussion sections. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `v2_table`, `paired_ablation`, `pct`, `main` | Explicit CLI only; Imports `csv` |
| `FraudLens-2.0-Backend/scripts/build_report_limitations.py` | Research utility: Draft the report's Limitations section. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `perception_stats`, `paired`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/build_report_methodology.py` | Research utility: Draft the report's Methodology section. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `corpus_counts`, `agent_cost`, `main` | Explicit CLI only; Imports `csv` |
| `FraudLens-2.0-Backend/scripts/build_results_summary.py` | Research utility: Build outputs/results_summary.md — the report's evidence base. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `v2_table`, `main` | Explicit CLI only; Imports `csv` |
| `FraudLens-2.0-Backend/scripts/drive_ablation.py` | Research utility: Drive the ablation's agent arm to completion across quota days. Explicit CLI, outside request/worker startup. | `IntegrityResult`, `verify_agent_integrity`, `agent_done`, `total_cases`, `main` | Imported by `src/api.py`; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/evaluate_checks.py` | Research utility: Scores src/checks against the synthetic corpus's ground truth. Reads data/generated/ground_truth.csv (the answer key) and fraudlens.db (what the checks actually see) - see… Explicit CLI, outside request/worker startup. | `resolve_db_path`, `load_ground_truth`, `evaluate_duplicate`, `print_report`, `target_archetypes_for`, `evaluate_check`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/scripts/export_api_contract.py` | Tooling OpenAPI/reference export using isolated API instance; not run. | `truncate`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/api.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/find_working_model.py` | Research utility: Surveys several Gemini model names in one pass to find which one actually has usable free-tier quota today, before src/perception.py's full ~1,326- image pass gets scheduled against whichever… Explicit CLI, outside request/worker startup. | `survey_model`, `print_table`, `print_recommendation`, `main` | Explicit CLI only; Uses `scripts/benchmark_perception.py`, `src/__init__.py`, `src/db.py`, `src/llm.py` + 2 more |
| `FraudLens-2.0-Backend/scripts/inject_baseline_linkage.py` | Research utility: Link underwriting inspections to later claims, in a COPY of the database. Explicit CLI, outside request/worker startup. | `worst_severity`, `main` | Explicit CLI only; Imports `csv` |
| `FraudLens-2.0-Backend/scripts/inject_collusion_ring.py` | Research utility: Inject a labelled collusion ring into a COPY of the database. Explicit CLI, outside request/worker startup. | `add_columns`, `main` | Explicit CLI only; Imports `csv` |
| `FraudLens-2.0-Backend/scripts/inject_repeat_claims.py` | Research utility: Inject repeat-claim sequences into a COPY of the database. Explicit CLI, outside request/worker startup. | `worst_severity`, `main` | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/inspect_dataset.py` | Research utility: Diagnostic script for the synthetic case corpus, run once before any check gets built. Its only job is to answer "did generate_dataset.py actually produce the signals the checks are supposed to… Explicit CLI, outside request/worker startup. | `resolve_db_path`, `load_ground_truth`, `report_garage_gaming`, `report_archetype_health`, `report_image_integrity`, `report_resolution_distribution`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/investigate_threshold_fp.py` | Research utility: Why does threshold_gaming flag 22.2% of clean claims? Explicit CLI, outside request/worker startup. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/base.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/leave_one_out.py` | Research utility: Per-check marginal contribution: what does each check add that the others do not? Explicit CLI, outside request/worker startup. | `load_findings`, `operating_point`, `score`, `evaluate`, `main` | Explicit CLI only; Uses `src/checks/__init__.py` |
| `FraudLens-2.0-Backend/scripts/make_figures.py` | Research utility: Generate the report's figures into outputs/figures/. Explicit CLI, outside request/worker startup. | `read_json`, `read_jsonl`, `save`, `figure_recall_by_archetype`, `figure_recall_progression`, `figure_false_positives`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/manage_reviewer.py` | Operational database reviewer/admin/viewer provisioning with interactive passwords; writes if run. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/api.py`, `src/db.py`, `src/models.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/measure_ai_detector.py` | Research utility: Measure the AI detector against genuinely AI-generated images. Explicit CLI, outside request/worker startup. | `bucket_for`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/ai_detection.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/measure_baseline_corruption.py` | Research utility: Measure `baseline_corruption` against its target archetype only. Explicit CLI, outside request/worker startup. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/scripts/measure_baseline_linkage.py` | Research utility: Measure baseline_linkage against the linked scenario database. Explicit CLI, outside request/worker startup. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/base.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/measure_baseline_signals.py` | Research utility: Can anything detect AI_GENERATED_BASELINE? Explicit CLI, outside request/worker startup. | `auc`, `describe`, `compression_profile`, `linkage_signal`, `forensic_signal`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/base.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/measure_digital_edit.py` | Research utility: Measure the digital-edit forensics against ground truth, then set the threshold from what was measured. Explicit CLI, outside request/worker startup. | `load_ground_truth`, `auc`, `threshold_at_fp_rate`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/digital_edit.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/measure_digital_edit_localised.py` | Research utility: Localised JPEG-ghost / noise / edge forensics for digital_edit. Explicit CLI, outside request/worker startup. | `frame_maps`, `propose_regions`, `score_regions`, `iou`, `auc`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/measure_duplicate.py` | Research utility: Re-measure internal_duplicate after the submission-order change. Explicit CLI, outside request/worker startup. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/scripts/measure_entity_graph.py` | Research utility: Measure entity_graph on the production corpus and on the injected ring. Explicit CLI, outside request/worker startup. | `evaluate`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/base.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/measure_severity_progression.py` | Research utility: Measure severity_progression against injected repeat-claim sequences. Explicit CLI, outside request/worker startup. | `verdicts_for`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/measure_view_completeness.py` | Research utility: Measure view_completeness, component by component. Explicit CLI, outside request/worker startup. | `auc`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/view_completeness.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/migrate_postgres.py` | Operational default-dry-run SQLite-to-new-schema migration; explicit apply writes. | `digest_rows`, `source_snapshot`, `inventory`, `source_digest`, `validate`, `apply`; further helpers | Imported by `scripts/postgres_backup.py`, `test_postgres.py`; Uses `src/__init__.py`, `src/db.py`, `src/pg_migrations.py` |
| `FraudLens-2.0-Backend/scripts/normalise_ai_images.py` | Research utility: Normalise the AI-generated source images to match the rest of the corpus. Explicit CLI, outside request/worker startup. | `corpus_short_sides`, `load_manifest`, `save_manifest`, `match_resolution`, `convert`, `verify`; further helpers | Explicit CLI only; Imports `PIL`, `statistics` |
| `FraudLens-2.0-Backend/scripts/partial_ablation.py` | Research utility: Partial ablation — a defensible comparison from an incomplete agent arm. Explicit CLI, outside request/worker startup. | `load_rows`, `load_exclusions`, `is_outage`, `flagged`, `bootstrap_recall_difference`, `cell_stats`; further helpers | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/pilot_backup.py` | Operational SQLite/filesystem backup and non-overwriting restore; private outputs. | `snapshot_database`, `backup`, `restore` | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/pilot_preflight.py` | Operational preflight; --live spends a provider call. Not run for this guide. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/api.py`, `src/db.py`, `src/ingest.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/plan_ablation.py` | Research utility: Generate outputs/ablation_plan.md from live corpus state. Explicit CLI, outside request/worker startup. | `wilson_halfwidth`, `main`, `write_report` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/postgres_backup.py` | Operational repeatable-read logical backup/non-overwriting restore drill; private outputs. | `backup`, `restore`, `main` | Imported by `test_postgres.py`; Uses `scripts/migrate_postgres.py`, `src/__init__.py`, `src/db.py`, `src/pg_migrations.py` |
| `FraudLens-2.0-Backend/scripts/prepare_analysis_rehearsal.py` | Operational isolated private PostgreSQL namespace creation; not run. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/pg_migrations.py`, `src/runtime_store.py` |
| `FraudLens-2.0-Backend/scripts/profile_demo_http.py` | Tooling isolated real submissions for admission timing; retained cases are written if run. | `main` | Explicit CLI only; Imports `httpx`, `uuid` |
| `FraudLens-2.0-Backend/scripts/profile_local_ocr.py` | Tooling real local OCR timing without provider; execution is not accuracy evidence. | `main` | Explicit CLI only; Uses `src/timing.py` |
| `FraudLens-2.0-Backend/scripts/profile_similarity.py` | Tooling read-only full-corpus similarity timing/equivalence observation. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/ingest.py` |
| `FraudLens-2.0-Backend/scripts/recover_provider.py` | Operational bounded recovery provider probe through guards; not run, never resets original stop. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/llm.py`, `src/session_budget.py` |
| `FraudLens-2.0-Backend/scripts/refresh_all.py` | Research utility: Regenerate every derived artefact from live data, in dependency order. Explicit CLI, outside request/worker startup. | `agent_effort`, `refresh_demo_effort`, `main` | Explicit CLI only; Imports `subprocess` |
| `FraudLens-2.0-Backend/scripts/regenerate_preserving_perception.py` | Research utility: Regenerate the corpus without throwing away paid-for perception. Explicit CLI, outside request/worker startup. | `perception_pass_running`, `export_perception`, `restore_perception`, `main` | Explicit CLI only; Imports `subprocess` |
| `FraudLens-2.0-Backend/scripts/report_v2.py` | Research utility: Build outputs/check_performance_v2.md from the cached findings. Explicit CLI, outside request/worker startup. | `load_ground_truth`, `load_findings`, `perceived_cases`, `evaluate`, `fmt_rate`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/reprocess_history.py` | Blocked retrospective plan/apply utility gated by real workflow proof and provider budget. | `read_json`, `write_json`, `run_id`, `records_from`, `budget_remaining`, `validation_gate`; further helpers | Imported by `scripts/verify_live_analysis.py`, `test_reprocess_history.py`; Uses `src/__init__.py`, `src/db.py`, `src/models.py`, `src/perception.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/run_ablation.py` | Research utility: The ablation: LLM agent vs rules-only baseline, same cases, same findings. Explicit CLI, outside request/worker startup. | `load_exclusions`, `load_or_freeze_sample`, `interleave_by_archetype`, `is_outage_row`, `has_fallback_trace`, `log_failure`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/baseline.py` + 6 more |
| `FraudLens-2.0-Backend/scripts/run_baseline.py` | Research utility: Run the rules-only baseline across every case and report it honestly. Explicit CLI, outside request/worker startup. | `load_ground_truth`, `gaming_garages`, `collect_findings`, `load_cached_findings`, `rehydrate`, `raw_scores`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/baseline.py`, `src/checks/__init__.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Backend/scripts/run_worker.py` | Active worker CLI with CPU/OCR warmup before leadership. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/api.py`, `src/checks/plate_ocr.py`, `src/db.py` + 2 more |
| `FraudLens-2.0-Backend/scripts/staged_regeneration.py` | Research utility: Regenerate the production corpus — gated, backed up, and verified. Explicit CLI, outside request/worker startup. | `agent_progress`, `snapshot`, `export_perception`, `restore_perception`, `assert_guarantees`, `main`; further helpers | Explicit CLI only; Imports `csv`, `subprocess` |
| `FraudLens-2.0-Backend/scripts/start_deployment.py` | Active single-host PostgreSQL/private-volume deployment wrapper requiring preserved ledgers. | `configure`, `main` | Imported by `test_deployment_storage.py` |
| `FraudLens-2.0-Backend/scripts/start_pilot.ps1` | Local PostgreSQL/SQLite bootstrap with preserved provider ledgers, private storage and API/worker modes. | — | Explicit CLI only |
| `FraudLens-2.0-Backend/scripts/upgrade_postgres.py` | Operational checksum inspection/additive upgrade utility; apply writes. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/db.py`, `src/pg_migrations.py` |
| `FraudLens-2.0-Backend/scripts/verify_api_contract.py` | Tooling isolated HTTP contract verification; not run. | `check`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/api.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/verify_browser_pilot.py` | Tooling real two-tab isolated rehearsal; can write cases/use provider failure paths. | `record`, `poll_job`, `admin_action`, `fill_intake`, `open_case`, `track`; further helpers | Explicit CLI only; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/verify_check_inventory.py` | Tooling checks on isolated copies with uncached external lookups disabled. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/agent/production_policy.py`, `src/checks/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/verify_integration.py` | Tooling isolated end-to-end seams with stub adjudication; not live AI proof. | `check`, `corpus_vehicle_image`, `stub_adjudicate`, `main` | Imported by `test_integration.py`; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/api.py` + 4 more |
| `FraudLens-2.0-Backend/scripts/verify_live_analysis.py` | Tooling saved-real-run readback for retrospective proof gate; no model request itself. | `VerificationError`, `require`, `decoded`, `references`, `read_saved`, `timestamp`; further helpers | Imported by `test_verify_live_analysis.py`; Uses `scripts/reprocess_history.py`, `src/__init__.py`, `src/db.py`, `src/perception.py` |
| `FraudLens-2.0-Backend/scripts/verify_live_pilot.py` | Tooling bounded live Gemini probe on isolated copy; not run. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/production_policy.py`, `src/api.py` + 4 more |
| `FraudLens-2.0-Backend/scripts/verify_ocr_cache.py` | Tooling isolated real local OCR/cache reuse; no detection accuracy claim. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/base.py`, `src/checks/plate_ocr.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/verify_offline_suite.py` | Tooling suite runner preserving exits and disabling live integration; no accuracy claim. | `main` | Explicit CLI only; Imports `subprocess` |
| `FraudLens-2.0-Backend/scripts/verify_postgres_checks.py` | Tooling SQLite/PostgreSQL storage-check equivalence on preserved records. | `canonical`, `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/base.py`, `src/db.py` |
| `FraudLens-2.0-Backend/scripts/verify_presentation_browser.py` | Tooling isolated browser/API/upload/worker/PDF acceptance; not run. | `record`, `headers`, `customer_signin`, `admin_signin`, `sample`, `intake`; further helpers | Explicit CLI only; Imports `fitz`, `httpx`, `playwright`, `pypdf`, `secrets` |
| `FraudLens-2.0-Backend/scripts/verify_readable_plate.py` | Tooling local OCR/cache/comparison on existing research image; no general accuracy claim. | `main` | Explicit CLI only; Uses `src/__init__.py`, `src/checks/base.py`, `src/checks/plate_ocr.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Frontend/scripts/field-suggestions-harness.tsx` | Tooling standalone React suggestion-behavior fixture. | `Harness` | Uses `src/experience/FieldSuggestions.tsx`, `src/experience/sampleSuggestions.ts` |
| `FraudLens-2.0-Frontend/scripts/field-suggestions.vite.ts` | Tooling Vite configuration serving the suggestion harness. | — | Imports `@vitejs/plugin-react`, `vite` |
| `FraudLens-2.0-Frontend/scripts/hash-password.mjs` | Legacy ADMIN_PASSWORD_SHA256 helper behind npm admin:password; not current reviewer provisioning. | `rl`, `password` | Imports `node:crypto`, `node:readline` |
| `FraudLens-2.0-Frontend/scripts/node22.ps1` | Local Node 22 command wrapper for frontend tooling. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/scripts/verify_admin_review.py` | Tooling fixture-based browser checks for reviewer layout, report and action behavior. | `case_fixture`, `Fixtures`, `open_case`, `verify_layout`, `run` | Imports `copy`, `io`, `playwright`, `reportlab`, `traceback` |
| `FraudLens-2.0-Frontend/scripts/verify_analysis_browser.py` | Tooling isolated browser customer/reviewer analysis verification. | `run` | Imports `httpx`, `importlib`, `playwright`, `pypdf`, `traceback` |
| `FraudLens-2.0-Frontend/scripts/verify_field_suggestions.py` | Tooling browser checks for suggestions, dependencies and form behavior. | `open_fixture`, `run` | Imports `playwright` |
| `FraudLens-2.0-Frontend/scripts/verify_session_transports.py` | Tooling browser checks for separate customer/reviewer sessionStorage bearer transports. | `compiled_clients`, `run` | Imports `playwright`, `subprocess` |

## Tests and verification sources

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/test_agent.py` | Verification source for agent; assertions/fixtures inspected only, not executed for this guide. | `test_rejection_attempt_is_coerced_to_escalation`, `test_rejection_detector_covers_the_obvious_phrasings`, `test_loop_terminates_on_a_final_answer`, `test_tool_call_executes_and_feeds_back`; further assertions | Test runner only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py`, `src/agent/tools.py` + 3 more |
| `FraudLens-2.0-Backend/test_analysis_recovery.py` | Verification source for analysis recovery; assertions/fixtures inspected only, not executed for this guide. | `test_circuit_and_http_failure_are_distinct`, `test_one_failed_probe_retains_original_stop_and_blocks_repeats`, `test_probe_success_requires_separate_bounded_validation`, `test_quota_access_or_configuration_cannot_receive_transient_probe`; further assertions | Test runner only; Uses `src/__init__.py`, `src/analysis_diagnostics.py`, `src/llm.py`, `src/quota_budget.py` + 2 more |
| `FraudLens-2.0-Backend/test_api.py` | Verification source for api; assertions/fixtures inspected only, not executed for this guide. | `test_list_returns_all_cases_with_summary_fields`, `test_filter_by_agent_type`, `test_filter_by_risk_band`, `test_filter_by_archetype_and_status`; further assertions | Test runner only; Uses `src/__init__.py`, `src/agent/engine.py`, `src/api.py`, `src/db.py` + 3 more |
| `FraudLens-2.0-Backend/test_assessment_explanation.py` | Verification source for assessment explanation; assertions/fixtures inspected only, not executed for this guide. | `test_baseline_explanation_matches_existing_arithmetic_without_deduplicating`, `test_agent_explanation_has_no_arbitrary_score_or_numeric_contributions`, `test_rule_parameters_freeze_actual_overrides_and_observations_are_detached`, `test_missing_failed_not_applicable_and_experimental_never_become_passes`; further assertions | Test runner only; Uses `src/__init__.py`, `src/agent/production_policy.py`, `src/api.py`, `src/assessment_explanation.py` + 7 more |
| `FraudLens-2.0-Backend/test_baseline.py` | Verification source for baseline; assertions/fixtures inspected only, not executed for this guide. | `test_concern_contributes_weight_times_confidence`, `test_inconclusive_and_pass_contribute_exactly_zero`, `test_demoted_check_cannot_move_the_score`, `test_retired_check_findings_are_ignored`; further assertions | Test runner only; Uses `src/__init__.py`, `src/baseline.py`, `src/models.py` |
| `FraudLens-2.0-Backend/test_checks.py` | Verification source for checks; assertions/fixtures inspected only, not executed for this guide. | `test_duplicate_check_fires_concern_on_a_known_reuse_case`, `test_duplicate_check_passes_on_a_known_clean_case`, `test_duplicate_check_reuse_vs_clean_sweep`, `test_metadata_check_no_exif_is_inconclusive_not_concern`; further assertions | Test runner only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/ai_detection.py`, `src/checks/base.py` + 10 more |
| `FraudLens-2.0-Backend/test_customer_workflow.py` | Verification source for customer workflow; assertions/fixtures inspected only, not executed for this guide. | `test_registration_password_session_expiry_and_independent_roles`, `test_owned_workflow_decision_visibility_and_privacy`, `test_idempotency_ownership_rollback_and_no_email_inheritance`, `test_manual_override_stale_basis_and_rejection_public_reason`; further assertions | Test runner only; Imported by `test_postgres.py`; Uses `src/__init__.py`, `src/api.py`, `src/db.py`, `src/runtime_store.py` + 1 more |
| `FraudLens-2.0-Backend/test_demo_readiness.py` | Verification source for demo readiness; assertions/fixtures inspected only, not executed for this guide. | `test_scene_missing_context_never_passes`, `test_selected_context_pattern_does_not_invent_a_contradiction`, `test_production_scene_uses_recorded_instant_without_second_timezone_shift`, `test_production_unverified_time_basis_abstains_without_lookups`; further assertions | Test runner only; Uses `src/__init__.py`, `src/checks/__init__.py`, `src/checks/base.py`, `src/checks/duplicate.py` + 7 more |
| `FraudLens-2.0-Backend/test_deployment_storage.py` | Verification source for deployment storage; assertions/fixtures inspected only, not executed for this guide. | `test_deployment_refuses_sqlite_fallback_and_missing_volume`, `test_deployment_requires_preserved_ledgers_and_exact_https_origins`, `test_readiness_refuses_paths_outside_declared_volume` | Test runner only; Uses `scripts/__init__.py`, `scripts/start_deployment.py`, `src/storage_health.py` |
| `FraudLens-2.0-Backend/test_durable_pilot.py` | Verification source for durable pilot; assertions/fixtures inspected only, not executed for this guide. | `test_evidence_resubmission_and_history`, `test_evidence_capability_scope`, `test_supplementary_failure_is_atomic`, `test_specific_request_and_stale_human_decision`; further assertions | Test runner only; Imported by `test_postgres.py`; Uses `src/__init__.py`, `src/agent/__init__.py`, `src/agent/engine.py`, `src/agent/production_policy.py` + 17 more |
| `FraudLens-2.0-Backend/test_engine_reliability.py` | Verification source for engine reliability; assertions/fixtures inspected only, not executed for this guide. | `test_failed_cache_can_recover_and_valid_cache_avoids_a_new_call`, `test_schema_retry_releases_optional_cache_write_before_next_generation`, `test_invalid_json_schema_is_persisted_as_failure_and_never_used_by_checks`, `test_schema_failure_separates_cached_responses_from_network_attempts`; further assertions | Test runner only; Uses `src/__init__.py`, `src/agent/__init__.py`, `src/agent/engine.py`, `src/agent/policy.py` + 12 more |
| `FraudLens-2.0-Backend/test_ingest.py` | Verification source for ingest; assertions/fixtures inspected only, not executed for this guide. | `test_sha256_is_stable_across_calls`, `test_phash_survives_resave_and_resize`, `test_embedding_is_512dim_and_unit_norm`, `test_cosine_similarity_self_vs_different_image`; further assertions | Test runner only; Uses `src/__init__.py`, `src/db.py`, `src/ingest.py`, `src/models.py` |
| `FraudLens-2.0-Backend/test_integration.py` | Verification source for integration; assertions/fixtures inspected only, not executed for this guide. | `run_all` | Test runner only; Uses `scripts/verify_integration.py` |
| `FraudLens-2.0-Backend/test_llm.py` | Verification source for llm; assertions/fixtures inspected only, not executed for this guide. | `test_provider_initializes_and_finds_api_key`, `test_chat_returns_nonempty_response`, `test_repeated_chat_hits_the_cache`, `test_usage_stats_reports_correctly`; further assertions | Test runner only; Imported by `test_analysis_recovery.py`; Uses `src/__init__.py`, `src/db.py`, `src/llm.py` |
| `FraudLens-2.0-Backend/test_models.py` | Verification source for models; assertions/fixtures inspected only, not executed for this guide. | `test_verdict_has_exactly_three_values`, `test_recommendation_has_no_reject_value`, `test_recommendation_values`, `test_admin_action_is_distinct_and_can_reject`; further assertions | Test runner only; Uses `src/__init__.py`, `src/db.py`, `src/models.py` |
| `FraudLens-2.0-Backend/test_perception.py` | Verification source for perception; assertions/fixtures inspected only, not executed for this guide. | `test_provider_initializes`, `test_perceive_image_produces_parseable_json`, `test_repeated_call_served_from_cache_no_new_api_call`, `test_perception_coverage_increments`; further assertions | Test runner only; Uses `src/__init__.py`, `src/db.py`, `src/ingest.py`, `src/llm.py` + 2 more |
| `FraudLens-2.0-Backend/test_pilot_workflow.py` | Verification source for pilot workflow; assertions/fixtures inspected only, not executed for this guide. | `test_login_email_expiry_revocation`, `test_password_rotation`, `test_applicant_admin_workflow`, `test_duplicate_filenames`; further assertions | Test runner only; Imported by `test_assessment_explanation.py`, `test_customer_workflow.py`, `test_durable_pilot.py`, `test_postgres.py` + 1 more; Uses `src/__init__.py`, `src/api.py`, `src/db.py`, `src/ingest.py` + 4 more |
| `FraudLens-2.0-Backend/test_postgres.py` | Verification source for postgres; assertions/fixtures inspected only, not executed for this guide. | `test_postgres_concurrent_claims_and_skip_locked`, `test_postgres_concurrent_submission_replays_one_acceptance`, `test_postgres_advisory_leader_and_worker_failover`, `test_postgres_stale_attempt_cannot_commit_findings_or_progress`; further assertions | Test runner only; Uses `scripts/migrate_postgres.py`, `scripts/postgres_backup.py`, `src/__init__.py`, `src/agent/__init__.py` + 19 more |
| `FraudLens-2.0-Backend/test_report_pdf.py` | Verification source for report pdf; assertions/fixtures inspected only, not executed for this guide. | `test_pdf_private_durable_idempotent`, `test_pdf_failure_retry_keeps_snapshot`, `test_pdf_pending_does_not_snapshot_active_analysis`, `test_saved_pdf_unchanged_after_decision_and_source_removal`; further assertions | Test runner only; Imported by `test_assessment_explanation.py`, `test_postgres.py`; Uses `src/__init__.py`, `src/agent/production_policy.py`, `src/api.py`, `src/assessment_explanation.py` + 6 more |
| `FraudLens-2.0-Backend/test_reprocess_history.py` | Verification source for reprocess history; assertions/fixtures inspected only, not executed for this guide. | `test_explicit_scope_and_budget_defer_all_822_without_modifying_ledger`, `test_unique_missing_vision_and_current_compatibility_estimates`, `test_apply_refuses_822_before_loading_models_or_touching_cases`, `test_live_validation_gate_rejects_missing_workflow_cached_or_unrecorded_attempts`; further assertions | Test runner only; Uses `scripts/__init__.py`, `scripts/reprocess_history.py`, `src/__init__.py`, `src/db.py` + 2 more |
| `FraudLens-2.0-Backend/test_severity_chronology.py` | Verification source for severity chronology; assertions/fixtures inspected only, not executed for this guide. | `test_worsening_damage_is_not_a_repeat_when_offsets_sort_differently` | Test runner only; Uses `src/checks/base.py`, `src/checks/severity_progression.py`, `src/models.py` |
| `FraudLens-2.0-Backend/test_verify_live_analysis.py` | Verification source for verify live analysis; assertions/fixtures inspected only, not executed for this guide. | `test_distinct_successful_workflows_produce_proof_without_mutating_saved_inputs`, `test_database_json_columns_are_decoded_without_losing_exact_run_proof`, `test_retained_failed_claim_and_missing_underwriting_emit_audit_only`, `test_cached_agent_response_cannot_prove_live_adjudication`; further assertions | Test runner only; Uses `scripts/__init__.py`, `scripts/verify_live_analysis.py`, `src/__init__.py`, `src/db.py` + 1 more |
| `FraudLens-2.0-Backend/verify_setup.py` | Environment/import/model prerequisite verification utility; not executed for this guide. | `check` | Imports `dotenv`, `google`, `pysolar`, `requests`, `subprocess` |

## Deployment and repository configuration

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `.gitignore` | Repository exclusions for secrets, evidence, databases/backups, generated files and caches. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/.env.example` | Server environment variable examples; values intentionally not reproduced. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/.gitignore` | Backend exclusions for local environments, data, models and private runtime artifacts. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/DEPLOYMENT.md` | Deployment and persistent evidence/worker requirements; not proof of a deployed backend. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/railway.json` | Existing Railway single-host startup/readiness/restart configuration; no Render blueprint present. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/requirements-pilot.txt` | Optional verification pins: pytest, Playwright, pypdf and PyMuPDF. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/requirements.txt` | Flat pinned environment combining application/research imports and transitives. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/runtime.txt` | Deployment Python runtime declaration. | — | Framework/tool configuration or supporting documentation/asset |

## Research, data and supporting documentation

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `ANALYSIS_REPAIR_HANDOVER.md` | Repair implementation/analysis-history/provider handover; supporting source-backed record. | — | Framework/tool configuration or supporting documentation/asset |
| `ANALYSIS_REPAIR_VERIFICATION.md` | Dated verification record including persisted stop and unintended guarded-test provider attempt. | — | Framework/tool configuration or supporting documentation/asset |
| `AUTONOMOUS_PROGRESS.md` | Chronological progress notes; pre-existing staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `CHECK_VERIFICATION_MATRIX.md` | Dated per-check verification/limitations matrix; pre-existing staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `DEMO_READINESS_CHECKLIST.md` | Dated demo readiness/limits checklist; pre-existing staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `DEMO_RUNBOOK.md` | Local demonstration/diagnostic runbook; pre-existing staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/app.py` | Research/debug Streamlit HTTP client; separate from the React product interface. | `api_get`, `band_chip`, `page_queue`, `case_picker`, `page_detail`, `page_trace`; further helpers | Imports `pandas`, `requests`, `streamlit` |
| `FraudLens-2.0-Backend/src/generate_dataset.py` | Research synthetic corpus/controlled image manipulation generator; not customer intake. | `build_garages`, `random_registration`, `random_claimant`, `sample_claim_amount`, `sample_gaming_amount`, `solar_elevation_local`; further helpers | Uses `src/__init__.py`, `src/db.py`, `src/ingest.py`, `src/models.py` |
| `FraudLens-2.0-Backend/src/sampling.py` | Research stratified evaluation sampling and perception-eligible cohort selection. | `load_archetypes`, `perceived_cases`, `cell_of`, `stratified_sample`, `sample_report`, `ablation_sample` | Imported by `scripts/ab_test_prompt.py`, `scripts/audit_clean_labels.py`, `scripts/run_ablation.py`; Uses `src/__init__.py`, `src/db.py` |
| `FraudLens-2.0-Frontend/EXPORT_MANIFEST.json` | Historical source export manifest; not current runtime settings. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/EXPORT_NOTES.md` | Historical export/setup notes; old separate-backend/SQLite deployment statements are superseded. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/INTEGRATION.md` | Integration contract notes; checked against current source. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/README.md` | Frontend development/setup documentation; supporting reference. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens_Pilot_Changes.patch` | Historical first-party patch artifact; never loaded/applied at runtime. | — | Framework/tool configuration or supporting documentation/asset |
| `GEMINI_DIAGNOSIS.md` | Dated provider-stop/recovery investigation; pre-existing staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `LATENCY_MEASUREMENTS.md` | Dated local timing observations; no new measurements executed for this guide. | — | Framework/tool configuration or supporting documentation/asset |
| `PILOT_HANDOVER.md` | Pilot operational handover; staged supporting record, not current DB inspection. | — | Framework/tool configuration or supporting documentation/asset |
| `POSTGRES_MIGRATION.md` | Migration/backup verification handover, including dated reported counts; staged version retained. | — | Framework/tool configuration or supporting documentation/asset |
| `PRESENTATION_HANDOVER.md` | Customer/reviewer presentation implementation and limitation handover. | — | Framework/tool configuration or supporting documentation/asset |
| `PRESENTATION_IMPLEMENTATION.md` | Presentation implementation notes cross-checked against components. | — | Framework/tool configuration or supporting documentation/asset |
| `PRESENTATION_VERIFICATION.md` | Dated browser/UI verification record; not checks performed by this documentation task. | — | Framework/tool configuration or supporting documentation/asset |
| `audit_reports/FraudLens_2_Project_Audit.docx` | Earlier generated audit document; historical reference, not current source of truth. | — | Framework/tool configuration or supporting documentation/asset |
| `audit_reports/generate_fraudlens_audit_doc.py` | Documentation python-docx generator for an earlier project audit; separate from report_pdf.py. | `run`, `read`, `rel`, `file_size`, `package_json`, `py_symbols`; further helpers | Imports `ast`, `csv`, `html`, `subprocess`, `zipfile` |

## Bundled public assets and directory placeholders

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `FraudLens-2.0-Backend/notebooks/.gitkeep` | Empty-directory placeholder; no implementation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/.gitkeep` | Empty-directory placeholder; no implementation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/agent/.gitkeep` | Empty-directory placeholder; no implementation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/checks/.gitkeep` | Empty-directory placeholder; no implementation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Backend/src/db/.gitkeep` | Empty-directory placeholder; no implementation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/apple-touch-icon.png` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/assets/fraudlens-cover.png` | Public branding/social-preview bitmap; not private evidence. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/assets/fraudlens-og.png` | Public branding/social-preview bitmap; not private evidence. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/favicon-16.png` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/favicon-32.png` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/favicon.ico` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/favicon.svg` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/icon-192.png` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/icon-512.png` | Public favicon/install icon referenced by metadata/manifest. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/intro-poster.jpg` | Bundled landing-page video/media used by IntroVideo. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/media/agent-recon.png` | Bundled agent illustration used by shared branding/service presentation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/media/agent-sentinel.png` | Bundled agent illustration used by shared branding/service presentation. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/media/intro.mp4` | Bundled landing-page video/media used by IntroVideo. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/public/site.webmanifest` | Public browser/install icon manifest; no service-worker/offline implementation implied. | — | Framework/tool configuration or supporting documentation/asset |
| `FraudLens-2.0-Frontend/src/assets/icon-sparkles-soft.svg` | Bundled vector asset; no current source reference found. | — | Framework/tool configuration or supporting documentation/asset |

## Generated documentation outputs

| Path | Purpose | Important symbols/routes | Main dependencies/callers |
|---|---|---|---|
| `docs/FraudLens_Mentor_Guide.md` | Generated source-backed mentor explanation, workflows/status distinctions and presentation narrative. | Sections 1–13 | Current source/configuration and dated verification records; editable PDF companion. |
| `docs/FraudLens_Mentor_Guide.pdf` | Generated paginated mentor handout with diagrams and concise file map. | Printable guide | Local documentation PDF workflow; no application analysis triggered. |
| `docs/FraudLens_File_Inventory.md` | Generated complete first-party inventory/dependency/route appendix. | This appendix | Static AST/import/configuration inspection, separate from the main PDF file map. |

## Dependency classification

**Direct versus transitive.** Frontend package.json explicitly separates direct `dependencies` and `devDependencies`; package-lock.json resolves transitives. Backend requirements.txt is a flat pinned environment: a pin does not prove it was an original top-level choice. The backend table distinguishes source imports, tooling/research imports and transitive/unconfirmed packages. Installed does not mean actively used. Optional requirements-pilot.txt is verification tooling.

### Frontend explicit direct dependencies

| Package | Declared version | Classification and evidence |
|---|---|---|
| `@base-ui/react` | `1.5.0` | Tooling/template — Reusable UI primitive only; outside product entry graph |
| `@hookform/resolvers` | `5.4.0` | Unconfirmed — No first-party product import found |
| `@material-symbols/svg-400` | `0.45.5` | Tooling/template — Icon imports in reusable UI templates; product Icon uses authored SVG paths |
| `@radix-ui/react-accordion` | `1.2.15` | Tooling/template — Only templates/harness/config import it: `src/components/ui/accordion.tsx` |
| `@radix-ui/react-alert-dialog` | `1.1.18` | Tooling/template — Only templates/harness/config import it: `src/components/ui/alert-dialog.tsx` |
| `@radix-ui/react-aspect-ratio` | `1.1.11` | Tooling/template — Only templates/harness/config import it: `src/components/ui/aspect-ratio.tsx` |
| `@radix-ui/react-avatar` | `1.2.1` | Tooling/template — Only templates/harness/config import it: `src/components/ui/avatar.tsx` |
| `@radix-ui/react-checkbox` | `1.3.6` | Tooling/template — Only templates/harness/config import it: `src/components/ui/checkbox.tsx` |
| `@radix-ui/react-collapsible` | `1.1.15` | Tooling/template — Only templates/harness/config import it: `src/components/ui/collapsible.tsx` |
| `@radix-ui/react-context-menu` | `2.3.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/context-menu.tsx` |
| `@radix-ui/react-dialog` | `1.1.18` | Tooling/template — Only templates/harness/config import it: `src/components/ui/command.tsx`, `src/components/ui/dialog.tsx` |
| `@radix-ui/react-dropdown-menu` | `2.1.19` | Tooling/template — Only templates/harness/config import it: `src/components/ui/dropdown-menu.tsx` |
| `@radix-ui/react-hover-card` | `1.1.18` | Tooling/template — Only templates/harness/config import it: `src/components/ui/hover-card.tsx` |
| `@radix-ui/react-label` | `2.1.11` | Tooling/template — Only templates/harness/config import it: `src/components/ui/form.tsx`, `src/components/ui/label.tsx` |
| `@radix-ui/react-menubar` | `1.1.19` | Tooling/template — Only templates/harness/config import it: `src/components/ui/menubar.tsx` |
| `@radix-ui/react-navigation-menu` | `1.2.17` | Tooling/template — Only templates/harness/config import it: `src/components/ui/navigation-menu.tsx` |
| `@radix-ui/react-popover` | `1.1.18` | Tooling/template — Only templates/harness/config import it: `src/components/ui/popover.tsx` |
| `@radix-ui/react-progress` | `1.1.11` | Tooling/template — Only templates/harness/config import it: `src/components/ui/progress.tsx` |
| `@radix-ui/react-radio-group` | `1.4.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/radio-group.tsx` |
| `@radix-ui/react-scroll-area` | `1.2.13` | Tooling/template — Only templates/harness/config import it: `src/components/ui/scroll-area.tsx` |
| `@radix-ui/react-select` | `2.3.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/select.tsx` |
| `@radix-ui/react-separator` | `1.1.11` | Tooling/template — Only templates/harness/config import it: `src/components/ui/separator.tsx` |
| `@radix-ui/react-slider` | `1.4.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/slider.tsx` |
| `@radix-ui/react-slot` | `1.3.0` | Tooling/template — Only templates/harness/config import it: `src/components/ui/breadcrumb.tsx`, `src/components/ui/button.tsx` |
| `@radix-ui/react-switch` | `1.3.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/switch.tsx` |
| `@radix-ui/react-tabs` | `1.1.16` | Tooling/template — Only templates/harness/config import it: `src/components/ui/tabs.tsx` |
| `@radix-ui/react-toggle` | `1.1.13` | Tooling/template — Only templates/harness/config import it: `src/components/ui/toggle.tsx` |
| `@radix-ui/react-toggle-group` | `1.1.14` | Tooling/template — Only templates/harness/config import it: `src/components/ui/toggle-group.tsx` |
| `@radix-ui/react-tooltip` | `1.2.11` | Tooling/template — Only templates/harness/config import it: `src/components/ui/tooltip.tsx` |
| `@tailwindcss/vite` | `4.3.2` | Tooling/template — Only templates/harness/config import it: `vite.config.ts` |
| `@tanstack/react-query` | `5.101.2` | Active — Imported by `src/router.tsx`, `src/routes/__root.tsx` |
| `@tanstack/react-router` | `1.170.17` | Active — Imported by `src/router.tsx`, `src/routes/__root.tsx` |
| `@tanstack/react-start` | `1.168.27` | Active — Imported by `src/server.ts`, `src/start.ts` |
| `@tanstack/router-plugin` | `1.168.19` | Unconfirmed — No first-party product import found |
| `class-variance-authority` | `0.7.1` | Tooling/template — Only templates/harness/config import it: `src/components/ui/alert.tsx`, `src/components/ui/badge.tsx` |
| `clsx` | `2.1.1` | Tooling/template — Only templates/harness/config import it: `src/lib/utils.ts` |
| `cmdk` | `1.1.1` | Tooling/template — Only templates/harness/config import it: `src/components/ui/command.tsx` |
| `date-fns` | `4.4.0` | Unconfirmed — No first-party product import found |
| `embla-carousel-react` | `8.6.0` | Tooling/template — Only templates/harness/config import it: `src/components/ui/carousel.tsx` |
| `input-otp` | `1.4.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/input-otp.tsx` |
| `nitro` | `^3.0.260903-beta (lock 3.0.260903-beta)` | Tooling/template — Only templates/harness/config import it: `vite.config.ts` |
| `react` | `19.2.7` | Active — Imported by `src/experience/Admin.tsx`, `src/experience/AdminOverview.tsx` |
| `react-day-picker` | `9.14.0` | Tooling/template — Only templates/harness/config import it: `src/components/ui/calendar.tsx` |
| `react-dom` | `19.2.7` | Active — Imported by `src/experience/FieldSuggestions.tsx` |
| `react-hook-form` | `7.81.0` | Tooling/template — Only templates/harness/config import it: `src/components/ui/form.tsx` |
| `react-resizable-panels` | `4.12.1` | Tooling/template — Only templates/harness/config import it: `src/components/ui/resizable.tsx` |
| `recharts` | `2.15.4` | Tooling/template — Only templates/harness/config import it: `src/components/ui/chart.tsx` |
| `sonner` | `2.0.7` | Tooling/template — Only templates/harness/config import it: `src/components/ui/sonner.tsx` |
| `tailwind-merge` | `3.6.0` | Tooling/template — Only templates/harness/config import it: `src/lib/utils.ts` |
| `tailwindcss` | `4.3.2` | Active — Imported by `src/styles.css` |
| `tw-animate-css` | `1.4.0` | Tooling — Build/style package; Vite/style configuration |
| `vaul` | `1.1.2` | Tooling/template — Only templates/harness/config import it: `src/components/ui/drawer.tsx` |
| `vite-tsconfig-paths` | `6.1.1` | Tooling/template — Only templates/harness/config import it: `vite.config.ts` |
| `zod` | `4.4.3` | Unconfirmed — No first-party product import found |
| `@eslint/js` | `9.39.4` | Tooling — Declared development dependency |
| `@types/node` | `22.20.0` | Tooling — Declared development dependency |
| `@types/react` | `19.2.15` | Tooling — Declared development dependency |
| `@types/react-dom` | `19.2.3` | Tooling — Declared development dependency |
| `@vitejs/plugin-react` | `5.2.0` | Tooling — Declared development dependency |
| `eslint` | `9.39.4` | Tooling — Declared development dependency |
| `eslint-config-prettier` | `10.1.8` | Tooling — Declared development dependency |
| `eslint-plugin-prettier` | `5.5.6` | Tooling — Declared development dependency |
| `eslint-plugin-react-hooks` | `5.2.0` | Tooling — Declared development dependency |
| `eslint-plugin-react-refresh` | `0.4.26` | Tooling — Declared development dependency |
| `globals` | `15.15.0` | Tooling — Declared development dependency |
| `prettier` | `3.9.4` | Tooling — Declared development dependency |
| `typescript` | `5.9.3` | Tooling — Declared development dependency |
| `typescript-eslint` | `8.62.1` | Tooling — Declared development dependency |
| `vite` | `7.3.6` | Tooling — Declared development dependency |
| `vite-plugin-svgr` | `5.2.0` | Tooling — Declared development dependency |

### Backend declared pin set

Pins come from requirements.txt. “Source import” establishes use; “transitive/unconfirmed” means direct first-party use and dependency-root origin were not established. Native/model libraries can load other packages transitively.

| Package | Pinned version | Classification and evidence |
|---|---|---|
| `altair` | `6.2.2` | Transitive/unconfirmed — No first-party direct import established |
| `annotated-doc` | `0.0.5` | Transitive/unconfirmed — No first-party direct import established |
| `annotated-types` | `0.8.0` | Transitive/unconfirmed — No first-party direct import established |
| `anyio` | `4.14.2` | Transitive/unconfirmed — No first-party direct import established |
| `attrs` | `26.1.0` | Transitive/unconfirmed — No first-party direct import established |
| `blinker` | `1.9.0` | Transitive/unconfirmed — No first-party direct import established |
| `certifi` | `2026.7.22` | Transitive/unconfirmed — No first-party direct import established |
| `cffi` | `2.1.1` | Transitive/unconfirmed — No first-party direct import established |
| `charset-normalizer` | `3.4.9` | Transitive/unconfirmed — No first-party direct import established |
| `click` | `8.4.2` | Transitive/unconfirmed — No first-party direct import established |
| `colorama` | `0.4.6` | Transitive/unconfirmed — No first-party direct import established |
| `contourpy` | `1.3.3` | Transitive/unconfirmed — No first-party direct import established |
| `cryptography` | `50.0.0` | Transitive/unconfirmed — No first-party direct import established |
| `cycler` | `0.12.1` | Transitive/unconfirmed — No first-party direct import established |
| `distro` | `1.9.0` | Transitive/unconfirmed — No first-party direct import established |
| `easyocr` | `1.7.2` | Active source import — `src/checks/plate_ocr.py` |
| `ExifRead` | `3.5.1` | Transitive/unconfirmed — No first-party direct import established |
| `fastapi` | `0.141.1` | Active source import — `src/api.py`, `src/customer_auth.py` |
| `filelock` | `3.29.0` | Tooling/research source import — `scripts/reprocess_history.py` |
| `fonttools` | `4.63.0` | Transitive/unconfirmed — No first-party direct import established |
| `fsspec` | `2026.4.0` | Transitive/unconfirmed — No first-party direct import established |
| `ftfy` | `6.3.1` | Transitive/unconfirmed — No first-party direct import established |
| `geographiclib` | `2.1` | Transitive/unconfirmed — No first-party direct import established |
| `geopy` | `2.5.0` | Active source import — `src/checks/metadata.py` |
| `google-ai-generativelanguage` | `0.6.15` | Transitive/unconfirmed — No first-party direct import established |
| `google-api-core` | `2.33.0` | Transitive/unconfirmed — No first-party direct import established |
| `google-api-python-client` | `2.198.0` | Transitive/unconfirmed — No first-party direct import established |
| `google-auth` | `2.56.3` | Transitive/unconfirmed — No first-party direct import established |
| `google-auth-httplib2` | `0.4.1` | Transitive/unconfirmed — No first-party direct import established |
| `google-genai` | `2.18.1` | Active source import — `src/llm.py` |
| `googleapis-common-protos` | `1.75.0` | Transitive/unconfirmed — No first-party direct import established |
| `greenlet` | `3.5.4` | Transitive/unconfirmed — No first-party direct import established |
| `grpcio` | `1.83.0` | Transitive/unconfirmed — No first-party direct import established |
| `grpcio-status` | `1.71.2` | Transitive/unconfirmed — No first-party direct import established |
| `h11` | `0.16.0` | Transitive/unconfirmed — No first-party direct import established |
| `hf-xet` | `1.6.0` | Transitive/unconfirmed — No first-party direct import established |
| `httpcore` | `1.0.9` | Transitive/unconfirmed — No first-party direct import established |
| `httplib2` | `0.32.0` | Transitive/unconfirmed — No first-party direct import established |
| `httptools` | `0.8.0` | Transitive/unconfirmed — No first-party direct import established |
| `httpx` | `0.28.1` | Tooling/research source import — `scripts/profile_demo_http.py`, `scripts/verify_browser_pilot.py` |
| `huggingface_hub` | `1.26.1` | Transitive/unconfirmed — No first-party direct import established |
| `idna` | `3.18` | Transitive/unconfirmed — No first-party direct import established |
| `ImageHash` | `4.3.2` | Active source import — `src/ingest.py` |
| `ImageIO` | `2.37.4` | Transitive/unconfirmed — No first-party direct import established |
| `itsdangerous` | `2.2.0` | Transitive/unconfirmed — No first-party direct import established |
| `Jinja2` | `3.1.6` | Transitive/unconfirmed — No first-party direct import established |
| `joblib` | `1.5.3` | Transitive/unconfirmed — No first-party direct import established |
| `jsonschema` | `4.26.0` | Transitive/unconfirmed — No first-party direct import established |
| `jsonschema-specifications` | `2025.9.1` | Transitive/unconfirmed — No first-party direct import established |
| `kiwisolver` | `1.5.0` | Transitive/unconfirmed — No first-party direct import established |
| `lazy-loader` | `0.5` | Transitive/unconfirmed — No first-party direct import established |
| `markdown-it-py` | `4.2.0` | Transitive/unconfirmed — No first-party direct import established |
| `MarkupSafe` | `3.0.3` | Transitive/unconfirmed — No first-party direct import established |
| `matplotlib` | `3.11.1` | Tooling/research source import — `scripts/make_figures.py` |
| `mdurl` | `0.1.2` | Transitive/unconfirmed — No first-party direct import established |
| `mpmath` | `1.3.0` | Transitive/unconfirmed — No first-party direct import established |
| `narwhals` | `2.24.0` | Transitive/unconfirmed — No first-party direct import established |
| `networkx` | `3.6.1` | Transitive/unconfirmed — No first-party direct import established |
| `ninja` | `1.13.0` | Transitive/unconfirmed — No first-party direct import established |
| `numpy` | `2.4.4` | Active source import — `src/checks/digital_edit.py`, `src/checks/external_corpus.py` |
| `open_clip_torch` | `3.3.0` | Active source import — `src/ingest.py` |
| `opencv-python-headless` | `5.0.0.93` | Active source import — `src/checks/digital_edit.py` |
| `packaging` | `26.3` | Transitive/unconfirmed — No first-party direct import established |
| `pandas` | `3.0.5` | Tooling/research source import — `app.py` |
| `piexif` | `1.1.3` | Active source import — `src/ingest.py` |
| `pillow` | `12.2.0` | Active source import — `src/api.py`, `src/evidence_workflow.py` |
| `proto-plus` | `1.28.2` | Transitive/unconfirmed — No first-party direct import established |
| `protobuf` | `5.29.6` | Transitive/unconfirmed — No first-party direct import established |
| `psycopg[binary]` | `3.3.6` | Active source import — `src/db.py`, `src/pg_migrations.py` |
| `psycopg-pool` | `3.3.3` | Active source import — `src/postgres.py` |
| `pyarrow` | `24.0.0` | Transitive/unconfirmed — No first-party direct import established |
| `pyasn1` | `0.6.4` | Transitive/unconfirmed — No first-party direct import established |
| `pyasn1_modules` | `0.4.2` | Transitive/unconfirmed — No first-party direct import established |
| `pyclipper` | `1.4.0` | Transitive/unconfirmed — No first-party direct import established |
| `pycparser` | `3.0` | Transitive/unconfirmed — No first-party direct import established |
| `pydantic` | `2.13.4` | Active source import — `src/api.py`, `src/customer_auth.py` |
| `pydantic_core` | `2.46.4` | Transitive/unconfirmed — No first-party direct import established |
| `pydeck` | `0.9.3` | Transitive/unconfirmed — No first-party direct import established |
| `Pygments` | `2.20.0` | Transitive/unconfirmed — No first-party direct import established |
| `pyparsing` | `3.3.2` | Transitive/unconfirmed — No first-party direct import established |
| `pysolar` | `0.13` | Active source import — `src/checks/scene_consistency.py` |
| `python-bidi` | `0.6.11` | Transitive/unconfirmed — No first-party direct import established |
| `python-dateutil` | `2.9.0.post0` | Transitive/unconfirmed — No first-party direct import established |
| `python-dotenv` | `1.2.2` | Active source import — `scripts/start_deployment.py`, `src/llm.py` |
| `python-multipart` | `0.0.32` | Active framework support — FastAPI Form/File multipart parser, not a direct import |
| `PyWavelets` | `1.9.0` | Transitive/unconfirmed — No first-party direct import established |
| `PyYAML` | `6.0.3` | Transitive/unconfirmed — No first-party direct import established |
| `referencing` | `0.37.0` | Transitive/unconfirmed — No first-party direct import established |
| `regex` | `2026.7.19` | Transitive/unconfirmed — No first-party direct import established |
| `requests` | `2.34.2` | Active source import — `src/checks/scene_consistency.py`, `src/llm.py` |
| `reportlab` | `4.4.4` | Active source import — `src/report_pdf.py` |
| `rich` | `15.0.0` | Transitive/unconfirmed — No first-party direct import established |
| `rpds-py` | `2026.6.3` | Transitive/unconfirmed — No first-party direct import established |
| `safetensors` | `0.8.0` | Transitive/unconfirmed — No first-party direct import established |
| `scikit-image` | `0.26.0` | Transitive/unconfirmed — No first-party direct import established |
| `scikit-learn` | `1.9.0` | Transitive/unconfirmed — No first-party direct import established |
| `scipy` | `1.18.0` | Transitive/unconfirmed — No first-party direct import established |
| `seaborn` | `0.13.2` | Transitive/unconfirmed — No first-party direct import established |
| `setuptools` | `78.1.0` | Transitive/unconfirmed — No first-party direct import established |
| `shapely` | `2.1.2` | Transitive/unconfirmed — No first-party direct import established |
| `shellingham` | `1.5.4` | Transitive/unconfirmed — No first-party direct import established |
| `six` | `1.17.0` | Transitive/unconfirmed — No first-party direct import established |
| `sniffio` | `1.3.1` | Transitive/unconfirmed — No first-party direct import established |
| `SQLAlchemy` | `2.0.51` | Transitive/unconfirmed — No first-party direct import established |
| `starlette` | `1.3.1` | Tooling/research source import — `test_postgres.py` |
| `streamlit` | `1.61.1` | Tooling/research source import — `app.py` |
| `sympy` | `1.14.0` | Transitive/unconfirmed — No first-party direct import established |
| `tenacity` | `9.1.4` | Transitive/unconfirmed — No first-party direct import established |
| `threadpoolctl` | `3.6.0` | Transitive/unconfirmed — No first-party direct import established |
| `tifffile` | `2026.7.31` | Transitive/unconfirmed — No first-party direct import established |
| `timm` | `1.0.28` | Transitive/unconfirmed — No first-party direct import established |
| `tokenizers` | `0.22.2` | Transitive/unconfirmed — No first-party direct import established |
| `toml` | `0.10.2` | Transitive/unconfirmed — No first-party direct import established |
| `torch` | `2.13.0+cpu` | Active source import — `src/checks/plate_ocr.py`, `src/ingest.py` |
| `torchvision` | `0.28.0+cpu` | Transitive/unconfirmed — No first-party direct import established |
| `tqdm` | `4.70.0` | Active source import — `src/orchestrator.py`, `src/perception.py` |
| `transformers` | `5.14.1` | Active source import — `src/checks/ai_detection.py` |
| `typer` | `0.27.1` | Transitive/unconfirmed — No first-party direct import established |
| `typing-inspection` | `0.4.2` | Transitive/unconfirmed — No first-party direct import established |
| `typing_extensions` | `4.15.0` | Transitive/unconfirmed — No first-party direct import established |
| `tzdata` | `2026.3` | Transitive/unconfirmed — No first-party direct import established |
| `uritemplate` | `4.2.0` | Transitive/unconfirmed — No first-party direct import established |
| `urllib3` | `2.7.0` | Transitive/unconfirmed — No first-party direct import established |
| `c2pa-python` | `0.38.0` | Active source import — `src/checks/provenance.py` |
| `uvicorn` | `0.52.1` | Active server tooling — Startup command in deployment/pilot scripts |
| `watchdog` | `6.0.0` | Transitive/unconfirmed — No first-party direct import established |
| `wcwidth` | `0.8.2` | Transitive/unconfirmed — No first-party direct import established |
| `websockets` | `16.1.1` | Transitive/unconfirmed — No first-party direct import established |

### Optional verification dependencies

| Package | Pinned version | Classification and evidence |
|---|---|---|
| `pytest` | `9.1.1` | Tooling — Unit/regression runner |
| `playwright` | `1.64.0` | Tooling — Chrome/browser workflow verification |
| `pypdf` | `6.20.1` | Tooling — PDF text extraction/assertions |
| `pymupdf` | `1.26.5` | Tooling — PDF rendering/inspection through fitz |

### Provider integrations versus local inference

- google-genai has a production Gemini vision/chat path in src/llm.py; persisted provider controls can block requests. Other installed Google SDKs are not separate integrations by implication.
- Ollama is an optional implemented HTTP adapter, selected by configuration; presence does not prove a running Ollama server.
- Historical weather requests/cache handling live in src/checks/scene_consistency.py. External-corpus matching is a local evaluation index, not a web reverse-image-search service.
- CLIP/PyTorch, EasyOCR and the optional transformers AI-image classifier perform local inference; cached weights must exist or be provisioned. Package pins do not verify cache contents.
- PostgreSQL uses psycopg/psycopg-pool. Supabase is server-side hosted PostgreSQL; no Supabase Auth/client SDK is used for product login.
- ReportLab renders saved application reports locally. The mentor PDF is separate documentation output.

## Complete registered API route inventory

### Complete registered backend route inventory

Extracted statically with Python AST from the current source: 38 explicit method/path registrations. No application import, HTTP request, database connection or model call was used. `src/api.py` calls `evidence_workflow.install`, `report_pdf.install` and `customer_auth.install`; no APIRouter or other route-registration module was found.

`require_admin` is a historical helper name: it accepts the reviewer-family roles, including read-only viewer, and the configured service token. Mutating human decisions use stronger checks. All paths below are relative to the backend origin.

| Method | Path | Purpose | Required access | Handler |
|---|---|---|---|---|
| GET | `/health` | Database/provider diagnostic summary; provider status comes from local controls | Public diagnostic route | `FraudLens-2.0-Backend/src/api.py::health` |
| GET | `/ready` | Check storage writability and database/schema availability | Public diagnostic route | `FraudLens-2.0-Backend/src/api.py::ready` |
| GET | `/v1/accounts` | List reviewer accounts without password hashes | Admin role only | `FraudLens-2.0-Backend/src/evidence_workflow.py::accounts` |
| PUT | `/v1/accounts` | Create/update/disable reviewer access and revoke existing sessions | Admin role only | `FraudLens-2.0-Backend/src/evidence_workflow.py::save_account` |
| POST | `/v1/auth/login` | Validate account password and create 8-hour session for that role | Public; credentials validated in handler | `FraudLens-2.0-Backend/src/api.py::login` |
| POST | `/v1/auth/logout` | Delete the presented session token hash; idempotent | Presented token to revoke; no session-validity prerequisite | `FraudLens-2.0-Backend/src/api.py::logout` |
| GET | `/v1/auth/session` | Validate current session and return identity/role/expiry | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::session` |
| GET | `/v1/cases` | Filter, paginate and sort reviewer case queue | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::list_cases` |
| POST | `/v1/cases` | Validate multipart intake, store evidence, enqueue job; optional UUID4 idempotency | Receipt-based anonymous intake supported; optional customer bearer creates ownership (frontend requires customer login) | `FraudLens-2.0-Backend/src/api.py::submit_case` |
| GET | `/v1/cases/{case_id}` | Current case details, image references, findings, decision and review basis | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_case_detail` |
| POST | `/v1/cases/{case_id}/action` | Record human approve/reject/evidence request with concurrency guards | Human admin/reviewer bearer; service explicitly denied | `FraudLens-2.0-Backend/src/api.py::record_action` |
| POST | `/v1/cases/{case_id}/evidence` | Accept requested supplementary photographs and enqueue a new run | Unexpired case receipt OR owning customer; current open evidence request required | `FraudLens-2.0-Backend/src/evidence_workflow.py::submit_evidence` |
| GET | `/v1/cases/{case_id}/report` | Current JSON report or selected immutable historical snapshot | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_case_report` |
| GET | `/v1/cases/{case_id}/reports` | List immutable report versions and PDF readiness | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/report_pdf.py::list_reports` |
| POST | `/v1/cases/{case_id}/reports/prepare` | Render/store missing PDF artifact from a saved report snapshot | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/report_pdf.py::prepare_report` |
| GET | `/v1/cases/{case_id}/reports/{snapshot_id}/pdf` | Return saved PDF bytes inline or as attachment (?download=true) | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/report_pdf.py::download_report` |
| POST | `/v1/cases/{case_id}/reprocess` | Snapshot prior report and enqueue a new run | Admin/reviewer/service bearer | `FraudLens-2.0-Backend/src/api.py::reprocess_case` |
| GET | `/v1/cases/{case_id}/similar` | Find related cases by internal evidence/identifiers | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_similar` |
| GET | `/v1/cases/{case_id}/trace` | Return recorded agent action trace, withholding outage steps | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_trace` |
| GET | `/v1/checks` | Registered check metadata and limitations | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::list_checks` |
| GET | `/v1/checks/{check_id}` | Check description, limitation and local measurement artifact names | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_check` |
| POST | `/v1/customer/auth/login` | Validate account password and create 8-hour session for that role | Public; credentials validated in handler | `FraudLens-2.0-Backend/src/customer_auth.py::login` |
| POST | `/v1/customer/auth/logout` | Delete the presented session token hash; idempotent | Presented token to revoke; no session-validity prerequisite | `FraudLens-2.0-Backend/src/customer_auth.py::logout` |
| POST | `/v1/customer/auth/register` | Create customer account and start customer session | Public; credentials validated in handler | `FraudLens-2.0-Backend/src/customer_auth.py::register` |
| GET | `/v1/customer/auth/session` | Validate current session and return identity/role/expiry | Customer bearer; case/image routes also enforce ownership | `FraudLens-2.0-Backend/src/customer_auth.py::session` |
| GET | `/v1/customer/cases` | List cases owned by current customer | Customer bearer; case/image routes also enforce ownership | `FraudLens-2.0-Backend/src/customer_auth.py::cases` |
| POST | `/v1/customer/cases/link` | Link unowned historical case using valid unexpired private receipt | Customer bearer plus valid case receipt; conflicting existing owner rejected | `FraudLens-2.0-Backend/src/customer_auth.py::link` |
| GET | `/v1/customer/cases/{case_id}` | Customer-safe details and public timeline for owned case | Customer bearer; case/image routes also enforce ownership | `FraudLens-2.0-Backend/src/customer_auth.py::detail` |
| GET | `/v1/customer/images/{image_id}` | Private customer image after server-side ownership check | Customer bearer; case/image routes also enforce ownership | `FraudLens-2.0-Backend/src/customer_auth.py::image` |
| GET | `/v1/finding-counts` | Aggregate current finding counts by check/verdict | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::finding_counts` |
| GET | `/v1/garages/{garage_id}` | Garage-scoped claim amount distribution and findings | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_garage` |
| GET | `/v1/health` | Database/provider diagnostic summary; provider status comes from local controls | Public diagnostic route | `FraudLens-2.0-Backend/src/api.py::health` |
| GET | `/v1/images/{image_id}` | Private original image or generated thumbnail (?thumb=1) | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_image` |
| GET | `/v1/jobs/{job_id}` | Return safe durable job status/progress | Unexpired case receipt OR owning customer OR reviewer-family bearer | `FraudLens-2.0-Backend/src/api.py::get_job` |
| GET | `/v1/operations` | Queue, worker leadership and sanitized recent failure diagnostics | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::operations` |
| GET | `/v1/policies` | Current policy configurations | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_policies` |
| GET | `/v1/stats` | Reviewer dashboard totals and research summary | Reviewer-family bearer: admin/reviewer/viewer, or configured service token | `FraudLens-2.0-Backend/src/api.py::get_stats` |
| GET | `/v1/track` | Safe applicant tracking; also requires registration or policy match | Unexpired case receipt OR owning customer OR reviewer-family bearer; track also requires registration/policy match | `FraudLens-2.0-Backend/src/api.py::track_case` |

### FastAPI framework documentation routes

The `FastAPI(...)` constructor does not override/disable the documentation defaults. These are framework registrations, separate from the 38 application registrations above. Expected framework methods are GET and HEAD; this is source/configuration inspection, not a live route probe.

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET, HEAD | `/openapi.json` | Generated OpenAPI schema | Public by default |
| GET, HEAD | `/docs` | Swagger interactive documentation | Public by default |
| GET, HEAD | `/docs/oauth2-redirect` | Swagger OAuth2 redirect helper (does not mean the app uses OAuth2) | Public by default |
| GET, HEAD | `/redoc` | ReDoc API documentation | Public by default |

CORS middleware may answer allowed cross-origin OPTIONS preflight requests; those are middleware handling rather than extra registered application endpoints.


Routes are extracted statically from FastAPI decorators and installed customer/evidence/report modules; no live OpenAPI request or application import was used. Built-in FastAPI documentation endpoints are identified separately.

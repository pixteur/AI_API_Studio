# AI API Studio v2 Blueprint

This document turns the current `CLAUDE.md` from a v1 reference into a launchpad for a more vertical, business-driven product.

The short version: yes, the existing `CLAUDE.md` is good enough to use as a development context file, but it should stay focused on "what exists today." For the next phase, the clean move is to keep `CLAUDE.md` as the v1 source of truth and add this v2 blueprint beside it.

## 1. What the current app really is

After reviewing the codebase, the current app is:

- A local-first Flask app with most backend behavior in `nbs.py`
- A mostly single-screen frontend with a large amount of stateful vanilla JS in `templates/index.html`
- Filesystem-backed for generations, favorites, elements, and config
- Gemini-first, with prompt-to-image generation and one strong side workflow for talent analysis

Important seams already in place:

- Generation pipeline: `/api/generate` already normalizes prompt input, model selection, aspect ratio, ref images, and writes generation metadata to disk
- Talent metadata pipeline: `/api/elements/analyze-image` already does structured LLM extraction and cost logging
- Stats logging: `config.json` already stores request and vision logs, but only at a lightweight summary level
- Asset system: `/api/elements` already acts like the beginning of a reusable asset library, not just a gallery

That means the app is not starting from zero. It already has the beginnings of:

- A prompt execution layer
- A metadata extraction layer
- A creative asset registry
- A local usage accounting layer

## 2. What the current architecture will struggle with

The current shape is very workable for v1, but it will fight you if you directly bolt on everything you listed.

Main constraints:

- One-file backend monolith: routes, provider logic, storage logic, pricing, auth, and image processing are all mixed together in `nbs.py`
- File-only persistence: JSON files and folders are fine for generations and assets, but weak for reporting, task history, routing decisions, cost attribution, retries, and connector sync state
- UI logic is tightly coupled to one generation experience: the current frontend is optimized for "prompt in, images out," not multi-step business workflows
- Provider abstraction is minimal: model info exists, but only for Gemini image generation plus one Gemini analysis path

Conclusion:

Do not treat v2 as "more buttons on top of v1."

Treat v2 as:

- the current generator plus
- a workflow engine plus
- a provider/router layer plus
- a reporting layer plus
- a connector layer

## 3. Best use of `CLAUDE.md`

Use `CLAUDE.md` for:

- Current route contracts
- Current storage conventions
- Current UI conventions
- Theme and template behavior
- Existing feature inventory

Do not overload `CLAUDE.md` with speculative v2 details unless they are implemented.

Recommended doc split:

- `CLAUDE.md`: current architecture and implemented behavior only
- `CLAUDE_V2_BLUEPRINT.md`: target architecture, product rules, data contracts, rollout plan
- Later, once features land, fold completed sections back into `CLAUDE.md`

This keeps AI agents and human devs from confusing "planned" with "real."

## 4. Product direction for v2

Your requested direction points to a different product category:

- Less "AI image toy"
- More "creative operations system"

The strongest product framing is:

`brief -> task -> automation -> routed workflow -> outputs -> reports -> delivery/sync`

That flow fits your list much better than the current "prompt bar plus settings" model.

## 5. Recommended v2 architecture

Keep Flask if you want speed and low complexity, but split the app into modules.

Suggested structure:

```text
AI_API_Studio/
  app/
    __init__.py
    web/
      routes_pages.py
      routes_generate.py
      routes_assets.py
      routes_reports.py
      routes_connectors.py
      routes_admin.py
    services/
      generation_service.py
      prompt_automation_service.py
      workflow_service.py
      talent_analysis_service.py
      reporting_service.py
      sync_service.py
      model_import_service.py
    providers/
      base.py
      gemini_provider.py
      comfyui_provider.py
      kling_provider.py
      seedance_provider.py
      hunyuan3d_provider.py
    routing/
      task_router.py
      llm_router.py
      capability_registry.py
    storage/
      files.py
      db.py
      repositories/
    domain/
      jobs.py
      tasks.py
      assets.py
      reports.py
      workflows.py
      providers.py
  templates/
  static/
```

### Storage recommendation

Keep filesystem storage for binary assets:

- generations
- loved outputs
- source references
- exported deliverables

Add SQLite for metadata and operational state:

- jobs
- workflow runs
- prompt presets
- client/project/task records
- provider capabilities
- routing decisions
- usage and cost logs
- connector sync runs
- model release catalog

This is the single biggest structural upgrade I would make.

## 6. Core platform concepts to add

### A. Job spec

Everything should normalize into one internal job spec before generation:

```json
{
  "client_id": "acme",
  "project_id": "spring_campaign",
  "task_type": "product_launch_visuals",
  "objective": "Generate 8 launch-ready social stills",
  "subject_pack_ids": ["talent_zuri", "shoe_drop_021"],
  "brand_pack_id": "acme_brand_core",
  "output_requirements": {
    "channels": ["instagram", "meta_ads"],
    "aspect_ratios": ["1:1", "4:5", "9:16"],
    "count": 8
  },
  "constraints": {
    "budget_usd": 25,
    "deadline": "2026-03-22"
  }
}
```

Prompt text becomes an implementation detail, not the main user-facing interface.

### B. Task templates

Users should choose a business task, not a raw model.

Examples:

- Launch campaign
- New talent onboarding
- Product hero images
- Ad variation batch
- Location concepting
- Editorial lookbook
- Model release ingestion
- Talent metadata cleanup

Each task template should define:

- required inputs
- optional inputs
- recommended providers
- output package shape
- QA checks
- delivery destinations

### C. Skill packs

Task-based skills can be implemented as reusable packs:

- prompt-building rules
- workflow graph defaults
- routing preferences
- metadata schema
- export rules

A "skill" here should be product-level, not just prompt text.

Example:

```json
{
  "id": "meta_ad_creative",
  "task_types": ["ad_variation_batch"],
  "prompt_blocks": ["brand_voice", "conversion_visual_rules"],
  "preferred_providers": ["gemini", "comfyui", "kling"],
  "report_dimensions": ["client", "campaign", "channel", "cost_per_approved_asset"]
}
```

### D. Provider capability registry

You will need a canonical registry for what each system can do.

Example fields:

- provider name
- model/workflow id
- input types
- output types
- strengths
- max batch size
- cost basis
- supports references
- supports video
- supports 3D
- supports img2img
- supports control inputs
- latency estimate
- availability status

This registry is what powers both task routing and semi-automated new model onboarding.

## 7. How your requested features map into the architecture

### Prompt automation

Build a prompt automation service that composes prompts from:

- task template
- client brand pack
- talent/location/prop packs
- output channel requirements
- style presets
- compliance rules

Input UI should be structured, like:

- What are we making?
- For which client?
- Which channels?
- Which talent/product/location?
- What vibe?
- Any hard constraints?

Output should be:

- internal job spec
- generated prompt variants
- chosen workflow/provider
- editable advanced prompt view for power users

### Task-based skills and LLM routing

Split routing into two layers:

1. Task router
   Chooses the workflow family based on business objective.

2. LLM/provider router
   Chooses the best provider or model based on capability, budget, latency, and quality target.

Example:

- "Talent onboarding" -> Gemini Vision or a vision-first metadata workflow
- "Ad batch variations" -> Gemini fast path or ComfyUI controlled workflow
- "3D concept asset" -> Hunyuan 3D workflow
- "Motion pitch draft" -> Kling or Seedance

Routing should be rule-first, not fully agentic. Keep it inspectable.

### Usage, flow, and cost reports

Current stats are too shallow for business reporting.

Add normalized tables for:

- job_runs
- workflow_steps
- provider_calls
- asset_outputs
- approvals
- exports
- sync_deliveries
- estimated_costs

Reports should answer:

- cost by client
- cost by campaign
- cost by provider/model
- output count by task type
- approval rate by workflow
- average time to approved asset
- prompt automation effectiveness
- connector delivery volume

### Sync with ads platforms and external systems

Use a connector abstraction:

```python
class Connector:
    def push_assets(self, payload): ...
    def pull_context(self, payload): ...
    def healthcheck(self): ...
```

Likely first connector targets:

- Meta Ads
- Google Ads
- Airtable
- Notion
- Google Sheets
- Drive/Dropbox
- basic webhook destinations

Important: connector runs need durable logging, retry state, and audit history.

### ComfyUI behind a simpler front end

This is a strong direction.

Do not expose nodes.
Expose outcome-oriented workflows:

- "Studio portrait cleanup"
- "Consistent product packshots"
- "Luxury editorial skin retouch"
- "Batch ad resize and varianting"
- "Character consistency upscale"

Internally, each one maps to:

- workflow template id
- required assets
- tunable params
- provider adapter

ComfyUI becomes an execution backend, not the UI model.

### Integrations with Hunyuan 3D, Seedance, Kling

These should fit under the same provider adapter pattern, not be added as one-off buttons.

Each adapter should declare:

- supported task types
- accepted inputs
- result polling behavior
- cost estimate method
- output artifact types

### Automated talent analysis with metadata generation

This already exists in early form.

Next step is to make it a pipeline:

- ingest portrait/reference
- analyze with vision model
- normalize to schema
- generate search tags
- generate usage recommendations
- generate safety/commercial notes
- attach to talent record
- optionally suggest matching task templates

The schema should grow beyond appearance into production utility.

New metadata fields worth adding:

- style fit
- brand fit
- pose range
- expression range
- wardrobe compatibility
- commercial use cases
- similarity clusters
- confidence score per extracted field

### Semi-automated import of new model releases and capabilities

This should become a provider capability ingestion pipeline:

- fetch release info from configured sources
- parse capability deltas
- flag new model/workflow candidates
- let admin approve import
- add to capability registry
- optionally map to task types

Do not auto-enable new providers directly in production workflows.
Use review/approval state.

### Workflow logic inspired by Flora and Luma, but more vertical

The right translation here is:

- graph-like workflow logic
- step-level orchestration
- reusable creative blocks
- business-specific task wrappers

So instead of a generic node editor, expose:

- campaigns
- tasks
- recipes
- approvals
- exports

The graph exists under the hood, but the user sees a business process.

## 8. Frontend direction

The current generator UI is good for a power-user sandbox, but not for most clients.

Recommended top-level UI shift:

### Current

- prompt
- references
- model
- aspect ratio
- generate

### v2

- client
- project
- task
- assets
- output goals
- automation level
- generate/run workflow

Suggested primary navigation:

- Workbench
- Tasks
- Assets
- Reports
- Integrations
- Admin

Suggested main workbench flow:

1. Pick or create task
2. Fill structured brief
3. Review auto-built plan
4. Run
5. Review outputs
6. Approve/export/sync

Keep an "Advanced Prompt" drawer for expert users, but hide it by default.

## 9. Immediate technical recommendations

If we build this in stages, I would do the following first:

### Phase 1: prepare the app for growth

- Split `nbs.py` into modules
- Add SQLite metadata store
- Move config, stats, job logs, and connector state into DB-backed repositories
- Introduce service layer around generation and talent analysis

### Phase 2: add task system

- Add task templates
- Add job spec normalization
- Add rule-based provider router
- Add workflow run records

### Phase 3: replace prompt-first UX

- Add structured brief UI
- Add prompt automation engine
- Keep current prompt bar as an advanced mode

### Phase 4: add provider adapters

- ComfyUI adapter
- one external motion/video adapter
- one external 3D adapter

### Phase 5: add reporting and sync

- cost dashboards
- flow metrics
- connector runs
- delivery/export actions

## 10. Suggested data entities

At minimum, add these entities:

- `clients`
- `projects`
- `tasks`
- `task_templates`
- `skill_packs`
- `job_runs`
- `workflow_runs`
- `workflow_steps`
- `providers`
- `provider_capabilities`
- `assets`
- `asset_collections`
- `talent_profiles`
- `reports_cache`
- `connector_accounts`
- `connector_runs`
- `model_release_candidates`

## 11. API surface that v2 will likely need

New API families:

- `/api/tasks/*`
- `/api/workflows/*`
- `/api/router/*`
- `/api/reports/*`
- `/api/connectors/*`
- `/api/providers/*`
- `/api/releases/*`

Keep existing APIs for backward compatibility while migrating the frontend.

## 12. What should be added to `CLAUDE.md` later

Once implementation begins, `CLAUDE.md` should grow with factual sections for:

- Domain model
- DB schema overview
- Provider adapter contract
- Routing rules
- Workflow execution contract
- Connector contract
- Reporting metrics definitions
- Task template schema
- Skill pack schema
- Migration notes from v1 routes to v2 routes

Until then, those belong in this blueprint, not the main v1 reference.

## 13. Recommended first build slice

If we want the smartest first step, build this vertical slice:

- structured task intake
- prompt automation
- rule-based provider routing
- job logging
- richer cost reporting

Why this first:

- it directly addresses the "clients do not want to write prompts" problem
- it creates the foundation for external providers later
- it improves business value before heavy integration work

## 14. Practical next milestone

Recommended milestone name:

`AI API Studio 1.5 - Task Workbench`

Scope:

- task templates
- structured brief form
- prompt automation service
- provider router
- SQLite metadata layer
- reports page with per-task/per-provider spend

That would turn the current app into a real orchestration foundation without forcing a full rewrite on day one.

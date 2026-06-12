# Agent creation prompts

Two-step flow: **editable JD** → **framework design** (with optional construction clarifications).

## Step 1 — Job description draft

**File:** `backend/services/agent_jd_generator.py`

Generates only role title, summary, and responsibilities. No schedule, no validation questions.

The hiring manager edits fields inline and confirms before framework design runs.

## Step 2 — Multi-agent framework design

**File:** `backend/services/agent_framework_designer.py`

Input: confirmed JD + persona context.

Output:
- `framework` — orchestrator + specialist agents mapped to responsibilities
- `construction_questions` — **only when design is ambiguous** (empty array when JD is clear)

Construction questions are open-text, directly tied to a stated ambiguity. No multiple-choice.

### When questions appear (rule-based)

- 5+ responsibilities → ask about priority routing
- 2+ vague/generic responsibilities → ask to narrow deliverables
- 6+ skills → ask which skill lane leads

## APIs

- `POST /api/agents/jd-draft` — generate editable JD
- `POST /api/agents/framework-preview` — design framework from confirmed JD
- `POST /api/agents/create` — persist agent with `job_description` + `framework_design`

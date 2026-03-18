---
name: brainlift
description: >
  Facilitated BrainLift creation: domain research via Gemini + WebSearch first,
  then orientation and Socratic prompts that draw out the human's genuine DOK 3
  insights and DOK 4 SPOVs. Assembles a complete BrainLift document. Use when the user says
  "/brainlift <topic>", "/brainlift refine <path>", or "/brainlift --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), or "refine <path>" to critique/improve
      an existing BrainLift. Optional flags: --deep (double research budget),
      --research <path> (reuse existing research artifact).
---

# BrainLift Skill Invoked

User has requested: `/brainlift {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to extract:

**Flags** (strip from args after detection):
- `--deep` -> double web research budget
- `--research <path>` -> path to existing `.research-<slug>.json` to reuse

**Mode detection** (after stripping flags):
1. **Refine mode**: first word is `refine` and remaining arg is a path to an existing `.md` file -> read it as an existing BrainLift to critique and improve. Skip to Step 9b.
2. **Topic mode**: everything else -> treat as the domain/topic.

**Slug derivation**: from the topic text, generate a slug — lowercase, hyphenated, max 40 chars.

**Output path**: `brainlifts/<slug>/BRAINLIFT.md`. Create the directory.

---

## Step 1: Domain research (parallel agents)

This is NOT technical research (APIs, packages). This is domain research — the knowledge foundation the human needs to form original insights. Research runs first so the human can see the landscape before articulating their tension.

**If `--research <path>` was provided**: read the existing artifact and skip to Step 1b.

**Otherwise:** launch two parallel agents for independent domain discovery.

### Gemini agent

Launch: `Agent(subagent_type="general-purpose", prompt=<prompt below>, run_in_background=true)`

```
You are a domain researcher. Use web_search (which has Google Search grounding built in)
to do broad discovery on a topic. Your job is to map the research landscape.

TOOLS: First call ToolSearch to load web_search:
  ToolSearch: select:mcp__gemini__web_search
Then use web_search for all research.

TOPIC: <topic>

BUDGET: Ask <BUDGET> research questions via web_search. Each should target a different
dimension of the domain.

For each call, investigate one of these dimensions:
1. Key researchers and thinkers — names, affiliations, what they're known for, where they DISAGREE
2. Foundational theories and frameworks — with citations
3. Active debates — conventional wisdom vs challengers
4. Empirical findings — studies, meta-analyses, effect sizes. Prefer recent work that contradicts older findings
5. Adjacent domains — transferable insights from other fields
6. Common misconceptions among practitioners

Be specific — cite real researchers and real papers, not generic claims.

OUTPUT: Write findings to brainlifts/<slug>/.research-gemini.json using the Write tool.
Schema:
{
  "agent": "gemini",
  "slug": "<slug>",
  "status": "complete",
  "researchers": [{ "name": "string", "affiliation": "string", "known_for": "string", "camp": "string" }],
  "frameworks": [{ "name": "string", "description": "string", "citation": "string" }],
  "debates": [{ "topic": "string", "conventional": "string", "challenger": "string", "challenger_name": "string" }],
  "findings": [{ "claim": "string", "source": "string", "year": "number or null", "effect_size": "string or null" }],
  "adjacent_domains": [{ "domain": "string", "insight": "string" }],
  "misconceptions": [{ "belief": "string", "reality": "string" }]
}

RETURN: DONE: findings written to brainlifts/<slug>/.research-gemini.json
Do NOT return findings themselves. Do NOT ask questions.
```

**Budget:** Normal: `<BUDGET>` = "2-3". Deep: `<BUDGET>` = "4-6".

### Claude agent

Launch: `Agent(subagent_type="general-purpose", prompt=<prompt below>, run_in_background=true)`

```
You are a domain researcher doing deep extraction from academic and research sources.
Your job is to find authoritative researchers, papers, and empirical evidence independently.

TOOLS: Use WebSearch to find sources, then WebFetch to extract details.
Run WebSearch calls SEQUENTIALLY (not parallel) to avoid rate limits.

TOPIC: <topic>

TARGET SOURCES: Google Scholar results, university faculty pages, ResearchGate profiles,
journal abstracts, conference proceedings, systematic reviews.

BUDGET:
- Run <SEARCH_BUDGET> WebSearch calls sequentially
- WebFetch the top <FETCH_BUDGET> results
- For each fetch, ask specific extraction questions:
  "Who are the key researchers? What are their positions? What studies support their claims?"

For each search, target a different angle:
- "<topic> systematic review OR meta-analysis"
- "<topic> leading researchers disagreement"
- "<topic> empirical evidence recent findings"
- "<topic> misconceptions practitioners"
- "<topic> [adjacent field] transferable insights"

OUTPUT: Write findings to brainlifts/<slug>/.research-claude.json using the Write tool.
Schema:
{
  "agent": "claude",
  "slug": "<slug>",
  "status": "complete",
  "researchers": [{ "name": "string", "affiliation": "string", "known_for": "string", "source_url": "string" }],
  "frameworks": [{ "name": "string", "description": "string", "source_url": "string" }],
  "debates": [{ "topic": "string", "positions": "string", "source_url": "string" }],
  "findings": [{ "claim": "string", "source": "string", "year": "number or null", "source_url": "string" }],
  "misconceptions": [{ "belief": "string", "reality": "string", "source_url": "string" }]
}

If you encounter errors, set "status": "partial" and include whatever you found.

RETURN: DONE: findings written to brainlifts/<slug>/.research-claude.json
Do NOT return findings themselves. Do NOT ask questions.
```

**Budget:** Normal: `<SEARCH_BUDGET>` = "3-5", `<FETCH_BUDGET>` = "max 4". Deep: `<SEARCH_BUDGET>` = "5-8", `<FETCH_BUDGET>` = "max 8".

---

## Step 1b: Merge research

Wait for both agents to complete. Read both intermediate files.

**Handle failures:** If one agent fails, proceed with the other's data. If both fail, stop with an error.

**Merge logic:**
1. **Researchers**: match by name (case-insensitive). When both agents found the same researcher, keep the version with more detail and merge source URLs. Set `confidence: "high"`. Unmatched researchers get `confidence: "single-source"`.
2. **Frameworks**: dedup by name. Merge descriptions.
3. **Debates**: dedup by topic. When both agents identified the same debate, merge positions and note agreement.
4. **Findings**: dedup by claim subject. When both agents cite the same study, merge and mark `confidence: "high"`. Flag contradictions (different effect sizes or conclusions for the same study).
5. **Misconceptions**: dedup by belief. Merge.

Save merged output to `brainlifts/<slug>/.research.json`:
```json
{
  "slug": "<slug>",
  "topic": "<topic>",
  "agents": ["gemini", "claude"],
  "researchers": [...],
  "frameworks": [...],
  "debates": [...],
  "findings": [...],
  "adjacent_domains": [...],
  "misconceptions": [...],
  "urls": [...],
  "conflicts": [...],
  "gaps": [...]
}
```
This artifact is reusable via `--research <path>` and available for refine mode.

---

## Step 2: Orient — Purpose & North Star

Now that the research landscape is visible, establish what the human is actually trying to understand. The research gives them context to articulate a sharper tension.

```
AskUserQuestion:
I've mapped out the research landscape for this domain. Before we dig in, I need to understand what YOU are trying to do with it.

1. **What are you building?** (Not the tech — the experience. Who uses it, and what should change about how they think/feel/act?)

2. **What's the tension?** (A BrainLift exists because something is hard to get right. What's the core design problem — the thing that, if you get wrong, nothing else matters?)

3. **Who is the user, and what's their current mental model?** (What do they already believe or expect before they encounter your design?)
```

Wait for user response. Hold their answers as `orientation` — these inform every subsequent step.

From their response, draft:
- A 1-2 sentence **Purpose** statement that names the tension
- A **North Star** — a single filtering question that resolves design disagreements
- Initial **In Scope** / **Out of Scope** boundaries

Present these back to the user for confirmation before proceeding. One round of revision max.

---

## Step 3: Expert identification

From the research, compile a candidate expert list (aim for 6-10 candidates).

```
AskUserQuestion:
Here are the key thinkers in this space. I've grouped them by what they'd argue:

**Camp A** (argues X):
- [Researcher 1] — [position, key work]
- [Researcher 2] — [position, key work]

**Camp B** (argues Y):
- [Researcher 3] — [position, key work]
- [Researcher 4] — [position, key work]

**Bridge/Synthesis thinkers:**
- [Researcher 5] — [what they contribute that others miss]

**Adjacent domain voices:**
- [Researcher 6] — [different field, transferable insight]

Which of these resonate with you? Whose work changed how YOU think about this problem? Are there experts you already follow who should be on this list?
```

Wait for response. Record the human's curated expert list (3-5 experts) with their reasoning for each inclusion.

---

## Step 4: DOK 2 — Knowledge Tree review

Organize the research findings into thematic categories. Present to the human as a structured summary, NOT the final DOK 2 section (that comes during assembly).

```
AskUserQuestion:
I've organized what I found into [N] categories. Before I ask you to think about this, I want to know what stands out to you:

**Category 1: [Theme]**
- [Key finding 1 — source]
- [Key finding 2 — source]
- [Where experts disagree on this]

**Category 2: [Theme]**
- [Key finding 1]
- [Key finding 2]

[...repeat for each category...]

**What I want to know from you:**

1. **What surprises you here?** What contradicts something you believed before reading this?
2. **What's missing?** You know this domain — what important perspective or finding is absent?
3. **Where do you disagree with the research?** Not where you wish it said something different — where your experience tells you the findings are incomplete or wrong.
```

Wait for response. Their answers are the raw material for DOK 3. Record them carefully — the surprises and disagreements are where insights come from.

If the human identifies missing areas, run 1-2 additional targeted searches to fill gaps.

---

## Step 5: DOK 3 — Insight extraction

This is the most important interactive phase. The human's DOK 4 SPOVs are built from these insights. The goal is to draw out genuine connections the human is making — not to suggest insights for them.

```
AskUserQuestion:
Now I want to help you find the insights buried in your reactions. These are your ideas — not summaries of what you read, but the new connections your brain is making.

Try these prompts (answer whichever ones spark something):

1. **"Most people in this field think ___, but actually ___."** (Fill in the blank. What's the conventional wisdom that your research suggests is incomplete or wrong?)

2. **"The thing that [Expert A] gets right that [Expert B] misses is ___."** (Where does one expert's blind spot get filled by another?)

3. **"I used to think ___, but after reading this I now think ___."** (What belief did you update? The bigger the update, the more interesting the insight.)

4. **"If I had to explain the ONE thing that makes this problem hard to solve well, it's ___."** (What's the core difficulty that most designs get wrong?)

5. **"[Finding from domain A] actually explains why [problem in domain B] is so persistent."** (Cross-domain connection — this is where the spikiest insights live.)

Take as many or few of these as are useful. I'm looking for 4-7 insights.
```

Wait for response.

**Evaluate the human's responses:**
- If a response is a restatement of a single source -> push back: "That sounds like it's coming from [source]. What does it mean when you combine it with [different source]?"
- If a response is generic -> push for specificity: "Can you give me the concrete version? What design decision does this change?"
- If a response is genuinely novel -> reinforce and probe: "That's interesting — what would someone who disagrees with you say? How would you defend it?"

```
AskUserQuestion:
I want to push on a few of these:

[For each response that needs sharpening:]
- "[Their insight]" — [specific probe: is this a summary or an insight? who would disagree? what does this change?]

And one more question: **looking at your insights together, do any of them cluster? Do two of them feel like they're circling the same bigger idea?**
```

Wait for response. Record refined insights. The clusters they identify are the seeds of DOK 4 SPOVs.

### Step 5b: Draft DOK 3 sections

The human has given you raw insight seeds — short, conversational, sometimes incomplete. Now ghostwrite fully elaborated DOK 3 entries using:
- The human's position and language as the core
- DOK 2 evidence (from Step 1/4) to ground each insight in specific sources
- Cross-references between insights where the human identified connections

For each insight, draft:
- **Title**: a single declarative sentence capturing the insight
- **Body**: 2-4 sentences that explain the connection, cite the supporting sources, and state why this goes beyond what any single source says

Present all drafted insights back to the human:

```
AskUserQuestion:
I've drafted your insights into full DOK 3 sections. These are YOUR ideas — I've just connected them to the evidence and fleshed out the reasoning. Tell me where I got your thinking wrong or where you want to sharpen something.

**Insight 1: [Title]**
[Drafted body with source citations]

**Insight 2: [Title]**
[Drafted body]

[...repeat for each insight...]

What needs changing? Where did I misrepresent what you meant?
```

Wait for response. Apply corrections. One round — the human's voice takes priority over polish.

---

## Step 6: DOK 4 — SPOV synthesis

The human has refined insights and has identified clusters. Now help them forge SPOVs.

```
AskUserQuestion:
Your insights are pointing toward some strong positions. Let's sharpen them into SPOVs — the bold claims that will drive your entire design.

For each cluster you identified:

1. **State it as a rule.** Not "I think X might be true" but "X is true and here's what it means for design." A SPOV is a commitment, not a hypothesis.

2. **Name the opponent.** Who in the field would disagree with this SPOV? What's their best argument against it? (If nobody would disagree, it's not spiky — it's consensus.)

3. **State the design consequence.** "Because of this SPOV, we will ___ and we will NOT ___." If the SPOV doesn't constrain a design decision, it's not actionable enough.

I'm looking for 3-5 SPOVs. Quality over quantity — one genuinely spiky, well-defended SPOV is worth more than five safe ones.
```

Wait for response. Record the human's raw SPOV positions.

**Evaluate:**
- If a SPOV is safe/consensus -> "I don't think anyone would argue with that. What's the version that would make a smart colleague push back?"
- If a SPOV is contrarian without evidence -> "That's provocative, but what's the evidence trail? Can you walk me from DOK 2 facts through DOK 3 insights to this claim?"
- If a SPOV is strong -> "Good. Now — what's the strongest argument AGAINST this position? And does your SPOV survive it?"

One round of refinement max on the human's raw positions. Don't over-iterate — the human's conviction matters.

### Step 6b: Draft DOK 4 sections

Now ghostwrite fully elaborated SPOV entries. For each SPOV, draft:
- **Assertion**: the human's position stated as a strong, clear claim
- **Elaboration**: 1-2 paragraphs building the evidence chain — walk from DOK 2 facts through DOK 3 insights to the claim. Cite specific researchers and findings. Name the tension between camps. Explain why the synthesis resolves the tension.
- **Design rule**: the concrete constraint this SPOV imposes on the design

The elaboration is where the writing labor lives. The human gave you the position and the evidence trail — you connect them into a coherent argument that a reader could follow from premise to conclusion.

Present all drafted SPOVs back to the human:

```
AskUserQuestion:
I've drafted your SPOVs into full DOK 4 sections. The positions are yours — I've built out the evidence chain and argument structure. Tell me where I got your reasoning wrong.

**SPOV 1: [Assertion]**
[Drafted elaboration with evidence chain]
**Design rule:** [Drafted constraint]

**SPOV 2: [Assertion]**
[Drafted elaboration]
**Design rule:** [Drafted constraint]

[...repeat...]

What needs changing? Where is the argument weaker than your actual position?
```

Wait for response. Apply corrections. One round.

---

## Step 7: Cognitive Map

```
AskUserQuestion:
Now let's map what's happening in your user's head. Walk me through the experience phase by phase.

For each phase of your design:

1. **Name the phase and what the user sees.** (Screen state, not feature list.)

2. **What are they ACTUALLY thinking?** Not what you want them to think. Not what a rational actor would think. What is a real person — with their prior knowledge, their biases, their limited attention — actually thinking at this moment?

3. **What decision are they making?** Every phase has one — even if it's "do I keep going or quit?" Is it a cognitive decision (reasoning) or a spatial one (where to look/tap)?

4. **What's in working memory?** List every item. If the list has more than 4 items, your design has a cognitive load problem at this phase. Rate it: LOW (1-2 items), MEDIUM (3-4), HIGH (4+).

5. **Where will they get stuck?** Be specific. Not "they might be confused" — but "they won't know where to tap because the visual hierarchy implies X when the interaction requires Y."

6. **What does the design do about it?** The design response should be specific enough to implement.

Start with phase 1 and go as far as you can. We'll refine as needed.
```

Wait for response. If phases are thin (missing dimensions from the table), probe:

```
AskUserQuestion:
Good start. Let me push on a few phases:

[For thin phases:]
- **Phase [N]**: You described what they see, but what are they DECIDING? Every phase has a decision point — even if the decision is "do I keep going or quit." What's the decision, and is it cognitive (thinking) or spatial (looking/tapping)?

[For phases missing load level:]
- **Phase [N]**: What's the cognitive load here? List what's in working memory at this exact moment. How many things must the user hold in mind simultaneously?

[For phases missing confusion risk:]
- **Phase [N]**: What's the confusion risk here? Think about the gap between YOUR mental model of what should happen and a FIRST-TIME user's mental model.
```

Wait for response. One refinement round.

### Step 7b: Draft Cognitive Map sections

The human gave you phase descriptions — possibly conversational, possibly incomplete on some dimensions. Ghostwrite fully structured cognitive map tables.

For each phase, draft:
- All 6 dimensions filled in the table format (User sees, User thinks, Decision point, Cognitive load, Confusion risk, Design response)
- Cognitive load rated as LOW/MEDIUM/HIGH with working memory items enumerated
- Decision point typed as cognitive or spatial

Also draft the **Cognitive Load Analysis** section:
- Load-by-phase summary table
- Key cognitive load principles applied (derive from what the human described — don't invent principles they didn't reference)
- Potential confusion points & mitigations table (pulled from each phase's confusion risk + design response)

Present the full cognitive map + load analysis back to the human:

```
AskUserQuestion:
I've structured your phase descriptions into the full cognitive map format. Check that I captured your thinking accurately — especially the load levels and confusion risks.

**Phase 1: [Name] ([Load Level])**
| Dimension | Analysis |
|---|---|
| **User sees** | [drafted] |
| **User thinks** | [drafted] |
| **Decision point** | [drafted] |
| **Cognitive load** | [drafted with working memory items] |
| **Confusion risk** | [drafted] |
| **Design response** | [drafted] |

[...repeat for each phase...]

**Cognitive Load by Phase:**
[summary table]

**Confusion Points:**
[mitigations table]

What needs correcting?
```

Wait for response. Apply corrections. One round.

---

## Step 8: Assumptions

```
AskUserQuestion:
Last section. Every design has load-bearing assumptions — things that must be true for the design to work, but that you haven't proven yet.

1. **What must be true about your USER for this design to work?** (What do they need to already know, be able to do, or be willing to try?)

2. **What must be true about your TECHNOLOGY for this design to work?** (What technical capability are you assuming exists and is reliable?)

3. **What must be true about your DESIGN THEORY for this design to work?** (Which research finding are you betting on most heavily? What if it doesn't replicate in your context?)

For each assumption: **how would you know if it were false?** If you can't answer that, you can't test it.
```

Wait for response. Record assumptions with their failure modes.

---

## Step 9: Assembly

Read the template from `~/.claude/templates/brainlift-template.md` for the structural skeleton.

Compile the full BrainLift document from all collected responses:

1. **Purpose, North Star, Scope** — from Step 2 (confirmed by user)
2. **DOK 4 SPOVs** — human-approved drafts from Step 6b
3. **Experts** — from Step 3, the human's curated list with reasoning
4. **User/Player Cognitive Map** — human-approved drafts from Step 7b (structured tables)
5. **Cognitive Load Analysis** — human-approved drafts from Step 7b (summary table, principles, confusion points)
6. **DOK 3 Insights** — human-approved drafts from Step 5b
7. **DOK 2 Knowledge Tree** — from Step 1 research + Step 4 human additions, organized by category with DOK 1 facts and DOK 2 summaries
8. **Key Assumptions** — from Step 8

**Assembly rules:**
- **DOK 3 and DOK 4**: use the human-approved drafts from Steps 5b and 6b directly. These have already been reviewed — don't re-draft them.
- **DOK 2 Knowledge Tree**: organize research findings into categories with DOK 1 facts and DOK 2 summaries. Include source URLs from web validation. Mark sources as verified or Gemini-only.
- **Cognitive Map and Cognitive Load Analysis**: use the human-approved drafts from Step 7b directly. These have already been structured and reviewed — don't re-derive from raw Step 7 answers.
- **Purpose, Experts, Assumptions**: use the human-confirmed versions from Steps 1, 3, and 8.
- Voice: the human's words and positions are the document's voice. When expanding short answers into full prose (cognitive map details, DOK 2 summaries), stay faithful to their framing.

Write the assembled document to `brainlifts/<slug>/BRAINLIFT.md`.

---

## Step 9.5: Generate PDF

Convert the assembled markdown to a styled PDF:

```bash
python3.11 ~/.claude/scripts/brainlift_pdf.py brainlifts/<slug>/BRAINLIFT.md brainlifts/<slug>/BRAINLIFT.pdf
```

If the command fails (missing dependencies), note it in the report but do not block — the markdown file is the primary deliverable.

---

## Step 9b: Refine mode

If refine mode was detected in Step 0:

1. Read the existing BrainLift at the provided path.
2. Assess each section against the thinking frameworks in the template:
   - Are SPOVs genuinely spiky? (Would a smart colleague push back?)
   - Are insights original connections or disguised summaries?
   - Does the cognitive map reflect the user's actual thinking or the designer's projection?
   - Are assumptions testable?
3. Present findings as specific, section-by-section critique.
4. Ask the human which areas they want to strengthen.
5. Run targeted facilitation prompts (from Steps 5-8) only for weak sections.
6. Rewrite the improved document to the same path.

---

## Step 10: Self-critique

After assembly, review the document against these quality checks:

- [ ] Every SPOV has a named opponent (someone who'd disagree)
- [ ] Every SPOV has a design rule that constrains a real decision
- [ ] Every DOK 3 insight traces to DOK 2 sources but isn't a restatement of any one source
- [ ] The cognitive map has all 6 dimensions for every phase
- [ ] Working memory items are enumerated (not vague) in each phase
- [ ] Key assumptions have failure modes
- [ ] DOK 2 sources include both supporting AND challenging evidence

If any check fails, note it at the bottom of the document under a `## Self-critique` section with specific gaps. Do NOT silently fix them — the human needs to see what's weak.

---

## Step 11: Report

```
BrainLift assembled: brainlifts/<slug>/BRAINLIFT.md
- PDF: brainlifts/<slug>/BRAINLIFT.pdf

Sections:
- Purpose & North Star: confirmed
- DOK 4 SPOVs: <count>
- Experts: <count>
- Cognitive Map: <phase count> phases
- DOK 3 Insights: <count>
- DOK 2 Categories: <count> categories, <source count> sources (<verified count> verified)
- Assumptions: <count>

Self-critique flags: <count or "none">
```

---

## What this skill does NOT do

- **Invent DOK 3 insights or DOK 4 SPOVs.** The positions, connections, and claims come from the human's brain. The skill draws them out through facilitation, then ghostwrites them into fully elaborated sections — but the human reviews and approves every draft. The ideas are theirs; the writing labor is shared.
- **Skip interactive phases.** The AskUser prompts are the core value, not an inconvenience. Every phase except research requires human input.
- **Use /research skill.** BrainLift research is domain knowledge (researchers, papers, frameworks), not technical research (APIs, packages). The skill runs its own Gemini + WebSearch phase.
- **Over-iterate.** Each interactive phase gets at most one refinement round. The human's conviction and voice matter more than polish.
- **Silently fix weak sections.** If the self-critique finds gaps, it flags them visibly. The human decides whether to strengthen or accept.

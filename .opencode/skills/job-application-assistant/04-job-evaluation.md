---
framework_version: 1.0.0
---

# Job Evaluation Framework

<!-- SETUP: Skill match areas and career goals are personalized by running /setup -->

## Scoring Dimensions

Evaluate each job posting against these five dimensions:

### 1. Technical Skills Match (0-100)
How well do the required/preferred skills align with the candidate's capabilities?

| Score | Meaning |
|-------|---------|
| 80-100 | Core requirements are primary skills |
| 60-79 | Most requirements match, 1-2 gaps that are learnable |
| 40-59 | Partial match, significant upskilling needed |
| 0-39 | Fundamental mismatch |

**Strong match areas:** Python, RAG / retrieval systems (FAISS, BM25, hybrid retrieval), LangChain, LLM evaluation & observability (LangSmith, Ragas), PyTorch / deep learning, fine-tuning, Docker deployment, prompt engineering, agentic workflows / MCP
**Moderate match areas:** SQL, AWS (EC2, S3, SageMaker), FastAPI, NLP (Transformers, SpaCy), TensorFlow, Power BI, statistics / hypothesis testing, JavaScript/TypeScript (familiar)
**Weak match areas:** Expert-level TypeScript, Kubernetes, front-end frameworks (React, etc.), mobile (React Native, Flutter), distributed training at scale, non-AWS clouds (GCP, Azure)

### 2. Experience Match (0-100)
Does work history align with what they're looking for?

| Score | Meaning |
|-------|---------|
| 80-100 | Direct experience in the same domain and role type |
| 60-79 | Related experience, transferable skills clear |
| 40-59 | Adjacent experience, would need to make the case |
| 0-39 | Unrelated experience |

**Strong:** RAG / LLM application engineering, ML model development and evaluation, end-to-end ML pipelines with containerised deployment, computer vision fine-tuning
**Moderate:** Data analysis / BI, backend API development (FastAPI), applied research collaboration
**Entry-level:** ML platform / infrastructure engineering, data engineering at scale, MLOps beyond evaluation tooling

**Seniority context:** ~2.5 years of combined experience (two internships + one mid-length AI Engineer role). Junior/mid-level and "early career with strong GenAI skills" postings are the natural fit; senior/staff postings need a strong strategic reason.

**Entry-level priority:** Entry-level and graduate roles asking for 0-3 years of experience are a **priority target** - evaluate them as a natural fit, never penalize them as "too junior." When evaluating and applying to these roles, treat the profile as entry-level: the CL Techno AI Engineer role is presented as **volunteer experience** (see presentation rule in 01-candidate-profile.md), with internships and the MSc carrying the experience story.

### 3. Behavioral/Culture Fit (0-100)
Does the role and company culture match the behavioral profile?

| Score | Meaning |
|-------|---------|
| 80-100 | Culture strongly matches behavioral preferences |
| 60-79 | Mixed signals but mostly compatible |
| 40-59 | Some friction areas |
| 0-39 | Significant culture mismatch |

**Red flags to research:** Department disorganization, work dominated by maintenance over development, poor chemistry with leadership, culture mismatches. Check reviews, media coverage, LinkedIn connections, and network contacts for insider perspective.

### 4. Location & Logistics (Pass/Fail + Notes)
- Within commute range: PASS
- Remote with occasional office: PASS
- Requires relocation: FAIL (deal-breaker)
- Frequent international travel: FLAG (discuss with user)

### 5. Career Alignment & Motivation (0-100)
Does this role advance career goals and contain tasks that energize?

| Score | Meaning |
|-------|---------|
| 80-100 | Strongly aligned with career direction, clear growth path |
| 60-79 | Good role but only partially aligned with long-term goals |
| 40-59 | Decent job but doesn't build toward career goals |
| 0-39 | Dead end or backwards step |

**Career goals:**
- Build agentic AI / LLM products that ship to real users (Priority 1 direction: AI/GenAI Engineer)
- Grow from early-career into a solid ML Engineer / Data Scientist / AI Research Engineer trajectory
- Keep the evaluation & responsible-AI thread (LLMOps, observability, bias auditing) alive as a differentiator

**Motivation filter:** Evaluate not just whether you *can* do the tasks, but whether the tasks will *energize* you. Consider:
- Tasks that energize: building agents/RAG systems end to end, LLM evaluation and observability, shipping to production, measurable outcomes
- Tasks that drain: pure demo/research work with no path to users; roles with no ML/AI content
- Non-task factors: leadership style, department culture, company values, degree of autonomy

**Life situation alignment:** Consider personal constraints:
- **Security**: currently between roles (last role ended Feb 2026) - a solid paid offer matters more than a perfect title; unpaid/commission-only is auto-reject
- **Flexibility**: fully mobile - open to UK, India, EU (with sponsorship), and worldwide remote; UK Graduate visa active
- **Professional development**: prioritize roles that deepen GenAI/agentic engineering rather than pure analyst work, even though analyst/developer roles are in scope as a wider net

## Location & Right-to-Work Rules (personalized)
- **UK roles:** PASS (Graduate visa, no sponsorship needed) - flag visa time limit if the posting requires long-term guarantees
- **India roles:** PASS (citizen)
- **EU / other international:** PASS only if the employer sponsors visas - otherwise FLAG
- **Remote worldwide:** PASS - check contractor vs. employment structure

### 6. Salary Benchmark (Optional)

If the salary lookup tool is configured (`salary_data.json` exists), look up the company:
```
python salary_lookup.py "<Company Name>" --json
```

If a city is known from the posting, add `--city "<City>"` to narrow results.

Present findings as:
```
### Salary Benchmark
| Metric | Value |
|--------|-------|
| [Category] index | XX.X (+/-X.X% vs baseline) |
| Overall index | XX.X (+/-X.X% vs baseline) |
```

Interpret results relative to the baseline defined in the data file's metadata. For index-based data, higher typically means above-market compensation.

If the salary tool is not configured, skip this section.

## Output Format

Present the evaluation as:

```
## Job Fit Evaluation: [Role] at [Company]

| Dimension | Score | Notes |
|-----------|-------|-------|
| Technical Skills | XX/100 | [brief note] |
| Experience Match | XX/100 | [brief note] |
| Behavioral Fit | XX/100 | [brief note] |
| Location | PASS/FAIL | [brief note] |
| Career Alignment | XX/100 | [brief note] |

**Overall Score: XX/100** (weighted average of scored dimensions)

### Verdict: [Strong Fit / Good Fit / Moderate Fit / Weak Fit / Poor Fit]

### Key Strengths for This Role
- [bullet points]

### Gaps to Address
- [bullet points]

### Recommendation
[1-2 sentences: apply/skip/apply with caveats]

### Company Research Checklist
- [ ] Checked company website (mission, values, recent news)
- [ ] Checked review sites (Glassdoor, Jobindex, etc.)
- [ ] Checked LinkedIn for team size, recent hires, connections
- [ ] Checked media for restructuring, growth, or workplace issues
- [ ] Identified network contacts who may know the team/manager
```

## Weighting
- Technical Skills: 30%
- Experience Match: 25%
- Behavioral Fit: 15%
- Career Alignment: 30%

(Location is pass/fail, not weighted)

## Thresholds
- **Strong Fit** (75+): Definitely apply, tailor everything
- **Good Fit** (60-74): Apply, address gaps in cover letter
- **Moderate Fit** (45-59): Consider carefully, discuss with user
- **Weak Fit** (30-44): Probably skip unless strategic reasons
- **Poor Fit** (<30): Skip

## Pre-Application: Call the Employer (Best Practice)

Before writing the application, consider whether the candidate should call the contact person listed in the posting. **Only call if there are substantive questions** - never call just to "be remembered."

### When to Suggest Calling
- The posting has unclear or ambiguous requirements
- It's unclear which competencies are essential vs. nice-to-have
- The role description is vague about day-to-day tasks
- There's a named contact person who invites questions

### Good Questions to Ask
- "What are the primary challenges in this role?"
- "How is time typically divided across the listed responsibilities?"
- "Which competencies are most critical for success in this position?"
- "What does success look like in the first 6-12 months?"

### Rules for the Call
- Prepare a 30-second "elevator pitch" about your background in case they ask
- The call's purpose is **gathering information**, not delivering a pitch
- Take notes - use what you learn to tailor the application
- Reference the conversation naturally in the cover letter ("After speaking with [name], I was especially drawn to...")

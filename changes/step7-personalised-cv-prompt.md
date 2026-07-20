# Step 7: Personalised CV — Article-Style Output (Auto-Triggered)

This step runs automatically after Step 6. It produces a second CV in a different style
(`personalised/main.tex` — clean article class, prose project summaries) alongside the
moderncv version from Steps 2-5. The user submits this version; the moderncv version
is kept as an editable source backup.

All inputs below are already in context from earlier steps. Do NOT re-read files.

---

## 7a. Gather Inputs

| Input | Source | Already in context? |
|-------|--------|-------------------|
| Job posting text | Step 0 | Yes |
| Generated CV content | Step 2/4 (cv/main_<company>.tex) | Yes |
| Candidate profile | Step 1 (.claude/skills/job-application-assistant/01-candidate-profile.md) | Yes |
| Rewrite rules | Read `personalised/rewrite-cv.txt` | **No — read this now** |
| Template structure | Read `personalised/main.tex` | **No — read this now** |

---

## 7b. Generate Personalised CV

Create `personalised/cv_<company>.tex` using the **article-class template** from
`personalised/main.tex` as the structural reference. Use `pdflatex` (not lualatex).

### Template skeleton

```latex
% CANONICAL SECTION ORDER (do not reorder):
%   PROFILE -> WORK EXPERIENCE -> PROJECTS -> EDUCATION -> SKILLS
\documentclass[11pt,a4paper]{article}
\renewcommand{\familydefault}{\sfdefault}
\usepackage[margin=0.75in]{geometry}
\usepackage[colorlinks=true,
            linkcolor=blue,
            urlcolor=blue,
            citecolor=blue]{hyperref}
\usepackage{needspace}
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage{xcolor}

\titleformat{\section}{\large\scshape\bfseries}{}{0em}{}[\titlerule]
\titlespacing{\section}{0pt}{10pt}{5pt}

\begin{document}

% Header
\begin{center}
    {\LARGE \bfseries Firstname Lastname} \\[5pt]
    Glasgow, UK $|$ +44 0000000000 $|$ \href{mailto:candidate@example.com}{candidate@example.com} $|$
    \href{https://linkedin.com/in/your-profile/}{LinkedIn} $|$ \href{https://github.com/your-github}{GitHub}
\end{center}

\vspace{10pt}

\section*{PROFILE}
% 5-7 line role-targeted summary here

\section*{WORK EXPERIENCE}
% Entries: \noindent\textbf{Company} $|$ \textbf{Role} $|$ Location \hfill Date
% Bullets: itemize with leftmargin=*, nosep

\section*{PROJECTS}
% Prose paragraphs — NOT bullet points
% Each title must be wrapped: \noindent\textbf{\href{<url>}{<Title>}} \\
% Use the Project GitHub URL table below to match the correct URL for each project.
% colorlinks=true renders hyperlinked titles blue automatically.

\section*{EDUCATION}

\section*{SKILLS}
% 5 skill categories, itemize with leftmargin=*, nosep
% KEYWORD-ONLY: strip all parentheticals and qualifiers (see rule 8 below)

\end{document}
```

### Project GitHub URLs

When writing the PROJECTS section, wrap each project title in `\href{}{}` using the correct URL.
Only include projects relevant to the JD. Match project names (titles may be slightly adapted for targeting).

| Project (as appears on CV) | GitHub URL |
|---------------------------|-----------|
| UK Data Job Market Dashboard (Power BI) | `https://github.com/your-github/uk_job_market_analysis` |
| Archival RAG System | `https://github.com/your-github/Archival_Rag_System` |
| Violence Detection using Deep Learning | `https://github.com/your-github/violence_detection` |
| Restaurant Ratings Analysis (Power BI) | `https://github.com/your-github/Rating-Analysis-Restaurant` |

### Rewrite rules to apply (from `personalised/rewrite-cv.txt`)

Apply ALL of the following while generating the CV content:

1. **Profile section**: 5-7 line role-targeted summary. Must communicate:
   - Target role and technical specialisation
   - Strongest engineering achievements (quantified)
   - Key technologies
   - Reduce repetition — only include info relevant to THIS job

2. **Experience bullets — Action -> Method -> Scale -> Result framing**:
   Every bullet must follow the pattern:
   - **Action** what you did -> **Method** how -> **Scale** scope/size -> **Result** outcome
   - Convert responsibilities into achievements with measurable outcomes
   - Remove or minimise irrelevant information

3. **Strict bullet budget**:
   | Role | Bullets |
   |------|---------|
   | Most recent (NeuraSearch) | 4-5 |
   | Middle (CL Techno) | 3 |
   | Oldest (Gamaka AI) | 2-3 |
   Never exceed these limits. If content spills, cut lowest-relevance bullets first.

4. **Projects as prose** (NOT bullet points):
   Each project = 2-3 crisp sentences as a `\noindent\textbf{Title} \\ \noindent Description`
   paragraph. Must match the JD. No `\begin{itemize}` in the Projects section.

5. **No repetition**:
   If a skill or achievement appears in both SKILLS and WORK EXPERIENCE, remove it from
   SKILLS. The experience bullet is more concrete evidence.

6. **ATS keyword optimisation**:
   - Reuse the keyword list extracted in Step 1
   - Ensure >=90% of required/preferred keywords appear in the CV text
   - If below 90%, add missing keywords where truthfully applicable in experience bullets
   - Never stuff keywords the profile does not genuinely support

7. **CL Techno title**: Use "(Volunteer) AI Engineer" — not just "AI Engineer"

8. **Skills style — keyword-only categorised list**: bold category label + comma-separated
   tools/techniques. **No parentheticals, no qualifiers, no capability clauses.** Strip all
   examples: `RAG (FAISS, BM25, reciprocal rank fusion, semantic chunking)` -> `RAG`;
   `post-deployment monitoring` -> `monitoring`; `Python (TDD, modularity, reuse)` -> `Python`;
   `AWS (EC2, S3, SageMaker)` -> `AWS`; `Ragas (faithfulness, relevancy, hallucination rate)`
   -> `Ragas`. Explanatory clauses belong in experience bullets, not here.

9. **Location heading — city only**: The header location line is `Glasgow, UK`, full stop.
   Do **not** append parentheticals like `(willing to relocate; UK Graduate visa, no
   sponsorship required)`, `(open to relocation)`, or any other notes about relocation,
   visa, or sponsorship. See `CLAUDE.md` "No relocation/visa notes in CV headings" for the
   full rule.

---

## 7c. Compile and Save

```bash
cd personalised && pdflatex -interaction=nonstopmode cv_<company>.tex
```

If compile fails, fix and recompile until clean.

Rename the output:
```powershell
Move-Item -Path "personalised/cv_<company>.pdf" -Destination "personalised/cv-firstname_lastname-<company>-$(Get-Date -Format yyyy-MM-dd).pdf" -Force
```

Clean up build artifacts:
```powershell
Remove-Item "personalised/cv_<company>.aux", "personalised/cv_<company>.log", "personalised/cv_<company>.out" -ErrorAction SilentlyContinue
```

---

## 7d. Verify

Quick check on the generated PDF:
- [ ] Exactly 1-2 pages (prefer 2 for full experience)
- [ ] Section order matches `main.tex`: PROFILE -> WORK EXPERIENCE -> PROJECTS -> EDUCATION -> SKILLS
- [ ] No orphaned section headings
- [ ] Projects section is prose, not bullets
- [ ] Project titles have GitHub hyperlinks (`\href{}{}`) rendering blue
- [ ] SKILLS is keyword-only — no parentheticals or qualifiers
- [ ] Location heading is `Glasgow, UK` only — no parentheticals
- [ ] Bullet counts match the 4-5/3/2-3 budget
- [ ] Profile is 5-7 lines

---

## 7e. Present

Tell the user:
> Personalised CV saved to `personalised/cv-firstname_lastname-<company>-<date>.pdf`
>
> This is the article-style version (submit this). The moderncv version remains at
> `cv/main_<company>.pdf` as a backup.

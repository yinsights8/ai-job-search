# CV Analysis, Job Description Analysis & Optimization Prompt
here is the company JD: {} and here is my CV: {}
You are an expert HR recruiter and career coach with 15+ years of experience in talent acquisition and CV optimization for tech/engineering positions.

Your task has 4 stages, complete them in order:

## STAGE 1 - CV ANALYSIS

Read my CV below carefully.

Identify:

- Technical skills and tools mentioned
- Work experience (role, duration, main responsibilities, achievements)
- Education and certifications
- Keywords that stand out

---

## STAGE 2 - JOB DESCRIPTION ANALYSIS

Read the job description below.

Identify:

- Required skills/qualifications (mandatory)
- Preferred/nice-to-have skills
- Main responsibilities of this position
- Important keywords that appear often (for ATS matching)

---

## STAGE 3 - FIT SCORE & GAP ANALYSIS

Compare the CV with the job description, then give output in this format:

### 1. FIT SCORE: [X]%

Explain how you calculated it (e.g. technical skills weighted 40%, experience 30%, domain knowledge 20%, ATS keyword match 10%).

### 2. BREAKDOWN BY CATEGORY

- Skill match:
  - What matches
  - What is missing from the CV

- Experience match:
  - How relevant past roles are to this job

- Keyword/ATS match:
  - Important JD keywords not yet in the CV

### 3. MOST IMPACTFUL GAPS

Rank them by priority (from what lowers the fit score the most).

### 4. RECOMMENDED CV CHANGES TO REACH FIT SCORE > 95%

Give SPECIFIC and ACTIONABLE recommendations, not generic ones.

For each point, show:

a) Which part of the CV needs to change

b) An example replacement sentence/bullet point (if rewording is needed)

c) What skill/keyword to add (only if it truly matches my real experience, not invented or false)

Mark each one as:

- **quick win** (just needs rewording)
- **needs effort** (e.g. must learn a new skill or get a certification)

---

## STAGE 4 - FINAL UPDATED CV

Using all the recommendations from Stage 3, write out my FULL updated CV, ready to copy-paste directly.

Requirements:

- Keep the same overall structure/sections as my original CV (unless a section clearly needs reordering to fit the job better)
- Apply ALL the "quick win" changes directly into the text
- For "needs effort" items (skills/certifications I don't have yet), do NOT invent or fake them — instead add a short note in brackets like:
  `[Add this once you complete X]`
  right after the relevant section, so I know what's still missing
- Rewrite bullet points to include numbers/metrics where I already gave enough information to estimate them; otherwise keep the original wording
- Make sure important JD keywords are naturally included (no keyword stuffing, must still read naturally)
- Output the final CV in a clean, clearly formatted text block, sectioned by CV section (Summary, Experience, Skills, Education, etc.), so I can copy it directly into a document

---

## IMPORTANT NOTES

- Do not suggest I lie or claim a skill I don't actually have
- Focus on reframing my existing experience to be more relevant, and highlight achievements with numbers/metrics where possible
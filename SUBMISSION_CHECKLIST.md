# LIFECORE-SWE — Kaggle Submission Checklist

**Competition:** Google DeepMind Gemma 4 Developer Agent Paper Track  
**Deadline:** November 12, 2026 at 11:59 PM UTC  
**Prize target:** Overall Best Paper ($15,000)

---

## Files Ready for Submission

| File | Purpose | Status |
|---|---|---|
| `experiments/results/m1c_*.json` | M1C retrieval & agent results | ✅ Ready |
| `experiments/results/m2_summary.json` | M2 experience benchmark | ✅ Ready |
| `experiments/results/m3_summary.json` | M3 central ablation data | ✅ Ready |
| `experiments/results/m4_summary.json` | M4 failure + ablation data | ✅ Ready |
| `experiments/experience_graph/*.db` | SQLite overlay databases | ✅ Ready |
| `experiments/experience/m2_condition_c.db` | M2 episodic store | ✅ Ready |
| `lifecore_swe_kaggle_notebook.ipynb` | Reproducibility notebook | ✅ Ready |
| `architecture_diagram.svg` | 4-stream architecture diagram | ✅ Ready |
| `README.md` | Project documentation | ✅ Ready |

---

## Step 1 — Upload Code to GitHub (do this first, ~10 minutes)

This is the single most important action for the **Verifiability** criterion (20% of your score).

```
1. Go to https://github.com/new
2. Repository name:  lifecore-swe
3. Visibility:       Public  ← required for judges to access
4. Do NOT initialize with README (you already have one)
5. Click "Create repository"
```

Then push from your local machine:

```powershell
cd "c:\Users\cool\Downloads\aistudio_agent_environment-081e6556-0190-4f3c-9aea-0396580db597-2026_09_30T21_43_05_859Z\lifecore-swe"

git init
git add README.md architecture_diagram.svg lifecore_swe_kaggle_notebook.ipynb pyproject.toml
git add lifecore_swe\ scripts\ tests\ fixtures\
git add experiments\results\ experiments\experience\ experiments\experience_graph\
git commit -m "LIFECORE-SWE: Kaggle Gemma 4 Developer Agent Paper Track submission"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/lifecore-swe.git
git push -u origin main
```

> **Note:** Do NOT commit your Google API key or any `.env` files.
> The `experiments/trajectories/` folder (if large) can be excluded via `.gitignore`.

**Copy the GitHub URL** — you will paste it into the Kaggle Writeup.

---

## Step 2 — Create Kaggle Dataset from Results (~5 minutes)

The notebook loads results from `/kaggle/input/lifecore-swe-results`. Upload the results folder as a Kaggle dataset so the notebook runs on Kaggle.

```
1. Go to https://www.kaggle.com/datasets/new
2. Dataset title:  lifecore-swe-results
3. Upload these files from experiments/results/:
   - m2_summary.json
   - m3_summary.json
   - m4_summary.json
   - retrieval_benchmark_summary.json
   - m1c_baseline_task101.json
   - m1c_graph_task101.json
   - m1c_baseline_task201.json
   - m1c_graph_task201.json
4. Visibility: Public
5. Click "Create"
```

**Copy the dataset URL** — you will add it as a data source in the notebook.

---

## Step 3 — Create and Publish the Kaggle Notebook (~10 minutes)

```
1. Go to https://www.kaggle.com/code
2. Click "New Notebook"
3. Title: LIFECORE-SWE: Experience-Conditioned Code Graphs
4. In the notebook editor, click File → Import Notebook
5. Upload:  lifecore_swe_kaggle_notebook.ipynb
6. Add your dataset:
   - Click "Add data" (right panel)
   - Search for "lifecore-swe-results"
   - Add it
7. Run All cells  (Session → Run All)
8. Verify all cells pass and charts render
9. Click "Save Version" → "Save & Run All (Commit)"
10. After it finishes, click "Share" → set to Public
```

**Copy the notebook URL** — you will paste it into the Writeup.

---

## Step 4 — Create the Kaggle Writeup (~15 minutes)

```
1. Go to the competition page:
   https://www.kaggle.com/competitions/gemma-4-developer-agent-paper-track
2. Click "New Submission" or "Submit Writeup"
3. Fill in:
```

### Title (copy exactly):
```
LIFECORE-SWE: Experience-Conditioned Code Graphs for Autonomous Software Engineering
```

### Subtitle (copy exactly):
```
Encoding Verified Agent Trajectories as Structural Priors Over Repository Graph Edges
```

### Body:
Paste the full paper from the Kiro artifact titled:
**"LIFECORE-SWE: Kaggle Competition Paper"**

After pasting, add these two lines at the top of the Introduction section:

```
**Code & Artifacts:** https://github.com/YOUR_USERNAME/lifecore-swe  
**Reproducibility Notebook:** https://www.kaggle.com/code/YOUR_KAGGLE_USERNAME/lifecore-swe-experience-conditioned-code-graphs
```

### Insert the Architecture Diagram:
In the Kaggle Writeup editor, after the System Architecture section heading, insert the diagram image.
- Upload `architecture_diagram.svg` using the image insert tool in the editor, OR
- Reference it from your GitHub raw URL:
  `https://raw.githubusercontent.com/YOUR_USERNAME/lifecore-swe/main/architecture_diagram.svg`

---

## Step 5 — Final Checks Before Submitting

Work through this checklist before clicking Submit:

- [ ] Word count is under 3,000 words (the paper is ~1,900 words — you have headroom)
- [ ] Title and subtitle are filled in (not just the body)
- [ ] GitHub link is correct and the repo is **public**
- [ ] Kaggle notebook link is correct and the notebook is **public**
- [ ] Architecture diagram is visible in the writeup preview
- [ ] Abstract is present and summarizes the central finding
- [ ] All 5 experimental sections reference real numbers from the JSON results
- [ ] Related work section has citations
- [ ] Limitations section is present
- [ ] No placeholder text like "YOUR_USERNAME" remains
- [ ] Writeup is not still in Draft — click **Submit**

---

## Step 6 — Submit

```
1. Click "Submit" (not just "Save Draft")
2. Confirm the submission on the next screen
3. Check your submission appears on your competition profile
```

---

## Prize Category Strategy

You are competing for **Overall Best Paper ($15,000)**. Your submission also qualifies for **Best New Application ($10,000)** — consider mentioning both angles:

- **Overall Best Paper:** The core novelty (structural graph conditioning vs. text injection, ablation proof)
- **Best New Application:** LIFECORE-SWE as a practical application of code graph techniques to agentic SWE workflows with Gemma 4

If the competition allows multiple category entries, submit the same writeup under both.

---

## Scoring Reminder

| Criterion | Weight | Your Strength |
|---|---|---|
| Novelty | 20% | ✅ Structural memory vs. text injection — not previously demonstrated |
| Quality | 20% | ✅ 5 conditions × 5 tasks, 2 safety ablations, controlled sequential benchmark |
| Relevance | 20% | ✅ Directly addresses Gemma 4 agentic SWE on real codebases |
| Verifiability | 20% | ✅ GitHub repo + Kaggle notebook + SQLite DBs + 121 passing tests |
| Clarity | 20% | ✅ Architecture diagram, structured paper, concrete numbers throughout |

---

## Emergency Fallback (if GitHub/notebook setup runs short on time)

If you run out of time before the deadline, submit the writeup **without** the notebook link. A strong paper with no notebook is still competitive. The notebook link upgrades Verifiability from good to excellent — but the paper itself is the primary artifact.

**Minimum viable submission = Writeup text only. Do not miss the deadline waiting for the notebook to finish running.**

---

*Checklist generated: October 14, 2026*  
*Deadline: November 12, 2026 at 11:59 PM UTC — 29 days remaining*

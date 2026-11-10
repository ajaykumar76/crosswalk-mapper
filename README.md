# CSF 2.0 to SP 800-53 Control Crosswalk Mapper (scored against NIST's own mapping)

Given a NIST Cybersecurity Framework 2.0 subcategory, suggest the NIST SP 800-53 Rev. 5 controls that
implement it, and **measure the suggestions against NIST's official CSF 2.0 to SP 800-53 crosswalk**. No
labels were written by me: the answer key is NIST's own mapping.

> **Short version of the result:** plain sentence embeddings (`all-MiniLM-L6-v2`) put at least one
> official control in the top 5 for **76%** of unseen subcategories (a "most-mapped controls" baseline: 31%),
> and in the top 10 for **93%**. But only **42%** of the official controls appear in the top 10, and a local
> 3B LLM used to re-rank the candidates made the top 5 **worse**. This is a candidate finder for a human
> reviewer, not an automatic mapper.

> **Not an official NIST product.** I did not write the mapping. The crosswalk is NIST's, and it is one
> expert view: a suggestion that is not in it is not necessarily wrong, so the scores understate real usefulness.

## Data

- **Ground truth:** NIST's *CSF 2.0 to SP 800-53 Rev. 5* concept crosswalk (draft, 740 mapping rows, 106
  subcategories, 210 distinct controls). It agrees exactly with the SP 800-53 Rev. 5.2.0 references in NIST's
  CSF 2.0 Reference Tool export for all 106 subcategories.
- **Subcategory text and implementation examples:** NIST CSF 2.0 Reference Tool export.
- **Control text:** NIST's OSCAL catalog of SP 800-53 Rev. 5 (withdrawn controls removed): 1,014 candidate
  controls, 300 base controls and 714 enhancements. 17 of the 210 target controls are enhancements.
- **Dropped:** one withdrawn target control (ra-4) and three crosswalk rows whose control ids my parser could not read.
- **Split by CSF category, not at random:** 51 dev and 55 test subcategories, so related subcategories do not leak between splits.
- The raw NIST downloads are not in this repo (see `.gitignore`); `data/subcategories.json` and
  `data/controls.json` are the derived files. Check NIST's terms of use before reusing the NIST text.

## Methods

| Method | What it does |
|---|---|
| random | shuffled list of all 1,014 controls (one seed) |
| prior | the most frequently mapped controls, counted only from dev subcategories of *other* CSF categories |
| embed | `all-MiniLM-L6-v2` similarity between the subcategory (plus up to two implementation examples) and each control's title and statement |
| embed + LLM rerank | local `llama3.2` picks the best 5 of the top 15 embedding hits; answers that are not candidates are discarded |

## Metrics

**hit@5 / hit@10:** at least one official control in the top 5 / 10. **recall@10:** share of the official controls
found in the top 10 (subcategories map to 1 to 40 controls, median 5). **MRR:** 1 divided by the rank of the first
official control. **family hit@5:** a control from the right control family (such as AC or AU); shown for
reference only, since random guessing already reaches about 45% because there are only about 20 families.
95% bootstrap intervals over subcategories; they are optimistically narrow because related subcategories share controls.

## Results

### Dev (51 subcategories), four variants tried

| | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|
| random | 0% | 0% | 0% | 1% |
| prior | 35% | 39% | 15% | 31% |
| embed (MiniLM) | 59% | 67% | 30% | 43% |
| **embed + examples** (chosen) | 57% | 75% | 36% | 45% |
| embed, `bge-small-en-v1.5` | 41% | 57% | 26% | 33% |
| embed + LLM rerank | 33% | 67% | 31% | 27% |

**Rule fixed before the test run:** pick the variant with the best average of hit@5 and recall@10 (this chose
MiniLM + examples, but only narrowly: the difference to plain MiniLM is inside the noise). The LLM re-rank was only
to be kept if it beat embeddings on both metrics; it did not.

### Test (55 subcategories), run once

| | hit@5 | hit@10 | recall@10 | MRR |
|---|---|---|---|---|
| random | 9% | 9% | 1% | 9% |
| prior | 31% | 55% | 23% | 27% |
| **embed + examples** | **76% (65-87)** | **93% (85-98)** | **42% (33-51)** | **57% (47-67)** |
| embed + LLM rerank | 67% (55-78) | 93% (85-98) | 42% (33-51) | 44% (35-54) |

## What I take from this

- **Embeddings clearly beat a popularity baseline** (76% vs 31% hit@5), so the result is not just "guess the common controls".
- **The 3B LLM re-rank hurt the top of the list** on both splits (dev 33% vs 59%, test 67% vs 76% hit@5). It followed the output format but chose worse than the embedding order. I kept it as a negative result.
- **Finding one right control is easy, finding all of them is not:** 93% hit@10 versus 42% recall@10.
- Test scores are higher than dev (76% vs 57% hit@5). The two splits contain different CSF categories, so I do not read this as improvement.
- Random's 9% on test is a quirk of one seed and one subcategory that maps to 40 controls.

## Limitations

- One crosswalk, one expert view; the file is labelled a draft concept crosswalk.
- Small evaluation sets (51 and 55 subcategories), correlated items, one embedding model family, one small LLM.
- Only SP 800-53 Rev. 5 is covered. ISO/IEC 27001 mappings are in NIST's export but are not evaluated here.
- Four dev variants were tried; the setup was fixed before the single test run.
- The prompt for the re-rank was written once; a larger model or a different prompt might do better. Not tested.

## Run it

```powershell
pip install -r requirements.txt
ollama pull llama3.2
# put the NIST files in data\ (csf2.xlsx, the crosswalk xlsx, NIST_SP-800-53_rev5_catalog.json)
python src\00_build_dataset.py
python src\01_crosswalk_eval.py --split dev --methods random,prior,embed --examples
python src\01_crosswalk_eval.py --split test --methods random,prior,embed,rerank --examples --tag final   # once
```

## Files

```
src/00_build_dataset.py    builds subcategories.json and controls.json from the NIST files
src/01_crosswalk_eval.py   baselines, embeddings, LLM re-rank, evaluation
data/                      derived JSON files
reports/                   saved results of each run
```

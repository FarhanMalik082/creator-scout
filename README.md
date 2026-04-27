# creator-scout

A [Command Code](https://commandcode.ai) skill that discovers dev-focused YouTube creators worth pitching for a dev tool brand. Runs in ~10 minutes for under $0.35 in tokens on the $1 Go plan.

Built as part of the Command Code growth team's outreach workflow. Replaces the parts of $300/mo influencer research SaaS tools that matter for B2B dev tool marketing.

**Current version: v0.2** — adds human-in-the-loop topic review and stricter validation between stages.

## What it does

You give it 5–10 seed creators you already consider good sponsor fits. It returns a ranked CSV of ~80 candidate channels with a niche relevance score, niche tag, and a short note on each.

The pipeline:

1. **Pull seed titles** — fetches recent video titles from each seed channel
2. **Extract topics** — Command Code reads the titles and proposes 10–15 specific searchable topics
3. **Review topics (human-in-the-loop)** — Command Code shows you the topics and waits for your approval before continuing
4. **Search YouTube** — finds channels whose recent videos cover those approved topics
5. **Score candidates** — Command Code scores each candidate's niche fit 0–100 based on its recent titles
6. **Rank** — combines the niche score with topic overlap and channel size into a final ranked CSV

Stages 2 and 5 use Command Code's open-source models (Kimi K2.6 by default). Everything else is plain Python with `yt-dlp`.

### Why the topic review matters

LLM topic extraction is non-deterministic. The same seeds can produce specific topics on one run ("python dependency injection", "neovim configuration") and generic topics on another ("python tutorial", "react nextjs tutorial"). Generic topics dominate the YouTube search results and crowd out the niche channels you actually want to find.

The topic-review checkpoint takes ~10 seconds of your attention and prevents 7 minutes of bad downstream work. If the topics look generic, you can paste a corrected list inline and the pipeline uses your version.

## Sample output

A real run on seeds in the dev-tools / Python / data-engineering niche surfaced channels like:

| Channel | Subs | Niche | Score |
|---|---|---|---|
| ThePrimeagen | 541k | dev-tools | 84.9 |
| Josean Martinez | 66.9k | dev-tools | 78.6 |
| DevOps Toolbox | 116k | dev-tools | 78.1 |
| typecraft | 227k | dev-tools | 71.2 |
| TJ DeVries | 114k | dev-tools | 70.3 |

Full sample output: [`examples/sample_output.csv`](examples/sample_output.csv).

## Install

You need Python 3.9+ and Command Code installed. If you don't have Command Code yet, grab it at [commandcode.ai](https://commandcode.ai).

```bash
git clone https://github.com/FarhanMalik082/creator-scout.git
cd creator-scout
pip install -r requirements.txt
```

The skill folder lives at `.commandcode/skills/creator-scout/`. To use it from another Command Code project, copy that folder into your project's `.commandcode/skills/` directory.

## Use

1. Edit `.commandcode/skills/creator-scout/seeds.json` with 5–10 anchor creators in your niche.
2. Run Command Code in the project directory:
   ```bash
   command-code
   ```
3. Ask it to run creator-scout:
   ```
   run creator-scout
   ```
4. **When it shows you the extracted topics, review them.** Type `continue` to proceed with the topics as-is, or paste a corrected JSON to override.
5. Wait ~7–10 minutes for Stages 4–6 to finish. Top 10 prints to terminal; full results are in the CSV.

Total runtime is ~10 minutes for 8 seeds and 80 candidates.

## seeds.json format

```json
{
  "brand": "YourProductName",
  "niche": "dev-tools",
  "seeds": [
    {"handle": "@SomeChannel", "notes": "what they cover"},
    {"handle": "@AnotherChannel", "notes": "what they cover"}
  ]
}
```

## Configuration knobs

The `scout.py` script accepts flags if you want to run stages individually:

```bash
# Stage 1 only — pull seed titles
python .commandcode/skills/creator-scout/scripts/scout.py stage1 \
  --per-seed 30 --output seeds_data.json

# Stage 2 only — search candidates from a topics file
# Note: --seeds-data is REQUIRED so seed channels are excluded from candidates
python .commandcode/skills/creator-scout/scripts/scout.py stage2 \
  --topics topics.json --seeds-data seeds_data.json \
  --per-search 20 --max-candidates 80 --output candidates.json

# Stage 3 only — combine scores into final CSV
python .commandcode/skills/creator-scout/scripts/scout.py stage3 \
  --raw candidates.json --scores scores.json \
  --output-json final.json --output-csv final.csv
```

Stage 3 validates that the scores file contains unique channel IDs and that every score corresponds to a real candidate. It exits with a clear error if either check fails so you can re-score and retry.

## Limitations

- **Topic specificity matters.** Vague seeds produce vague topics. Even with the human review step, a careful seed list gives you better starting topics to approve.
- **Cloud IPs get rate-limited.** YouTube blocks `yt-dlp` searches from AWS, GCP, and DigitalOcean addresses pretty aggressively. Run on a residential IP for best results.
- **Sub counts can lag.** YouTube's display values update on their own schedule. Treat them as approximate.
- **Run-to-run variance is real but bounded.** With the topic-review step you control the input to Stage 4, which is the largest source of variance. The remaining variance comes from YouTube's search ranking and the LLM's scoring at the margins (a few candidates near score 70 may shift to 65 or 75 between runs).

## Roadmap

- `--max-subs` flag to filter out tier-1 creators (Fireship, etc.) when running on a smaller budget — most B2B dev tools convert better in the 20k–200k range
- Sponsor history detection — cross-reference candidates' descriptions against known dev-tool advertiser domains
- Cache layer so re-runs in the same week don't re-fetch identical data
- A `topics_pinned.json` option for fully deterministic runs in CI/scheduled contexts

## License

MIT — see [LICENSE](LICENSE).

## Author

Built by [Farhan Malik](https://github.com/FarhanMalik082), PMM at Command Code.
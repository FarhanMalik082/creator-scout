# creator-scout

A [Command Code](https://commandcode.ai) skill that discovers dev-focused YouTube creators worth pitching for a dev tool brand. Runs in ~15 minutes for under $0.25 in tokens on the $1 Go plan.

Built as part of the Command Code growth team's outreach workflow. Replaces the parts of $300/mo influencer research SaaS tools that matter for B2B dev tool marketing.

## What it does

You give it 5–10 seed creators you already consider good sponsor fits. It returns a ranked CSV of ~80 candidate channels with a niche relevance score, niche tag, and a short note on each.

The pipeline:

1. **Pull seed titles** — fetches recent video titles from each seed channel
2. **Extract topics** — Command Code reads the titles and identifies 10–15 specific searchable topics
3. **Search YouTube** — finds channels whose recent videos cover those same topics
4. **Score candidates** — Command Code scores each candidate's niche fit 0–100 based on its recent titles
5. **Rank** — combines the niche score with topic overlap and channel size into a final ranked CSV

Stages 2 and 4 use Command Code's open-source models (Kimi K2.6 by default). Everything else is plain Python with `yt-dlp`.

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

The skill orchestrates all 5 stages. Total runtime is ~15 minutes for 8 seeds and 80 candidates.

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
python .commandcode/skills/creator-scout/scripts/scout.py stage2 \
  --topics topics.json --seeds-data seeds_data.json \
  --per-search 20 --max-candidates 80 --output candidates.json

# Stage 3 only — combine scores into final CSV
python .commandcode/skills/creator-scout/scripts/scout.py stage3 \
  --raw candidates.json --scores scores.json \
  --output-json final.json --output-csv final.csv
```

## Limitations

- Topic specificity matters. Vague seeds produce vague topics produce noisy results.
- YouTube can rate-limit `yt-dlp` searches from cloud IPs. Run locally for best results.
- The LLM occasionally hallucinates channel IDs at the boundary between stages 2 and 3. The script catches this and exits cleanly so you can re-score.
- Sub counts come from YouTube's display value and can lag real subscriber counts by hours or days.

## Roadmap

- `--max-subs` flag to filter out tier-1 creators (Fireship, etc.) when running on a smaller budget
- Sponsor history detection — cross-reference candidates' descriptions against known dev-tool advertiser domains
- Cache layer so re-runs in the same week don't re-fetch identical data

## License

MIT — see [LICENSE](LICENSE).

## Author

Built by [Farhan Malik](https://github.com/FarhanMalik082), PMM at Command Code.

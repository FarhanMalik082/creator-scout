---
name: creator-scout
description: Discover dev-focused YouTube channels worth pitching for a dev tool brand, using content-based discovery. Use when the user asks to find YouTubers to sponsor, discover dev creators, build an influencer outreach list, or prospect YouTube channels similar to a set of seed channels. The tool extracts topics from seed channels' recent video titles, searches YouTube for channels covering the same topics, and ranks candidates by topic overlap, size, and activity.
allowed-tools: Read Write Bash(python:*) Bash(pip:*)
metadata:
  author: dexter
  version: "0.1"
---

# creator-scout

You help the user build an influencer outreach list by discovering dev-focused YouTube channels whose content overlaps with a set of seed channels. The user has a dev tool product and needs to find channels in the same content niche as their seeds.

## When to use this skill

Trigger on:
- "run creator-scout"
- "find me dev YouTubers to sponsor"
- "discover channels for CommandCode"
- "build me an influencer outreach list"
- "find creators similar to my seeds"

## Architecture

This is a 3-stage pipeline. You run the stages in order and do LLM work in between.

**Stage 1** — Seed analysis (script, no LLM): pull recent video titles from each seed.
**Stage 2a** — Topic extraction (you, LLM): read seed titles, produce a unified topic list.
**Stage 2b** — Candidate search (script, no LLM): search YouTube for each topic, collect channels.
**Stage 3a** — Niche scoring (you, LLM): for each candidate's sample titles, judge niche relevance.
**Stage 3b** — Final ranking + CSV (script, no LLM): score, sort, write outputs.

Do NOT skip stages or do them out of order. Each stage's output is the next stage's input.

## Step-by-step instructions

### Stage 1: Pull seed titles

Run:

```bash
python .commandcode/skills/creator-scout/scripts/scout.py stage1 --output /tmp/creator_scout_seeds.json
```

This reads `seeds.json`, pulls ~30 recent video titles per seed channel, and writes structured data to `/tmp/creator_scout_seeds.json`. Takes 2–4 minutes.

If any seed returns 0 videos, report which ones failed and continue with the rest.

### Stage 2a: Extract topics (YOU do this)

Read `/tmp/creator_scout_seeds.json`. You'll see an array of seeds, each with a list of recent video titles.

Your job: produce a unified list of 10–15 specific, searchable TOPICS that describe what these channels collectively cover. Topics should be:
- 2–4 words each
- Specific enough to search on YouTube (not "programming" — too broad)
- Diverse across sub-niches the seeds cover
- Free of brand names (don't include "Cursor" or "Claude Code")

Good examples: `"python decorators"`, `"react server components"`, `"ai coding agents"`, `"clean code refactoring"`, `"docker production deployment"`.
Bad examples: `"programming"` (too broad), `"cursor vs copilot"` (brand-specific), `"latest news"` (temporal).

Write your output to `/tmp/creator_scout_topics.json` in this shape:

```json
{
  "topics": [
    "ai coding agents",
    "python clean code",
    "react patterns"
  ],
  "reasoning": "Brief note on why these topics — so a human can sanity-check your choices."
}
```

### Stage 2b: Candidate search

Run:

```bash
python .commandcode/skills/creator-scout/scripts/scout.py stage2 --topics /tmp/creator_scout_topics.json --output /tmp/creator_scout_candidates_raw.json
```

This searches YouTube for each topic, collects unique channels, and enriches them with sub counts and recent video titles. Takes 5–10 minutes. Output is an unranked list of 80–150 candidates.

### Stage 3a: Niche scoring (YOU do this)

Read `/tmp/creator_scout_candidates_raw.json`. Each candidate has a `channel_name`, `sub_count`, and `sample_titles` (up to 8 recent titles).

For each candidate, score niche relevance on 0–100:

- **100**: This channel is clearly in the same niche as the seeds. Dev-focused, educational, similar topics.
- **70–90**: Mostly relevant, some overlap with seeds' topics.
- **40–69**: Tangentially related (e.g. general tech news that occasionally covers dev topics).
- **0–39**: Off-topic (gaming, lifestyle vlogs, crypto hype, non-dev AI content aimed at non-developers).

Also assign each candidate a `niche_tag`: one of `dev-tools`, `web-dev`, `python-data`, `ai-ml-dev`, `mobile-dev`, `devops-cloud`, `programming-education`, `tech-commentary`, `off-topic`.

Write your scores to `/tmp/creator_scout_scores.json` in this shape:

```json
{
  "scores": [
    {"channel_id": "UC...", "niche_score": 85, "niche_tag": "web-dev", "note": "Clear React/Next.js focus, educational"},
    {"channel_id": "UC...", "niche_score": 20, "niche_tag": "off-topic", "note": "Mostly crypto and trading"}
  ]
}
```

Important: include EVERY candidate from the input (even off-topic ones — we filter in the next stage, we don't just drop them). Channel IDs must match exactly.

### Stage 3b: Final ranking

Run:

```bash
python .commandcode/skills/creator-scout/scripts/scout.py stage3 --raw /tmp/creator_scout_candidates_raw.json --scores /tmp/creator_scout_scores.json --output-json /tmp/creator_scout_final.json --output-csv /tmp/creator_scout_final.csv
```

This combines your scores with the structural signals (size, activity) and produces the final ranked CSV.

### Reporting to the user

Once Stage 3b completes, show a brief terminal summary:
- Total candidates found
- Candidates above niche_score 70 (these are the pitch-worthy ones)
- Top 10 by final_score with: handle/name, subs, niche_tag, niche_score, note
- Path to the CSV

DO NOT paste the whole 80-candidate list into chat. The CSV is for that.

## Edge cases

- **A seed returns no videos:** report it, continue with remaining seeds. If 3+ seeds fail, stop and ask the user to check the handles.
- **Stage 2b returns fewer than 20 candidates:** topics may have been too narrow. Ask the user if they want to retry Stage 2a with broader topics.
- **YouTube rate-limits:** the script backs off and retries. If it hits hard limits, it writes what it has so far and exits with code 1. Tell the user to re-run Stage 2b in an hour.
- **A channel ID in your scores doesn't match the raw data:** Stage 3b will flag it and exit. Re-read the raw JSON and re-score — don't hallucinate channel IDs.

## Cost notes

This skill uses CommandCode's LLM twice per run (Stage 2a and Stage 3a). Expected total token cost under $0.20 with the Go plan's open-source models. No external API keys required.
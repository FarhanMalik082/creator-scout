---
name: creator-scout
description: Discover dev-focused YouTube channels worth pitching for a dev tool brand, using content-based discovery. Use when the user asks to find YouTubers to sponsor, discover dev creators, build an influencer outreach list, or prospect YouTube channels similar to a set of seed channels. The tool extracts topics from seed channels' recent video titles, searches YouTube for channels covering the same topics, and ranks candidates by topic overlap, size, and activity.
allowed-tools: Read Write Bash(python:*) Bash(pip:*)
metadata:
  author: dexter
  version: "0.2"
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

This is a 5-stage pipeline. You run the stages in order and do LLM work in between. There is one human-in-the-loop checkpoint between Stage 2a and Stage 2b — DO NOT skip it.

**Stage 1** — Seed analysis (script, no LLM): pull recent video titles from each seed.
**Stage 2a** — Topic extraction (you, LLM): read seed titles, produce a unified topic list.
**Stage 2a-review** — Topic review (human-in-the-loop): show topics to user, wait for confirmation.
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

Your job: produce a unified list of 10–15 SPECIFIC, searchable TOPICS that describe what these channels collectively cover. Topics must be:
- 2–4 words each
- **Specific, not generic.** This matters more than anything. "Python dependency injection" is good. "Python tutorial" is bad. "Neovim configuration" is good. "Terminal productivity tools" is bad.
- Diverse across sub-niches the seeds cover
- Free of brand names (don't include "Cursor" or "Claude Code")

**The specificity rule, restated:** generic topics like "react nextjs tutorial" or "fastapi backend tutorial" pull every mass-market education channel on YouTube. They will dominate the results and crowd out the niche channels you actually want. Always prefer the specific noun phrase from the seeds' titles over the generic version.

Good examples: `"python decorators"`, `"react server components"`, `"ai coding agents"`, `"clean code refactoring"`, `"docker production deployment"`, `"dotfiles git workflow"`, `"pyspark data engineering"`.

Bad examples: `"programming"` (too broad), `"cursor vs copilot"` (brand-specific), `"latest news"` (temporal), `"react nextjs tutorial"` (generic), `"sql database tutorial"` (generic).

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

### Stage 2a-review: HUMAN APPROVAL — DO NOT SKIP

After writing the topics file, STOP and show the topics to the user. Print exactly this format:

```
I extracted these 15 topics from your seeds. Review before I run candidate search.

  1. [topic 1]
  2. [topic 2]
  ...

Generic topics produce mass-market candidates (Fireship, freeCodeCamp, etc).
Specific topics produce niche channels (terminal/vim creators, narrow domain experts).

Type 'continue' to proceed, OR paste corrected topics to override.
```

WAIT for the user's response. Do NOT proceed to Stage 2b until they explicitly:
- Type "continue" or "proceed" or "go" → use topics as-is
- Paste a corrected list of topics → write the corrected list to `/tmp/creator_scout_topics.json` and proceed
- Ask for adjustments → revise topics and show again, loop until they approve

This step exists because LLM topic extraction is non-deterministic. The same seeds can produce specific OR generic topics on different runs. A 10-second human review prevents 7 minutes of bad downstream work.

### Stage 2b: Candidate search

Once user has approved the topics, run:

```bash
python .commandcode/skills/creator-scout/scripts/scout.py stage2 --topics /tmp/creator_scout_topics.json --seeds-data /tmp/creator_scout_seeds.json --output /tmp/creator_scout_candidates_raw.json
```

**Critical: the `--seeds-data` flag is mandatory.** Without it, seed channels can appear in the candidate output, which contaminates the results. The script uses the seeds file to dedupe seeds out of candidates.

This searches YouTube for each topic, collects unique channels, and enriches them with sub counts and recent video titles. Takes 5–10 minutes. Output is an unranked list of 80–150 candidates.

After stage2 completes, verify two things before continuing:
1. The output JSON's `candidates` array has at least 30 entries
2. None of the candidates' channel_ids appear in the seeds data

If verification fails, stop and report the issue to the user.

### Stage 3a: Niche scoring (YOU do this)

Read `/tmp/creator_scout_candidates_raw.json`. Each candidate has a `channel_id`, `channel_name`, `sub_count`, and `sample_titles` (up to 8 recent titles).

For each candidate, score niche relevance on 0–100:

- **100**: This channel is clearly in the same niche as the seeds. Dev-focused, educational, similar topics.
- **70–90**: Mostly relevant, some overlap with seeds' topics.
- **40–69**: Tangentially related (e.g. general tech news that occasionally covers dev topics).
- **0–39**: Off-topic (gaming, lifestyle vlogs, crypto hype, non-dev AI content aimed at non-developers).

Also assign each candidate a `niche_tag`: one of `dev-tools`, `web-dev`, `python-data`, `ai-ml-dev`, `mobile-dev`, `devops-cloud`, `programming-education`, `tech-commentary`, `off-topic`.

Each `note` should be ONE short sentence — what they post about and why you scored them this way.

**CRITICAL RULES — failure to follow these will fail the run:**

1. Score EVERY candidate from the input. All of them. Don't skip any.
2. Use the EXACT channel_id from the input — copy-paste, don't paraphrase, don't invent.
3. Do NOT include duplicate channel_ids in your output. Before writing, verify your scores list has unique channel_ids only.
4. Do NOT score seed channels. Stage 2b should have removed them, but if any slip through, score them 0 with niche_tag "seed" and note "seed channel — should not be a candidate".
5. Don't invent product names in notes (no "OpenClaw" or "OpenCode" if those aren't real products in the source data).

Write your scores to `/tmp/creator_scout_scores.json` in this shape:

```json
{
  "scores": [
    {"channel_id": "UC...", "niche_score": 85, "niche_tag": "web-dev", "note": "Clear React/Next.js focus, educational"},
    {"channel_id": "UC...", "niche_score": 20, "niche_tag": "off-topic", "note": "Mostly crypto and trading"}
  ]
}
```

After writing, **verify your output**:
- Count of unique channel_ids equals count of entries in `scores` array
- Every channel_id in your scores file matches a channel_id in the candidates file (no hallucinated IDs)

If either check fails, regenerate the scores until both pass.

### Stage 3b: Final ranking

Run:

```bash
python .commandcode/skills/creator-scout/scripts/scout.py stage3 --raw /tmp/creator_scout_candidates_raw.json --scores /tmp/creator_scout_scores.json --output-json /tmp/creator_scout_final.json --output-csv /tmp/creator_scout_final.csv
```

The script will fail loudly if there are missing or duplicate scores. If it fails, regenerate Stage 3a's output.

### Reporting to the user

Once Stage 3b completes, show a brief terminal summary:
- Total candidates found
- Candidates above niche_score 70 (these are the pitch-worthy ones)
- Top 10 by final_score with: handle/name, subs, niche_tag, niche_score, note
- Path to the CSV

DO NOT paste the whole 80-candidate list into chat. The CSV is for that.

## Edge cases

- **A seed returns no videos:** report it, continue with remaining seeds. If 3+ seeds fail, stop and ask the user to check the handles.
- **User rejects topics in Stage 2a-review:** revise and show again. Don't run Stage 2b until they approve.
- **Stage 2b returns fewer than 30 candidates:** topics may have been too narrow. Ask the user if they want to retry Stage 2a with broader topics.
- **YouTube rate-limits:** the script backs off and retries. If it hits hard limits, it writes what it has so far and exits with code 1. Tell the user to re-run Stage 2b in an hour.
- **A channel ID in your scores doesn't match the raw data:** Stage 3b will exit. Re-read the raw JSON and re-score — don't hallucinate channel IDs.
- **Duplicate channel_ids in your scores:** Stage 3b will catch this. Re-score with unique IDs only.

## Cost notes

This skill uses CommandCode's LLM twice per run (Stage 2a and Stage 3a). Expected total token cost ~$0.30 with the Go plan's open-source models. The human-in-the-loop topic review costs nothing additional — the LLM doesn't think while waiting. No external API keys required.
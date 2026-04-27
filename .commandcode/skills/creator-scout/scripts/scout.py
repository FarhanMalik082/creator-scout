"""creator-scout — content-based discovery for dev-focused YouTube channels.

Runs in 3 stages. LLM work (topic extraction, niche scoring) happens in
CommandCode between stages. This script does all the non-LLM plumbing:
pulling video titles, searching YouTube, enriching channels, scoring,
writing CSV.

Usage:
    python scout.py stage1 --output seeds.json
    python scout.py stage2 --topics topics.json --output candidates_raw.json
    python scout.py stage3 --raw candidates_raw.json --scores scores.json \\
        --output-json final.json --output-csv final.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yt_dlp
except ImportError:
    print("Missing dependency: yt-dlp. Install: pip install yt-dlp", file=sys.stderr)
    sys.exit(1)


SKILL_DIR = Path(__file__).parent.parent
SEEDS_FILE = SKILL_DIR / "seeds.json"


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------

def normalize_handle(handle: str) -> str:
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = f"@{handle}"
    return handle


def safe_sleep(seconds: float) -> None:
    """Rate limiter wrapper so we can swap in jitter later if needed."""
    time.sleep(seconds)


def ytdlp_extract(url: str, opts_overrides: Optional[dict] = None) -> Optional[dict]:
    """Thin wrapper with consistent defaults and error logging."""
    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
    }
    if opts_overrides:
        opts.update(opts_overrides)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"  ! yt-dlp failed for {url}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


# -----------------------------------------------------------------------------
# STAGE 1: Pull recent titles for each seed
# -----------------------------------------------------------------------------

@dataclass
class SeedAnalysis:
    handle: str
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    sub_count: Optional[int] = None
    recent_titles: list[str] = field(default_factory=list)
    error: Optional[str] = None


def stage1_analyze_seed(handle: str, video_limit: int) -> SeedAnalysis:
    handle = normalize_handle(handle)
    print(f"\n=== Seed: {handle} ===", file=sys.stderr)

    analysis = SeedAnalysis(handle=handle)

    # Pull videos (flat list — no description, we only need titles)
    videos_url = f"https://www.youtube.com/{handle}/videos"
    info = ytdlp_extract(videos_url, {
        "extract_flat": True,
        "playlistend": video_limit,
    })

    if not info:
        analysis.error = "channel not accessible"
        return analysis

    # Channel metadata from the videos-list response
    analysis.channel_id = info.get("channel_id") or info.get("id")
    analysis.channel_name = info.get("channel") or info.get("uploader") or info.get("title")
    analysis.sub_count = info.get("channel_follower_count")

    entries = (info.get("entries") or [])[:video_limit]
    titles = [e.get("title", "").strip() for e in entries if e.get("title")]
    analysis.recent_titles = [t for t in titles if t]

    print(f"  {analysis.channel_name or handle}: "
          f"{analysis.sub_count or '?'} subs, "
          f"{len(analysis.recent_titles)} recent titles", file=sys.stderr)

    return analysis


def cmd_stage1(args) -> int:
    # Load seeds config
    try:
        with open(SEEDS_FILE, "r", encoding="utf-8") as f:
            seeds_config = json.load(f)
    except FileNotFoundError:
        print(f"seeds.json not found at {SEEDS_FILE}", file=sys.stderr)
        return 2

    seed_handles = [s["handle"] for s in seeds_config["seeds"]]
    print(f"Stage 1: pulling recent titles for {len(seed_handles)} seeds "
          f"({args.per_seed} titles each)...", file=sys.stderr)

    analyses: list[SeedAnalysis] = []
    for h in seed_handles:
        analyses.append(stage1_analyze_seed(h, args.per_seed))
        safe_sleep(0.5)

    failed = [a for a in analyses if not a.recent_titles]
    succeeded = [a for a in analyses if a.recent_titles]

    print(f"\nStage 1 done: {len(succeeded)} seeds succeeded, {len(failed)} failed",
          file=sys.stderr)
    if failed:
        for a in failed:
            print(f"  ! failed: {a.handle} ({a.error or 'no titles'})", file=sys.stderr)

    if len(succeeded) < 2:
        print("Not enough seeds with data to continue. Check your handles.",
              file=sys.stderr)
        return 1

    payload = {
        "brand": seeds_config.get("brand"),
        "niche_hint": seeds_config.get("niche"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seeds": [asdict(a) for a in analyses],
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {args.output}", file=sys.stderr)
    print(f"\n>> NEXT: read this file, extract 10-15 topics, "
          f"write to /tmp/creator_scout_topics.json, then run stage2.",
          file=sys.stderr)
    return 0


# -----------------------------------------------------------------------------
# STAGE 2: Search YouTube for each topic, collect + enrich candidates
# -----------------------------------------------------------------------------

@dataclass
class Candidate:
    channel_id: str
    channel_name: str
    handle: Optional[str] = None
    sub_count: Optional[int] = None
    matching_topics: list[str] = field(default_factory=list)
    topic_overlap: int = 0
    sample_titles: list[str] = field(default_factory=list)
    last_upload_days_ago: Optional[int] = None
    upload_count_30d: int = 0


def stage2_search_topic(topic: str, per_search: int) -> list[dict]:
    """Search YouTube for a topic. Return unique uploader channels from results."""
    query = f"ytsearch{per_search}:{topic}"
    info = ytdlp_extract(query, {"extract_flat": True})
    if not info:
        return []

    entries = info.get("entries") or []
    seen_channels = set()
    channels = []
    for e in entries:
        cid = e.get("channel_id") or e.get("uploader_id")
        if not cid or cid in seen_channels:
            continue
        seen_channels.add(cid)
        channels.append({
            "channel_id": cid,
            "channel_name": e.get("channel") or e.get("uploader") or "",
            "handle": e.get("uploader_id") or None,
            "result_title": e.get("title", ""),
        })
    return channels


def stage2_enrich_channel(cid: str, sample_title_count: int) -> dict:
    """Pull sub count and a few recent video titles for a candidate channel."""
    url = f"https://www.youtube.com/channel/{cid}/videos"
    info = ytdlp_extract(url, {
        "extract_flat": True,
        "playlistend": sample_title_count,
    })
    if not info:
        return {}

    entries = (info.get("entries") or [])[:sample_title_count]
    titles = [e.get("title", "").strip() for e in entries if e.get("title")]

    # Try to figure out last upload recency (rough — extract_flat doesn't give dates reliably)
    # We leave this None for v0.1 and let the LLM stage use titles only.

    return {
        "channel_name": info.get("channel") or info.get("uploader") or info.get("title"),
        "sub_count": info.get("channel_follower_count"),
        "sample_titles": titles,
    }


def cmd_stage2(args) -> int:
    # Load topics
    with open(args.topics, "r", encoding="utf-8") as f:
        topics_data = json.load(f)
    topics = topics_data.get("topics", [])
    if not topics:
        print("No topics in topics file. Stage 2a must run first.", file=sys.stderr)
        return 1

    # Also load seed IDs so we can exclude them from candidates
    seed_channel_ids: set[str] = set()
    try:
        with open(args.seeds_data, "r", encoding="utf-8") as f:
            seeds_data = json.load(f)
        for s in seeds_data.get("seeds", []):
            if s.get("channel_id"):
                seed_channel_ids.add(s["channel_id"])
    except FileNotFoundError:
        print(f"  (warning: {args.seeds_data} not found, can't exclude seeds)",
              file=sys.stderr)

    print(f"Stage 2: searching {len(topics)} topics "
          f"({args.per_search} results per topic)...", file=sys.stderr)

    # Candidates keyed by channel_id; accumulate topic matches
    candidates: dict[str, Candidate] = {}

    for i, topic in enumerate(topics, 1):
        print(f"\n  [{i}/{len(topics)}] searching: {topic!r}", file=sys.stderr)
        channels = stage2_search_topic(topic, args.per_search)
        for ch in channels:
            cid = ch["channel_id"]
            if cid in seed_channel_ids:
                continue
            if cid not in candidates:
                candidates[cid] = Candidate(
                    channel_id=cid,
                    channel_name=ch["channel_name"],
                    handle=ch.get("handle"),
                )
            c = candidates[cid]
            if topic not in c.matching_topics:
                c.matching_topics.append(topic)
                c.topic_overlap += 1
        safe_sleep(0.4)

    print(f"\n  found {len(candidates)} unique candidate channels", file=sys.stderr)

    # Cap at max_candidates by overlap before enriching (enrichment is slow)
    sorted_candidates = sorted(
        candidates.values(),
        key=lambda c: -c.topic_overlap,
    )[:args.max_candidates]

    print(f"\nStage 2: enriching top {len(sorted_candidates)} with "
          f"sub counts and sample titles...", file=sys.stderr)
    for i, c in enumerate(sorted_candidates, 1):
        enrich = stage2_enrich_channel(c.channel_id, args.sample_titles)
        if enrich:
            c.sub_count = enrich.get("sub_count")
            c.sample_titles = enrich.get("sample_titles", [])
            if enrich.get("channel_name"):
                c.channel_name = enrich["channel_name"]
        if i % 10 == 0:
            print(f"  enriched {i}/{len(sorted_candidates)}", file=sys.stderr)
        safe_sleep(0.3)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topics_searched": topics,
        "candidates": [asdict(c) for c in sorted_candidates],
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {args.output}", file=sys.stderr)
    print(f"\n>> NEXT: read this file, score each candidate's niche relevance (0-100), "
          f"write to /tmp/creator_scout_scores.json, then run stage3.",
          file=sys.stderr)
    return 0


# -----------------------------------------------------------------------------
# STAGE 3: Combine scores with structural signals, rank, write CSV
# -----------------------------------------------------------------------------

def final_score(niche_score: int, sub_count: Optional[int], topic_overlap: int,
                max_overlap: int) -> float:
    """Combine LLM niche score with structural signals.

    Weights:
    - niche relevance (LLM): 60%  — the whole point
    - topic overlap:        25%  — breadth of match
    - size (log scaled):    15%  — bigger = wider reach but not overwhelming
    """
    niche_component = (niche_score / 100) * 60

    overlap_component = (topic_overlap / max(max_overlap, 1)) * 25

    if sub_count:
        # log-ish scaling: 1k=~3, 10k=~6, 100k=~9, 1M=~12, 10M=~15
        import math
        size_component = min(15, max(0, (math.log10(sub_count) - 2) * 3))
    else:
        size_component = 5  # unknown = neutral

    return round(niche_component + overlap_component + size_component, 2)


def cmd_stage3(args) -> int:
    with open(args.raw, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    with open(args.scores, "r", encoding="utf-8") as f:
        scores_data = json.load(f)

    raw_candidates = raw_data["candidates"]
    score_map = {s["channel_id"]: s for s in scores_data.get("scores", [])}

    missing = [c["channel_id"] for c in raw_candidates if c["channel_id"] not in score_map]
    if missing:
        print(f"ERROR: {len(missing)} candidates have no score. "
              f"Stage 3a must score every candidate.", file=sys.stderr)
        print(f"First 5 missing IDs: {missing[:5]}", file=sys.stderr)
        return 2

    max_overlap = max((c["topic_overlap"] for c in raw_candidates), default=1)

    ranked = []
    for c in raw_candidates:
        s = score_map[c["channel_id"]]
        niche_score = int(s.get("niche_score", 0))
        ranked.append({
            "channel_id": c["channel_id"],
            "channel_name": c["channel_name"],
            "handle": c.get("handle"),
            "sub_count": c.get("sub_count"),
            "topic_overlap": c["topic_overlap"],
            "matching_topics": c["matching_topics"],
            "niche_score": niche_score,
            "niche_tag": s.get("niche_tag", ""),
            "note": s.get("note", ""),
            "sample_titles": c.get("sample_titles", [])[:3],
            "final_score": final_score(niche_score, c.get("sub_count"),
                                       c["topic_overlap"], max_overlap),
        })

    ranked.sort(key=lambda r: -r["final_score"])

    # JSON
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_candidates": len(ranked),
            "pitch_worthy_count": sum(1 for r in ranked if r["niche_score"] >= 70),
            "candidates": ranked,
        }, f, indent=2, ensure_ascii=False)

    # CSV
    with open(args.output_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "final_score", "niche_score", "niche_tag", "channel_name", "handle",
            "sub_count", "topic_overlap", "matching_topics", "note",
            "sample_title_1", "sample_title_2", "sample_title_3", "channel_id",
        ])
        for r in ranked:
            samples = r["sample_titles"] + ["", "", ""]
            w.writerow([
                r["final_score"], r["niche_score"], r["niche_tag"],
                r["channel_name"], r["handle"] or "",
                r["sub_count"] or "", r["topic_overlap"],
                ", ".join(r["matching_topics"]), r["note"],
                samples[0], samples[1], samples[2], r["channel_id"],
            ])

    print(f"Wrote {args.output_json}", file=sys.stderr)
    print(f"Wrote {args.output_csv}", file=sys.stderr)
    print(f"\nTotal: {len(ranked)} candidates", file=sys.stderr)
    print(f"Pitch-worthy (niche_score >= 70): "
          f"{sum(1 for r in ranked if r['niche_score'] >= 70)}", file=sys.stderr)
    print(f"\nTop 10 by final_score:", file=sys.stderr)
    for r in ranked[:10]:
        print(f"  [{r['final_score']:5.1f}] {r['channel_name']} "
              f"(subs: {r['sub_count'] or '?'}, niche: {r['niche_tag']}, "
              f"score: {r['niche_score']})", file=sys.stderr)

    return 0


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="creator-scout pipeline")
    sub = parser.add_subparsers(dest="stage", required=True)

    p1 = sub.add_parser("stage1", help="Pull recent video titles from seed channels")
    p1.add_argument("--per-seed", type=int, default=30)
    p1.add_argument("--output", required=True)

    p2 = sub.add_parser("stage2", help="Search YouTube for topics, collect candidates")
    p2.add_argument("--topics", required=True, help="Path to topics JSON from stage2a")
    p2.add_argument("--seeds-data", default="/tmp/creator_scout_seeds.json",
                    help="Path to stage1 output (to exclude seeds from candidates)")
    p2.add_argument("--per-search", type=int, default=20,
                    help="Max results per YouTube search")
    p2.add_argument("--max-candidates", type=int, default=80,
                    help="Cap candidates before enrichment")
    p2.add_argument("--sample-titles", type=int, default=8,
                    help="Recent titles per candidate for stage 3a scoring")
    p2.add_argument("--output", required=True)

    p3 = sub.add_parser("stage3", help="Combine scores, rank, write CSV")
    p3.add_argument("--raw", required=True, help="Stage 2 raw candidates JSON")
    p3.add_argument("--scores", required=True, help="Stage 3a scores JSON from LLM")
    p3.add_argument("--output-json", required=True)
    p3.add_argument("--output-csv", required=True)

    args = parser.parse_args()

    if args.stage == "stage1":
        return cmd_stage1(args)
    elif args.stage == "stage2":
        return cmd_stage2(args)
    elif args.stage == "stage3":
        return cmd_stage3(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
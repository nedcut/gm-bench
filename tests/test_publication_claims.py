from __future__ import annotations

import json
import re
from pathlib import Path

DISPLAY_NAMES = {
    "meta/muse-spark-1.1": "Muse Spark 1.1",
    "z-ai/glm-5.2": "GLM 5.2",
    "google/gemini-3.5-flash": "Gemini 3.5 Flash",
    "tencent/hy3:free": "Tencent HY3",
    "qwen/qwen3.7-plus": "Qwen 3.7 Plus",
    "openai/gpt-5.6-luna": "GPT-5.6 Luna",
    "anthropic/claude-sonnet-5": "Claude Sonnet 5",
    "minimax/minimax-m3": "MiniMax M3",
}


def test_blog_result_table_matches_generated_leaderboard() -> None:
    site = json.loads(Path("web/src/data/leaderboard.json").read_text())
    blog = Path("docs/blog/sota-v2-findings.md").read_text()
    rows = {}
    pattern = re.compile(
        r"^\| (?P<name>[^|]+?) \| (?P<mean>-?[0-9.]+) \| (?P<lift>-?[0-9.]+) "
        r"\| (?P<tokens>[0-9,.]+) \| \$(?P<cost>[0-9.]+) \| (?P<illegal>[0-9]+) \|$"
    )
    for line in blog.splitlines():
        match = pattern.match(line)
        if match:
            rows[match.group("name")] = match.groupdict()

    assert set(rows) == set(DISPLAY_NAMES.values())
    for model in site["models"]:
        row = rows[DISPLAY_NAMES[model["model"]]]
        assert row["mean"] == f"{model['mean_score']:.3f}"
        assert row["lift"] == f"{model['lift_vs_best_baseline']:.3f}"
        assert row["tokens"] == f"{model['tokens_per_decision']:,.1f}"
        assert row["cost"] == f"{model['cost_usd']:.4f}"
        assert row["illegal"] == str(model["illegal_actions"])


def test_public_claim_surfaces_use_the_frozen_lane_and_current_gate() -> None:
    blog = Path("docs/blog/sota-v2-findings.md").read_text()
    readme = Path("README.md").read_text()
    assert "4,096-token" in blog
    assert "1,024-token safety ceiling" not in blog
    assert "`publishable_ranking: true`" in readme
    assert "no ordinal \u201cbest model\u201d claim" in " ".join(readme.split())

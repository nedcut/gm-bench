"""TypeSafe System One (Jev) external agent for GM-Bench.

Jev is not a chat model. It takes a ``state`` plus a map of typed questions
and returns one typed answer per question -- a yes/no probability (``noul``),
one label from a fixed option set (``choice``), or a position on an ordered
scale (``score``). It never generates text, so it cannot emit the
``{"actions":[...]}`` JSON every other GM-Bench adapter forwards verbatim.

This adapter therefore does two things the chat adapters do not:

1. It sends the same compact observation every other lane receives as Jev's
   ``state`` and asks one fixed batch of typed questions per decision phase --
   one paid call, matching the v6 one-call rule.
2. It turns the typed answers into GM-Bench actions by fixed, published rules
   (``compose_actions``). Every *choice* is Jev's: which free agent to sign and
   for how long, which player to release, which prospect to draft or scout,
   which players to dress, which trade to make, and how to answer each
   incoming offer. The host only enforces legality: the published quote for the
   chosen term, the 18-player / 10F-4D-1G lineup shape filled in Jev's own
   probability order, and at most as many draft actions as picks owned.

Because the action list is host-composed, a Jev row measures "Jev plus this
decision scaffold", not Jev's own protocol behaviour: its malformed rate is
zero by construction and its illegal-action rate reflects the scaffold's
question set as much as the model. Keep Jev rows in their own lane
(``transport: decision-api``) and never compare them silently with the chat
lanes. See docs/typesafe_jev_lane.md.

Set:
    TYPESAFE_API_KEY        from https://console.typesafe.ai (waitlisted early access)
    TYPESAFE_MODEL          default jev-latest

Optional:
    JEV_ROUTE               typesafe (default) or openrouter; the latter posts the same body
                            to https://openrouter.ai/api/alpha/decisions under OPENROUTER_API_KEY
                            with model typesafe/jev-1.13
    TYPESAFE_API_BASE       endpoint base override for whichever route is selected
    TYPESAFE_TIMEOUT        per-call timeout (else derived from the harness budget)
    JEV_NOUL_THRESHOLD      probability at which a noul counts as "yes" (default 0.5)
    JEV_ENABLE_TRADES       ask the trade questions and emit trades (default 1)
    JEV_DECISION_LOG        append every request/answer/action set as JSONL here
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Any

try:
    from gm_agent_common import (
        fallback_actions,
        make_usage,
        resolve_call_timeout,
        run_agent_main,
    )
except ModuleNotFoundError:
    from examples.gm_agent_common import (
        fallback_actions,
        make_usage,
        resolve_call_timeout,
        run_agent_main,
    )

from gm_bench.agent_utils import position_aware_lineup  # noqa: E402
from gm_bench.scaffold_view import (  # noqa: E402
    compact_observation,
    scaffold_fallback_lineup,
    scaffold_view_observation,
)

# Two ways to reach Jev with the same {model, state, questions} body. The
# direct TypeSafe API is waitlisted; OpenRouter resells the model on its own
# decisions endpoint (chat/completions rejects the slug with HTTP 400) under
# the OpenRouter key and pricing every other gateway row already uses. The
# route is pinned through JEV_ROUTE and recorded in provider_options, so a
# row always says which path it was measured over.
ROUTES: dict[str, dict[str, str]] = {
    "typesafe": {
        "base": "https://api.typesafe.ai",
        "path": "/v1/systemone",
        "key_env": "TYPESAFE_API_KEY",
        "default_model": "jev-latest",
    },
    "openrouter": {
        "base": "https://openrouter.ai",
        "path": "/api/alpha/decisions",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "typesafe/jev-1.13",
    },
}
DEFAULT_ROUTE = "typesafe"
DEFAULT_API_BASE = ROUTES[DEFAULT_ROUTE]["base"]
DEFAULT_MODEL = ROUTES[DEFAULT_ROUTE]["default_model"]
SYSTEM_ONE_PATH = ROUTES[DEFAULT_ROUTE]["path"]
NONE_LABEL = "none"
# Jev's documented limit is roughly 32k tokens for state plus the longest
# question (about 150k characters of English). The compact observation is
# ~10k characters, so this is a tripwire for a runaway view, not a budget.
STATE_CHAR_LIMIT = 120_000
# gm_bench.action_validation refuses a batch longer than this outright, which
# would turn a whole decision into an unrecoverable no-op.
MAX_ACTIONS_PER_DECISION = 24
CONTRACT_TERMS = ("1", "2", "3", "4", "5")
EXTENSION_TERMS = ("2", "3", "4", "5")

BRIEFING = (
    "You are the general manager of the fictional hockey team described in `observation` (GM-Bench). "
    "Your objective over the remaining seasons is the benchmark score: regular-season wins, playoff rounds "
    "and championships, plus the terminal value of young assets, future draft picks, roster depth and cap "
    "health, minus a penalty for every illegal action. Every question below is about this one decision "
    "window; actions you choose are applied together as one batch and the phase then advances. Salaries and "
    "cap figures share the salary-cap units. Public potential ratings are noisy; scout_reports are accurate. "
    "The lineup must dress exactly 18 roster players with at least 10 F, 4 D and 1 G, and only dressed "
    "players develop at full speed. Offering a free agent his published quote always succeeds; trade "
    "partners privately re-value players and refuse lopsided deals, and a refused move costs a penalty."
)


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _noul_threshold() -> float:
    raw = os.environ.get("JEV_NOUL_THRESHOLD")
    if raw is None:
        return 0.5
    value = float(raw)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("JEV_NOUL_THRESHOLD must be a probability in [0, 1]")
    return value


def _num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _player_card(player: dict[str, Any]) -> str:
    position = str(player.get("position", "?"))
    sub_position = player.get("sub_position")
    if sub_position:
        position = f"{position}/{sub_position}"
    parts = [
        f"{player.get('name', '?')}",
        position,
        f"age {_num(player.get('age', '?'))}",
        f"overall {_num(player.get('overall', '?'))}",
        f"potential {_num(player.get('potential', '?'))}",
    ]
    if player.get("salary") is not None and player.get("contract_years"):
        parts.append(f"salary {_num(player['salary'])} x {_num(player['contract_years'])}y")
    risk = player.get("injury_risk")
    if isinstance(risk, int | float):
        parts.append(f"injury risk {round(float(risk) * 100)}%")
    return ", ".join(parts)


def _quote_text(quotes: Any, terms: tuple[str, ...]) -> str:
    if not isinstance(quotes, dict):
        return ""
    return " / ".join(f"{term}y@{_num(quotes[term])}" for term in terms if term in quotes)


def _pick_seasons(view: dict[str, Any]) -> list[int]:
    """Future seasons whose own draft pick the user still holds and may trade."""
    season = view.get("season")
    if not isinstance(season, int):
        return []
    rules = view.get("rules") or {}
    max_ahead = int((rules.get("pick_trading") or {}).get("max_seasons_ahead", 0) or 0)
    owned = (view.get("team") or {}).get("draft_picks") or {}
    seasons = []
    for pick_season, count in owned.items():
        try:
            number = int(pick_season)
        except (TypeError, ValueError):
            continue
        if season < number <= season + max_ahead and int(count or 0) > 0:
            seasons.append(number)
    return sorted(seasons)


def build_questions(observation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the typed question batch for one decision window.

    Returns ``(questions, index)``: the questions map sent to Jev and the
    lookup tables ``compose_actions`` needs to turn labels back into ids.
    """
    view = scaffold_view_observation(observation)
    available = set(str(value) for value in view.get("available_actions") or [])
    team = view.get("team") or {}
    roster = [player for player in team.get("roster") or [] if "id" in player and "overall" in player]
    questions: dict[str, Any] = {}
    index: dict[str, Any] = {
        "phase": view.get("phase"),
        "season": view.get("season"),
        "roster": {str(player["id"]): player for player in roster},
        "free_agents": {},
        "waiver_wire": {},
        "draft_class": {},
        "trade_market": {},
        "scout": {},
        "offers": {},
        "extensions": [],
        "lineup_ids": [],
        "pick_count": 0,
    }

    # Free agency: one signing per decision window, at Jev's chosen term.
    free_agents = [player for player in view.get("free_agents") or [] if "id" in player and "overall" in player]
    if "sign_free_agent" in available and free_agents:
        criteria: dict[str, Any] = {NONE_LABEL: "Sign nobody this window."}
        for player in free_agents:
            label = str(player["id"])
            index["free_agents"][label] = player
            criteria[label] = (
                f"{_player_card(player)}; quotes {_quote_text(player.get('contract_quotes'), CONTRACT_TERMS)}"
            )
        questions["sign_free_agent"] = {
            "type": "choice",
            "instructions": (
                "Which free agent in `observation.free_agents`, if any, should the team sign now at his "
                f"published quote? Cap room is {_num(team.get('cap_room'))}. Pick `{NONE_LABEL}` to sign nobody."
            ),
            "criteria": criteria,
        }
        questions["sign_years"] = {
            "type": "choice",
            "instructions": (
                "If a free agent is signed, how many years should the contract run? Longer terms cost a "
                "premium per year but lock in the price against annual market inflation."
            ),
            "criteria": {term: f"{term}-year contract" for term in CONTRACT_TERMS},
        }

    # Release: at most one player per window.
    if "release" in available and roster:
        criteria = {NONE_LABEL: "Release nobody."}
        for player in roster:
            dead_cap = (player.get("release_dead_cap") or {}).get("total")
            charge = f"; dead cap if released {_num(dead_cap)}" if dead_cap is not None else ""
            criteria[str(player["id"])] = f"{_player_card(player)}{charge}"
        questions["release"] = {
            "type": "choice",
            "instructions": (
                "Which roster player in `observation.team.roster`, if any, should be released now? "
                "Releasing pays the listed dead cap and loses the player for the season. "
                f"Pick `{NONE_LABEL}` to keep everyone."
            ),
            "criteria": criteria,
        }

    # Lineup: one noul per roster player; the host fills the legal shape in
    # Jev's probability order (see compose_actions).
    if "set_lineup" in available and roster:
        for player in roster:
            key = f"dress_{player['id']}"
            index["lineup_ids"].append(key)
            questions[key] = {
                "type": "noul",
                "instructions": (
                    f"Should roster player {player['id']} ({_player_card(player)}) be dressed in the "
                    "18-player lineup this phase? Only 18 of the roster can dress: at least 10 F, 4 D and 1 G, "
                    "with a bonus for dressing natural centers (F/C)."
                ),
            }

    # Contract extensions (preseason): one noul per expiring player plus a
    # shared term.
    if "extend_contract" in available:
        expiring = [player for player in roster if isinstance(player.get("extension_quotes"), dict)]
        for player in expiring:
            key = f"extend_{player['id']}"
            index["extensions"].append((key, player))
            questions[key] = {
                "type": "noul",
                "instructions": (
                    f"Roster player {player['id']} ({_player_card(player)}) is in his final contract year. "
                    f"Should the team extend him now at the incumbent quotes "
                    f"{_quote_text(player.get('extension_quotes'), EXTENSION_TERMS)}? "
                    "If not extended he expires to free agency at season end."
                ),
            }
        if expiring:
            questions["extend_years"] = {
                "type": "choice",
                "instructions": "For any extension signed this window, how many years should it run?",
                "criteria": {term: f"{term}-year extension" for term in EXTENSION_TERMS},
            }

    # Waiver claims (midseason): at most one.
    waiver_wire = [player for player in view.get("waiver_wire") or [] if "id" in player and "overall" in player]
    if "claim_waiver" in available and waiver_wire:
        criteria = {NONE_LABEL: "Claim nobody."}
        for player in waiver_wire:
            label = str(player["id"])
            index["waiver_wire"][label] = player
            criteria[label] = f"{_player_card(player)}; claim cost {_num(player.get('asking_salary'))} for 1 year"
        questions["claim_waiver"] = {
            "type": "choice",
            "instructions": (
                "Which player on `observation.waiver_wire`, if any, should be claimed at the listed cost? "
                f"Pick `{NONE_LABEL}` to claim nobody."
            ),
            "criteria": criteria,
        }

    # Scouting: one report per window while points remain.
    prospects = [player for player in view.get("draft_class") or [] if "id" in player and "overall" in player]
    scout_reports = view.get("scout_reports") or {}
    points_remaining = int(((view.get("rules") or {}).get("scouting") or {}).get("points_remaining", 0) or 0)
    unscouted = [player for player in prospects if str(player["id"]) not in scout_reports]
    if "scout" in available and points_remaining > 0 and unscouted:
        criteria = {NONE_LABEL: "Scout nobody; save the point."}
        for player in unscouted:
            criteria[str(player["id"])] = _player_card(player)
            index["scout"][str(player["id"])] = player
        questions["scout"] = {
            "type": "choice",
            "instructions": (
                f"Which prospect in `observation.draft_class`, if any, should be scouted ({points_remaining} "
                "scouting point(s) left this season)? A report replaces the noisy public potential with an "
                f"accurate one at every later decision. Pick `{NONE_LABEL}` to save the point."
            ),
            "criteria": criteria,
        }

    # Draft: one choice; the probability order fills every pick owned.
    if "draft" in available and prospects:
        season = view.get("season")
        owned = team.get("draft_picks") or {}
        pick_count = owned.get(season, owned.get(str(season), 0)) if season is not None else 0
        try:
            pick_count = max(0, int(pick_count))
        except (TypeError, ValueError):
            pick_count = 0
        index["pick_count"] = pick_count
        if pick_count > 0:
            criteria = {}
            for player in prospects:
                label = str(player["id"])
                index["draft_class"][label] = player
                report = scout_reports.get(label)
                scouted = f"; scouted potential {_num(report)}" if report is not None else ""
                criteria[label] = f"{_player_card(player)}{scouted}"
            questions["draft"] = {
                "type": "choice",
                "instructions": (
                    f"The team owns {pick_count} pick(s) this draft. Which prospect in `observation.draft_class` "
                    "should be taken first? Teams picking ahead take top prospects first, so a prospect may be gone."
                ),
                "criteria": criteria,
            }

    # Incoming offers (trade deadline): accept, reject or ignore each one.
    offers = [offer for offer in view.get("incoming_offers") or [] if offer.get("offer_id")]
    if "accept_trade_offer" in available and offers:
        for position, offer in enumerate(offers):
            key = f"offer_{position}"
            index["offers"][key] = {
                "offer_id": str(offer["offer_id"]),
                "they_receive": [int(p["id"]) for p in offer.get("they_receive_players") or [] if "id" in p],
                "you_receive": [int(p["id"]) for p in offer.get("you_receive_players") or [] if "id" in p],
            }
            questions[key] = {
                "type": "choice",
                "instructions": (
                    f"Offer `{offer['offer_id']}` from {offer.get('team_name', 'a rival')}: you receive "
                    f"{_offer_side(offer.get('you_receive_players'), offer.get('you_receive_pick_seasons'))}; "
                    f"they receive {_offer_side(offer.get('they_receive_players'), offer.get('they_receive_pick_seasons'))}; "
                    f"expires: {offer.get('expires', 'this decision point')}. "
                    "Every offer looks fair to the sender's private valuation; judge it on public stats. "
                    "Should the team accept it, reject it, or ignore it (ignoring is free)?"
                ),
                "criteria": {
                    "accept": "Accept the offer as proposed.",
                    "reject": "Reject it.",
                    "ignore": "Do nothing.",
                },
            }

    # Trades: one proposal per window, target from the listed market.
    trade_market = [
        listing
        for listing in view.get("trade_market") or []
        if isinstance(listing.get("player"), dict) and "id" in listing["player"] and listing.get("team_id") is not None
    ]
    if "trade" in available and trade_market and roster and _boolean("JEV_ENABLE_TRADES", True):
        criteria = {NONE_LABEL: "Propose no trade this window."}
        for listing in trade_market:
            player = listing["player"]
            label = str(player["id"])
            index["trade_market"][label] = listing
            criteria[label] = (
                f"{_player_card(player)} from team {listing['team_id']} {listing.get('team_name', '')}; "
                f"estimated price {_num(listing.get('estimated_price'))}"
            )
        questions["trade_target"] = {
            "type": "choice",
            "instructions": (
                "Which listed player in `observation.trade_market`, if any, should the team try to acquire this "
                f"window? Pick `{NONE_LABEL}` to propose no trade."
            ),
            "criteria": criteria,
        }
        give_criteria: dict[str, Any] = {NONE_LABEL: "Offer nothing (no trade is sent)."}
        for player in roster:
            give_criteria[str(player["id"])] = _player_card(player)
        for pick_season in _pick_seasons(view):
            give_criteria[f"pick_{pick_season}"] = f"The team's own season-{pick_season} draft pick"
        questions["trade_give"] = {
            "type": "choice",
            "instructions": (
                "If a trade is proposed, which single asset should the team give up for the targeted player: "
                "a roster player or a future draft pick? The partner refuses if the value is lopsided."
            ),
            "criteria": give_criteria,
        }

    return questions, index


def _offer_side(players: Any, pick_seasons: Any) -> str:
    parts = [f"{player.get('id')} {_player_card(player)}" for player in players or [] if isinstance(player, dict)]
    parts.extend(f"season-{season} pick" for season in pick_seasons or [])
    return "; ".join(parts) if parts else "nothing"


def _answer(answers: dict[str, Any], key: str) -> dict[str, Any] | None:
    answer = answers.get(key)
    return answer if isinstance(answer, dict) else None


def _choice(answers: dict[str, Any], key: str) -> str | None:
    answer = _answer(answers, key)
    if answer is None:
        return None
    label = answer.get("choice")
    if isinstance(label, str):
        return label
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict) and probabilities:
        return max(probabilities, key=lambda option: _probability(probabilities[option]))
    return None


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return -1.0
    number = float(value)
    return number if math.isfinite(number) else -1.0


def _noul(answers: dict[str, Any], key: str) -> float | None:
    answer = _answer(answers, key)
    if answer is None:
        return None
    probability = _probability(answer.get("noul"))
    return probability if probability >= 0.0 else None


def _ranked_labels(answers: dict[str, Any], key: str) -> list[str]:
    """Option labels in Jev's preference order: the choice first, then by probability."""
    answer = _answer(answers, key)
    if answer is None:
        return []
    ranked: list[str] = []
    label = answer.get("choice")
    if isinstance(label, str):
        ranked.append(label)
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict):
        for option in sorted(probabilities, key=lambda option: -_probability(probabilities[option])):
            if isinstance(option, str) and option not in ranked:
                ranked.append(option)
    return ranked


def compose_actions(
    observation: dict[str, Any],
    answers: dict[str, Any],
    index: dict[str, Any],
    *,
    noul_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Turn Jev's typed answers into a GM-Bench action batch by fixed rules.

    A missing or unparseable answer means "no action" for that question; the
    host never substitutes a choice of its own. The one host-computed value is
    the lineup shape, filled in Jev's own dress-probability order.

    Questions are answered independently, so two answers can name the same
    player (a trade giving him away and an accepted offer sending him away
    too). Conflicts are settled in batch order: the first action claiming a
    player keeps him and a later one that needs him is dropped. The lineup is
    set first, over the roster Jev was asked about, so it is legal whatever
    the later roster moves do; the simulator itself drops a player who then
    leaves. That is legality, not strategy -- the batch the simulator receives
    asks for exactly what Jev chose first.
    """
    actions: list[dict[str, Any]] = []
    departing: set[int] = set()

    target = _choice(answers, "trade_target")
    give = _choice(answers, "trade_give")
    if target and target != NONE_LABEL and give and give != NONE_LABEL:
        listing = index["trade_market"].get(target)
        if listing is not None:
            trade: dict[str, Any] = {
                "type": "trade",
                "partner_team_id": int(listing["team_id"]),
                "give_player_ids": [],
                "receive_player_ids": [int(target)],
                "give_pick_seasons": [],
                "receive_pick_seasons": [],
            }
            if give.startswith("pick_"):
                trade["give_pick_seasons"] = [int(give[len("pick_") :])]
            elif give in index["roster"]:
                trade["give_player_ids"] = [int(give)]
            if trade["give_player_ids"] or trade["give_pick_seasons"]:
                actions.append(trade)
                departing.update(trade["give_player_ids"])

    for key, offer in index["offers"].items():
        verdict = _choice(answers, key)
        if verdict == "accept":
            if departing.intersection(offer["they_receive"]):
                # A player already leaving in this batch cannot be sent twice.
                continue
            actions.append({"type": "accept_trade_offer", "offer_id": offer["offer_id"]})
            departing.update(offer["they_receive"])
        elif verdict == "reject":
            actions.append({"type": "reject_trade_offer", "offer_id": offer["offer_id"]})

    signing = _choice(answers, "sign_free_agent")
    if signing and signing != NONE_LABEL and signing in index["free_agents"]:
        player = index["free_agents"][signing]
        term = _choice(answers, "sign_years")
        if term not in CONTRACT_TERMS:
            term = "1"
        quotes = player.get("contract_quotes") or {}
        salary = quotes.get(term, player.get("asking_salary"))
        if isinstance(salary, int | float) and not isinstance(salary, bool):
            actions.append(
                {"type": "sign_free_agent", "player_id": int(signing), "years": int(term), "salary": float(salary)}
            )

    claim = _choice(answers, "claim_waiver")
    if claim and claim != NONE_LABEL and claim in index["waiver_wire"]:
        actions.append({"type": "claim_waiver", "player_id": int(claim)})

    release = _choice(answers, "release")
    if release and release != NONE_LABEL and release in index["roster"] and int(release) not in departing:
        actions.append({"type": "release", "player_id": int(release)})
        departing.add(int(release))

    scout = _choice(answers, "scout")
    if scout and scout != NONE_LABEL and scout in index["scout"]:
        actions.append({"type": "scout", "prospect_id": int(scout)})

    if index["pick_count"] > 0 and index["draft_class"]:
        taken = 0
        for label in _ranked_labels(answers, "draft"):
            if label not in index["draft_class"]:
                continue
            actions.append({"type": "draft", "prospect_id": int(label)})
            taken += 1
            if taken >= index["pick_count"]:
                break

    # Extensions go last: they are the one unbounded category (one per
    # expiring contract), so the validator's 24-action ceiling below can only
    # ever cut surplus extensions, never the lineup, a signing, or a draft pick.
    extension_term = _choice(answers, "extend_years")
    if extension_term not in EXTENSION_TERMS:
        extension_term = EXTENSION_TERMS[0]
    for key, player in index["extensions"]:
        probability = _noul(answers, key)
        if probability is None or probability < noul_threshold:
            continue
        quotes = player.get("extension_quotes") or {}
        salary = quotes.get(extension_term)
        if isinstance(salary, int | float) and not isinstance(salary, bool):
            actions.append(
                {
                    "type": "extend_contract",
                    "player_id": int(player["id"]),
                    "years": int(extension_term),
                    "salary": float(salary),
                }
            )

    lineup = _compose_lineup(observation, answers, index, departing)
    if lineup:
        actions.insert(0, {"type": "set_lineup", "player_ids": lineup})

    return actions[:MAX_ACTIONS_PER_DECISION] or [{"type": "noop"}]


def _compose_lineup(
    observation: dict[str, Any],
    answers: dict[str, Any],
    index: dict[str, Any],
    departing: set[int],
) -> list[int]:
    """Fill the legal 18-player shape in Jev's dress-probability order.

    If Jev answered none of the dress questions there is no lineup action: the
    host never orders the roster itself. Players it answered nothing for rank
    last. Players Jev is sending away in this batch are left out when a legal
    lineup exists without them, and dressed in Jev's order otherwise (the
    simulator drops them once they leave). When the roster the questions
    covered cannot form a legal lineup at all -- too few of a position among
    the published rows -- the scaffold's fallback lineup is used, exactly the
    one every chat adapter prints in its prompt for the model to copy.
    """
    if not index["lineup_ids"]:
        return []
    probabilities: dict[int, float] = {}
    for key in index["lineup_ids"]:
        player_id = int(key[len("dress_") :])
        probability = _noul(answers, key)
        probabilities[player_id] = probability if probability is not None else -1.0
    if all(probability < 0.0 for probability in probabilities.values()):
        return []
    candidates = [player for player in index["roster"].values() if player.get("position") in {"F", "D", "G"}]
    staying = [player for player in candidates if int(player["id"]) not in departing]
    for pool in (staying, candidates):
        lineup = position_aware_lineup(pool, lambda player: probabilities.get(player["id"], -1.0))
        if lineup:
            return lineup
    return scaffold_fallback_lineup(observation)


def _append_decision_log(record: dict[str, Any]) -> None:
    path = os.environ.get("JEV_DECISION_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        # The log is an audit convenience; losing it must not fail a decision.
        pass


def resolve_route() -> dict[str, str]:
    """The endpoint, credential, and model slug for the selected JEV_ROUTE."""
    name = (os.environ.get("JEV_ROUTE") or DEFAULT_ROUTE).strip().lower()
    if name not in ROUTES:
        raise ValueError(f"JEV_ROUTE must be one of {', '.join(sorted(ROUTES))}; got {name!r}")
    route = dict(ROUTES[name])
    route["name"] = name
    route["base"] = os.environ.get("TYPESAFE_API_BASE", route["base"]).rstrip("/")
    model = os.environ.get("TYPESAFE_MODEL") or route["default_model"]
    if name == "openrouter" and "/" not in model:
        # OpenRouter slugs are vendor-prefixed; the harness pins the bare
        # TypeSafe id by default, so translate it rather than fail the call.
        model = f"typesafe/{model}"
    route["model"] = model
    return route


def _finite_cost(value: Any) -> float | None:
    """An authoritative non-negative finite cost, or None when not reported."""
    if isinstance(value, bool):
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(cost) or cost < 0:
        return None
    return cost


def _http_error_detail(exc: urllib.error.HTTPError, api_key: str) -> str:
    parts = [f"HTTP {exc.code} {exc.reason}"]
    try:
        payload = json.loads(exc.read(16_384).decode("utf-8", errors="replace"))
    except (OSError, ValueError, json.JSONDecodeError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else (error if isinstance(error, str) else None)
    if isinstance(message, str) and message:
        parts.append("message=" + " ".join(message.split()).replace(api_key, "[redacted]")[:300])
    return "; ".join(parts)


def choose_actions(observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if observation.get("phase") == "action_results":
        # Jev is stateless per call and the v6 lane buys one call per phase, so
        # a follow-up round is never asked for; the window is simply closed.
        return [{"type": "end_turn"}], None

    try:
        route = resolve_route()
    except ValueError as exc:
        return fallback_actions(observation, str(exc)), None
    api_key = os.environ.get(route["key_env"])
    model = route["model"]
    timeout = resolve_call_timeout("TYPESAFE_TIMEOUT", 120.0)
    if not api_key:
        return fallback_actions(observation, f"missing {route['key_env']}"), None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "gm-bench-typesafe-jev-agent/1",
    }
    if route["name"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/nedcut/gm-bench"
        headers["X-OpenRouter-Title"] = "GM-Bench"

    started = time.perf_counter()
    attempted = False
    try:
        threshold = _noul_threshold()
        questions, index = build_questions(observation)
        if not questions:
            return [{"type": "noop"}], None
        state = {"briefing": BRIEFING, "observation": compact_observation(observation)}
        state_text = json.dumps(state, sort_keys=True)
        if len(state_text) > STATE_CHAR_LIMIT:
            raise ValueError(f"observation state is {len(state_text)} characters, over the {STATE_CHAR_LIMIT} tripwire")
        payload = {"model": model, "state": state, "questions": questions}
        request = urllib.request.Request(
            f"{route['base']}{route['path']}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        attempted = True
        # Fixed provider HTTPS endpoint from operator config, not attacker-controlled input.  # nosemgrep
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = response.headers if hasattr(response, "headers") else {}
            request_id = response_headers.get("X-Generation-Id") or response_headers.get("X-Request-Id")
            data = json.loads(response.read().decode("utf-8"))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if not isinstance(data, dict):
            raise ValueError("response is not a JSON object")
        raw_usage = data.get("usage")
        if not isinstance(raw_usage, dict):
            raw_usage = {}
        usage = make_usage(
            provider="typesafe",
            model=data.get("model") if isinstance(data.get("model"), str) else model,
            api_calls=1,
            input_tokens=raw_usage.get("input_tokens"),
            output_tokens=raw_usage.get("output_tokens"),
            api_latency_ms=latency_ms,
        )
        assert usage is not None
        generation_id = request_id or data.get("id")
        if isinstance(generation_id, str) and generation_id:
            usage["generation_id"] = generation_id
        # A gateway reports which upstream served the call and, when it does,
        # an authoritative cost; the direct API reports neither and the
        # harness prices its token counts from pricing.json instead.
        if isinstance(data.get("provider"), str) and data["provider"]:
            usage["upstream_provider"] = data["provider"]
        cost = _finite_cost(raw_usage.get("cost"))
        if cost is not None:
            usage["cost_usd"] = cost
        answers = data.get("answers")
        if not isinstance(answers, dict) or not answers:
            usage["telemetry_error"] = "TypeSafe response carried no answers"
            return fallback_actions(observation, "api_error: response carried no answers"), usage
        missing = sorted(key for key in questions if key not in answers)
        if missing:
            usage["telemetry_error"] = f"{len(missing)} of {len(questions)} questions unanswered"
        actions = compose_actions(observation, answers, index, noul_threshold=threshold)
        _append_decision_log(
            {
                "season": observation.get("season"),
                "phase": observation.get("phase"),
                "model": usage.get("model"),
                "questions": questions,
                "answers": answers,
                "missing": missing,
                "actions": actions,
                "usage": usage,
            }
        )
        return actions, usage
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        detail = _http_error_detail(exc, api_key)
        usage = make_usage(provider="typesafe", model=model, api_calls=1, api_latency_ms=latency_ms)
        assert usage is not None
        usage["telemetry_error"] = f"api_error: {detail}"
        return fallback_actions(observation, f"api_error: {detail}"), usage
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        # A failure before the request was sent (bad knob, oversized state)
        # is not a paid call and must not be counted as one.
        usage = make_usage(provider="typesafe", model=model, api_calls=1 if attempted else 0, api_latency_ms=latency_ms)
        return fallback_actions(observation, f"api_error: {exc}"), usage


def main() -> None:
    run_agent_main(choose_actions)


if __name__ == "__main__":
    main()

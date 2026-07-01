# GM-Bench JSON Schemas

Formal contracts for the GM-Bench agent protocol.

| Schema | Purpose |
| --- | --- |
| `gm_observation.schema.json` | Observation object written to external-agent stdin |
| `gm_action_list.schema.json` | Action array expected on external-agent stdout |
| `gm_actions.schema.json` | Structured `{"actions": [...]}` wrapper for Codex/Claude adapters |

External agents should read observations matching `gm_observation.schema.json` and
respond with a JSON array matching `gm_action_list.schema.json`.

Model-backed coding-agent adapters may use `gm_actions.schema.json` instead and
let the adapter unwrap the `actions` field.

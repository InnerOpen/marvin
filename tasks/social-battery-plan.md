# The Social Battery: finishing the mood meter

Jared, 2026-10-25: "finish the implementation". The settings shipped 2026-10-16 (`MoodSettings` on packs, the workspace
and agents; read by nothing). This builds the meter they describe (Brain: "Marvin Agent Social Battery").

## Guardrails (from the Brain, non-negotiable)

1. Only rudeness aimed at the assistant drains; frustration with the *problem* never does.
2. Help quality never changes: no refusals, no slower answers, no guilt-tripping. Flavour only.
3. Visible and resettable ("Reset our relationship"), described plainly as a game.
4. Off by default; a workspace switches it on.

## Shape

- [x] **Switch**: `mood_enabled` on the workspace's AI settings (off; Persona page → "Social Battery"). Agents' and the
      workspace's `MoodSettings` apply only while it's on. Defaults for unset choices: drains `treatment`, meter
      `visible`, memory `weeks`, absence `neutral`.
- [x] **Record**: `ai_mood_meters` — one per (workspace, person, agent): `level` 0–100 (starts 50), `last_seen_at`,
      `signals` (the last 12: kind, delta, when), `band_since` (for a milestone), `reset_at`. Migration.
- [x] **Scoring** (`services/ai/mood.py`, rules, no model call), on each message a person sends an agent from a chat
      surface (bubble, Ask page, the agent route as a person — never MCP, API tokens' automations, workflows, hand-off
      children):
  - charges: thanks (+6), a compliment or "that worked" (+6; both +10);
  - drains (treatment): an insult aimed at the assistant (−12), the same message again within the recent signals (−4),
    rapid-fire (the 5th+ message within 2 minutes: −3), a very long session (the 25th+ message within 90 minutes: −2);
  - drains (use): every message −2, on top of the treatment drains;
  - drift toward 50: `daily` → back to 50 on the first message of a new day; `weeks` → 10% of the distance per day;
  - absence (3+ days): `recharges` +15, `cools` −10, `neutral` nothing — once, on the first message back;
  - clamp 0–100; bands: low ≤ 30, high ≥ 70, else neutral.
- [x] **Prompt line** between Character and Tone (`tones.tone_parts(..., mood_line)`), only when the tone keeps the
      character: "Mood: drained — … a weary aside is fair." / "Mood: warm — …", each ending with the flavour-only rule.
      A first message in a new band adds "one short aside acknowledging it is fine" (the rare milestone line).
- [x] **API**: the run's reply carries `mood: {level, band, visible}`; `GET /api/ai/mood?agent=` and
      `POST /api/ai/mood/reset` (`{agent}`); `GET /api/groups/ai-settings` carries `mood_enabled` and each agent voice's
      `mood` (its band lines and meter choice).
- [x] **Bubble**: greeting and taglines from the band's lines when it has them; a small battery in the header (hidden
      when the character's `meter` is hidden) with the game explained in its tooltip; `/mood` says the level and `/mood
      reset` resets ("Reset our relationship"); a low band rests in the `waiting` state when the pack has one.
- [x] **Settings UI**: the Persona page's switch; the mood fields lose "not active yet".
- [x] Tests (scoring, drift, absence, bands, guardrail 1, prompt placement, the route per person/agent/source, reset,
      the bubble helpers); docs (agents-and-ask.md); Brain project note → active.

## Review

Built 2026-10-25, all of the shape above. Two things settled while building: the agent's own MoodSettings replace the
workspace's whole (not field by field) — that is how a pack's sheet is meant to travel; and the milestone aside is one
sentence on the first message in a new band (sustained-high cutscenes would need a timeline nobody keeps). The bubble's
`waiting` state stands in for "slumped" since packs have no mood states of their own. Only person surfaces score.
Tests: `tests/test_social_battery.py` (29), `frontend/src/lib/marvin/mood.test.mjs` (5); the tone golden tests unchanged.


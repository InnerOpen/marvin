// A workflow's agent step (`kind: "agent"`): which agents the editor offers, the step read back from its form, and how a
// finished run's output reads on the run detail. Pure, so `npm test` covers it (agentStep.test.mjs).

export const AGENT_DEFAULT_STEPS = 8;
export const AGENT_MAX_STEPS = 15;
export const AGENT_MAX_PLAYBOOKS = 3;

/** An agent the builder's options offer (`agents` of GET /api/automations/options). */
export interface AgentOption {
  slug: string;
  name: string;
  description?: string | null;
  enabled?: boolean;
  /** Whether its permissions let it save drafts on its own for the author (Entries: author set to Allow). */
  canDraft?: boolean;
}

/** A published Playbook the step may add. */
export interface PlaybookOption {
  name: string;
  description?: string | null;
  manualOnly?: boolean;
}

/** The agents to pick from: switched on, or the one this step already names (so an existing step still shows). */
export function offeredAgents(agents: AgentOption[] | null | undefined, current?: string | null): AgentOption[] {
  return (agents ?? []).filter((a) => a.enabled !== false || a.slug === current);
}

/** One line under the picker: what the agent is for and what it may do here. */
export function agentSummary(agent: AgentOption | undefined): string {
  if (!agent) return "";
  const what = (agent.description ?? "").trim();
  const may = agent.canDraft
    ? "May save drafts on its own."
    : "May not save drafts here: set Entries: author to Allow for it (Settings → AI → Agents).";
  return what ? `${what} ${may}` : may;
}

/** Playbooks the step may name: published ones that load by themselves (a manual-only one loads only when named). */
export function offeredPlaybooks(playbooks: PlaybookOption[] | null | undefined): PlaybookOption[] {
  return (playbooks ?? []).filter((p) => !p.manualOnly);
}

export interface AgentForm {
  agent: string;
  message: string;
  playbooks: string[];
  maxSteps: string | number;
  onEntry: boolean;
  /** Check its work before it finishes; absent (a form without the box) leaves the step as it was. */
  checkWork?: boolean;
}

/** The step the form describes laid over the one it was opened with (null: not filled in enough to be one).
 * Defaults stay out of the saved step: 8 steps and "about the trigger's entry" are what an absent key means. */
export function readAgentStep(form: AgentForm, original: Record<string, any> = {}): Record<string, any> | null {
  const agent = form.agent.trim();
  const message = form.message.trim();
  if (!agent || !message) return null;
  const step: Record<string, any> = { ...original, kind: "agent", agent, message };
  const playbooks = [...new Set(form.playbooks.map((p) => p.trim()).filter(Boolean))].slice(0, AGENT_MAX_PLAYBOOKS);
  if (playbooks.length) step.playbooks = playbooks;
  else delete step.playbooks;
  const asked = Number(form.maxSteps);
  const steps = Number.isFinite(asked) && asked >= 1 ? Math.min(Math.round(asked), AGENT_MAX_STEPS) : AGENT_DEFAULT_STEPS;
  if (steps === AGENT_DEFAULT_STEPS) delete step.max_steps;
  else step.max_steps = steps;
  if (form.onEntry) delete step.on_entry;
  else step.on_entry = false;
  if (form.checkWork === true) step.check_work = true;
  else if (form.checkWork === false) delete step.check_work;
  return step;
}

/** What a run recorded for an agent step, as the run detail shows it. */
export interface AgentRunView {
  answer: string;
  entries: { id: string; title: string; status: string; href: string; reviewLink: string }[];
  playbooks: string[];
  stopped: { code: string; text: string };
  tokens: number | null;
  costUsd: number | null;
  executionId: string | null;
  skipped: string | null;
}

const STOPPED: Record<string, string> = {
  complete: "Finished",
  max_steps: "Ran out of steps: it answered with what it had",
  refused: "Stopped: a call needed an approval nobody could give",
};

/** The output of an agent step (`answer`, `entries`, `playbooks`, `stopped`, `execution_id`, `tokens`, `cost_usd`) in
 * the words and links the run detail uses; null for an output that isn't one. */
export function agentRunView(output: any): AgentRunView | null {
  if (!output || typeof output !== "object" || typeof output.stopped !== "string") return null;
  const entries = (Array.isArray(output.entries) ? output.entries : [])
    .filter((e: any) => e && typeof e === "object" && e.id)
    .map((e: any) => ({
      id: String(e.id),
      title: String(e.title || "Untitled"),
      status: String(e.status ?? ""),
      href: String(e.url || `/workspace/entries/${e.id}`),
      reviewLink: String(e.reviewLink ?? ""),
    }));
  return {
    answer: String(output.answer ?? ""),
    entries,
    playbooks: (Array.isArray(output.playbooks) ? output.playbooks : []).map(String),
    stopped: { code: output.stopped, text: STOPPED[output.stopped] ?? output.stopped },
    tokens: typeof output.tokens === "number" ? output.tokens : null,
    costUsd: typeof output.cost_usd === "number" ? output.cost_usd : null,
    executionId: output.execution_id ? String(output.execution_id) : null,
    skipped: output.skipped ? String(output.skipped) : null,
  };
}

/** "1,234 tokens · $0.0123" (either part left out when the run didn't record it). */
export function costText(tokens: number | null, costUsd: number | null): string {
  const parts: string[] = [];
  if (tokens != null) parts.push(`${tokens.toLocaleString("en-US")} tokens`);
  if (costUsd != null) parts.push(`$${costUsd < 0.01 ? costUsd.toFixed(4) : costUsd.toFixed(2)}`);
  return parts.join(" · ");
}

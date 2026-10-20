// The Integrations page's "Social engagement" card: core's Social blueprint set (the auto-reply rule and log types, their
// two collections and the engine's scheduled task), what of it is installed, and the task's state. Pure, so `npm test`
// covers it (socialEngagement.test.mjs).

/** The category core's social blueprints share. */
export const SOCIAL_CATEGORY = "Social";
/** The scheduled task's type: how the card finds it, whatever a person renamed it. */
export const SOCIAL_TASK_TYPE = "social_engagement";

export interface SocialBlueprint {
  slug: string;
  name: string;
  kind: string;
  source: string;
  category: string;
  applied: boolean;
  available: boolean;
}

export interface SocialTask {
  id: string;
  enabled?: boolean;
  taskType?: string;
  task_type?: string;
  taskConfig?: Record<string, unknown> | null;
  task_config?: Record<string, unknown> | null;
}

const KIND_ORDER = ["entry_type", "collection", "scheduled_task"];

/** Core's Social blueprints in the order they apply: types, then collections, then the task. */
export function socialSet<T extends SocialBlueprint>(blueprints: T[]): T[] {
  const rank = (b: T) => (KIND_ORDER.includes(b.kind) ? KIND_ORDER.indexOf(b.kind) : KIND_ORDER.length);
  return blueprints
    .map((b, i) => ({ b, i }))
    .filter(({ b }) => b.source === "core" && b.category === SOCIAL_CATEGORY)
    .sort((x, y) => rank(x.b) - rank(y.b) || x.i - y.i)
    .map(({ b }) => b);
}

/** The slugs still to apply (those the workspace can apply: an unmet requirement is applied after the thing it needs). */
export function missingSlugs(set: SocialBlueprint[]): string[] {
  return set.filter((b) => !b.applied).map((b) => b.slug);
}

/** The engine's scheduled task among a workspace's tasks, or undefined before the set is applied. */
export function socialTask<T extends SocialTask>(tasks: T[]): T | undefined {
  return tasks.find((t) => (t.taskType ?? t.task_type) === SOCIAL_TASK_TYPE);
}

export interface TaskState {
  enabled: boolean;
  /** Rehearsal is on unless the task's config says `rehearsal: false` (the engine's own default). */
  rehearsal: boolean;
  /** Whether new comments are announced to workflows (`announce`, on unless the config says false). */
  announce: boolean;
  label: string;
  href: string;
}

const falsy = (v: unknown) => v === false || ["false", "0", "no", "off"].includes(String(v).toLowerCase());

/** What the card says about the task: switched on or off, rehearsal or live, and where to change it. */
export function taskState(task: SocialTask): TaskState {
  const config = task.taskConfig ?? task.task_config ?? {};
  const enabled = task.enabled === true;
  const rehearsal = !falsy(config.rehearsal ?? true);
  const announce = !falsy(config.announce ?? true);
  const mode = rehearsal ? "rehearsal on (nothing is sent)" : "rehearsal off (replies are sent)";
  return {
    enabled,
    rehearsal,
    announce,
    label: `${enabled ? "Enabled" : "Disabled"}, ${mode}`,
    href: `/workspace/scheduled-tasks/${task.id}`,
  };
}

// Where every admin and workspace settings page sits: one node per page, linked to its parent. The layouts build the
// breadcrumb trail from it (`crumb` prop), the admin sidebar and the settings hub read their labels and links from it,
// and navTree.test.mjs checks that every page declares a node and every node points at a page.
//
// `label` is the short name (a crumb, a sidebar row); `title` is the page's H1 when that differs. A detail page's href is
// its route pattern ("/admin/users/[id]"); the page passes its own title, and `crumbParams` when a dynamic page is an
// ancestor of another (the event type above its webhook page).

export interface NavNode {
  id: string;
  label: string;
  href: string;
  parent?: string;
  /** The page's H1 when it isn't the label (detail pages pass their own). */
  title?: string;
}

export interface Crumb {
  label: string;
  href: string;
}

const NODES: NavNode[] = [
  // Platform admin
  { id: "admin", label: "Admin", href: "/admin", title: "Overview" },
  { id: "admin.users", label: "Users", href: "/admin/users", parent: "admin" },
  { id: "admin.users.new", label: "Create User", href: "/admin/users/new", parent: "admin.users" },
  { id: "admin.users.user", label: "User", href: "/admin/users/[id]", parent: "admin.users" },
  { id: "admin.workspaces", label: "Workspaces", href: "/admin/workspaces", parent: "admin" },
  { id: "admin.workspaces.new", label: "Create Workspace", href: "/admin/workspaces/new", parent: "admin.workspaces" },
  // A workspace's detail page still lives under its legacy /admin/groups/{id} path.
  { id: "admin.workspaces.workspace", label: "Workspace", href: "/admin/groups/[id]", parent: "admin.workspaces" },
  { id: "admin.roles", label: "Roles", href: "/admin/roles", parent: "admin", title: "Roles & Permissions" },
  { id: "admin.site-settings", label: "Site Settings", href: "/admin/site-settings", parent: "admin" },
  { id: "admin.email", label: "Email", href: "/admin/email-settings", parent: "admin", title: "Email Settings" },
  {
    id: "admin.submission-protection",
    label: "Submission Protection",
    href: "/admin/submission-protection",
    parent: "admin",
  },
  { id: "admin.plugins", label: "Plugins", href: "/admin/plugins", parent: "admin" },
  { id: "admin.character-library", label: "Character Library", href: "/admin/character-library", parent: "admin" },
  { id: "admin.system", label: "System", href: "/admin/system", parent: "admin", title: "Platform System" },
  { id: "admin.events", label: "Events", href: "/admin/events", parent: "admin" },
  { id: "admin.scheduled-tasks", label: "Scheduled Tasks", href: "/admin/scheduled-tasks", parent: "admin" },
  {
    id: "admin.scheduled-tasks.new",
    label: "New System Task",
    href: "/admin/scheduled-tasks/new",
    parent: "admin.scheduled-tasks",
  },
  {
    id: "admin.scheduled-tasks.log",
    label: "Execution Log",
    href: "/admin/scheduled-tasks/log",
    parent: "admin.scheduled-tasks",
    title: "Global Execution Log",
  },
  {
    id: "admin.scheduled-tasks.task",
    label: "Scheduled Task",
    href: "/admin/scheduled-tasks/[id]",
    parent: "admin.scheduled-tasks",
  },
  { id: "admin.backups", label: "Backups", href: "/admin/backups", parent: "admin" },
  { id: "admin.maintenance", label: "Maintenance", href: "/admin/maintenance", parent: "admin" },

  // Workspace pages with no parent: the dashboard (the sidebar's Workspace → Settings) and creating a workspace.
  { id: "workspace", label: "Workspace", href: "/workspace", title: "Workspace Dashboard" },
  { id: "workspace.new", label: "Create Workspace", href: "/workspace/new" },

  // Workspace settings
  { id: "settings", label: "Settings", href: "/workspace/settings", title: "Workspace Settings" },
  {
    id: "settings.general",
    label: "General",
    href: "/workspace/settings/general",
    parent: "settings",
    title: "Workspace Details",
  },
  { id: "settings.environment", label: "Environment", href: "/workspace/settings/environment", parent: "settings" },
  {
    id: "settings.secrets",
    label: "Secrets",
    href: "/workspace/settings/secrets",
    parent: "settings.environment",
    title: "Workspace Secrets",
  },
  { id: "settings.backups", label: "Backups", href: "/workspace/settings/backups", parent: "settings" },
  { id: "settings.members", label: "Members", href: "/workspace/members", parent: "settings" },
  { id: "settings.members.new", label: "Add Member", href: "/workspace/members/new", parent: "settings.members" },
  { id: "settings.invites", label: "Invitations", href: "/workspace/invites", parent: "settings" },
  { id: "settings.invites.new", label: "Create Invite", href: "/workspace/invites/new", parent: "settings.invites" },
  {
    id: "settings.invites.email",
    label: "Email Invite",
    href: "/workspace/invites/[token]/email",
    parent: "settings.invites",
  },
  { id: "settings.entry-types", label: "Entry Types", href: "/workspace/entry-types", parent: "settings" },
  {
    id: "settings.entry-types.new",
    label: "Create Entry Type",
    href: "/workspace/entry-types/new",
    parent: "settings.entry-types",
  },
  {
    id: "settings.entry-types.entry-type",
    label: "Entry Type",
    href: "/workspace/entry-types/[id]",
    parent: "settings.entry-types",
  },
  { id: "settings.tags", label: "Tags", href: "/workspace/tags", parent: "settings" },
  {
    id: "settings.email",
    label: "Email",
    href: "/workspace/settings/email",
    parent: "settings",
    title: "Email Templates",
  },
  {
    id: "settings.email.template",
    label: "Template",
    href: "/workspace/settings/email/[id]",
    parent: "settings.email",
  },
  { id: "settings.email.test", label: "Test Emails", href: "/workspace/settings/email/test", parent: "settings.email" },
  {
    id: "settings.email.smtp",
    label: "SMTP",
    href: "/workspace/settings/email/smtp",
    parent: "settings.email",
    title: "SMTP Configuration",
  },
  {
    id: "settings.submission-protection",
    label: "Submission Protection",
    href: "/workspace/settings/submission-protection",
    parent: "settings",
  },
  { id: "settings.integrations", label: "Integrations", href: "/workspace/settings/integrations", parent: "settings" },
  {
    id: "settings.integrations.health",
    label: "Alerts & health",
    href: "/workspace/settings/integration-health",
    parent: "settings.integrations",
  },
  { id: "settings.ai", label: "AI Settings", href: "/workspace/settings/ai-workflow", parent: "settings" },
  { id: "settings.ai-ask", label: "Ask", href: "/workspace/settings/ai-ask", parent: "settings" },
  { id: "settings.ai-agents", label: "Agents", href: "/workspace/settings/ai-agents", parent: "settings" },
  {
    id: "settings.ai-executions",
    label: "AI Executions",
    href: "/workspace/settings/ai-executions",
    parent: "settings",
  },
  {
    id: "settings.ai-mcp-servers",
    label: "MCP Servers",
    href: "/workspace/settings/ai-mcp-servers",
    parent: "settings",
  },

  // Automation and Publishing pages sit directly under Settings: the hub's tabs aren't pages, so they're not crumbs.
  { id: "automation.workflows", label: "Workflows", href: "/automation/workflows", parent: "settings" },
  { id: "automation.events", label: "Events", href: "/automation/events", parent: "settings" },
  { id: "automation.events.type", label: "Event", href: "/automation/events/[type]", parent: "automation.events" },
  {
    id: "automation.events.type.webhook",
    label: "Connect Webhook",
    href: "/automation/events/[type]/webhook/[webhookId]",
    parent: "automation.events.type",
  },
  { id: "automation.webhooks", label: "Webhooks", href: "/automation/webhooks", parent: "settings" },
  {
    id: "automation.webhooks.new",
    label: "New Webhook",
    href: "/automation/webhooks/new",
    parent: "automation.webhooks",
  },
  {
    id: "automation.webhooks.log",
    label: "Activity Log",
    href: "/automation/webhooks/log",
    parent: "automation.webhooks",
    title: "Webhook Activity Log",
  },
  {
    id: "automation.webhooks.webhook",
    label: "Edit Webhook",
    href: "/automation/webhooks/[id]",
    parent: "automation.webhooks",
  },
  {
    id: "automation.incoming-webhooks",
    label: "Incoming Webhooks",
    href: "/automation/incoming-webhooks",
    parent: "settings",
  },
  {
    id: "automation.scheduled-tasks",
    label: "Scheduled Tasks",
    href: "/workspace/scheduled-tasks",
    parent: "settings",
  },
  {
    id: "automation.scheduled-tasks.new",
    label: "New Scheduled Task",
    href: "/workspace/scheduled-tasks/new",
    parent: "automation.scheduled-tasks",
  },
  {
    id: "automation.scheduled-tasks.log",
    label: "Activity Log",
    href: "/workspace/scheduled-tasks/log",
    parent: "automation.scheduled-tasks",
  },
  {
    id: "automation.scheduled-tasks.task",
    label: "Scheduled Task",
    href: "/workspace/scheduled-tasks/[id]",
    parent: "automation.scheduled-tasks",
  },
  { id: "automation.event-log", label: "Event Log", href: "/workspace/events", parent: "settings" },

  { id: "publishing.site", label: "Site", href: "/publishing/site", parent: "settings", title: "Site Configuration" },
  { id: "publishing.clients", label: "API Clients", href: "/publishing/clients", parent: "settings" },
  {
    id: "publishing.clients.new",
    label: "New API Client",
    href: "/publishing/clients/new",
    parent: "publishing.clients",
  },
  {
    id: "publishing.clients.client",
    label: "Edit API Client",
    href: "/publishing/clients/[id]/edit",
    parent: "publishing.clients",
  },
];

/** Every node, in map order (navTree.test.mjs checks ids and hrefs are unique). */
export const NAV_NODE_LIST: readonly NavNode[] = NODES;

export const NAV_NODES: ReadonlyMap<string, NavNode> = new Map(NODES.map((node) => [node.id, node]));

/** The node for `id`; throws on an unknown id so a typo fails the build instead of rendering no trail. */
export function navNode(id: string): NavNode {
  const node = NAV_NODES.get(id);
  if (!node) throw new Error(`Unknown nav node "${id}" (see lib/navTree.ts)`);
  return node;
}

/** A node's link. Pass params for a route pattern ("/admin/users/[id]"). */
export function navHref(id: string, params: Record<string, string> = {}): string {
  return navNode(id).href.replace(/\[(\w+)\]/g, (_, key: string) => encodeURIComponent(params[key] ?? ""));
}

/** The H1 a page shows when it doesn't pass its own. */
export function navTitle(id: string): string {
  const node = navNode(id);
  return node.title ?? node.label;
}

/**
 * The ancestors of `id`, root first — the page itself is not included (its title is the H1). `labels` overrides an
 * ancestor's label by node id, for a dynamic ancestor such as an event type.
 */
export function navTrail(
  id: string,
  options: { params?: Record<string, string>; labels?: Record<string, string> } = {},
): Crumb[] {
  const trail: Crumb[] = [];
  const seen = new Set<string>([id]);
  let parentId = navNode(id).parent;
  while (parentId) {
    if (seen.has(parentId)) throw new Error(`Nav node cycle at "${parentId}"`);
    seen.add(parentId);
    const parent = navNode(parentId);
    trail.unshift({ label: options.labels?.[parentId] ?? parent.label, href: navHref(parentId, options.params) });
    parentId = parent.parent;
  }
  return trail;
}

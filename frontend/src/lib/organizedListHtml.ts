// HTML the shared list kit draws for client-rendered lists (the pages build their lists from JSON, so these are
// strings, like lib/integrationLogo.ts's `markHtml`). Styles: components/OrganizedSections.astro. Pure, so `npm test`
// covers it (organizedListHtml.test.mjs).

import { markHtml } from "./integrationLogo.ts";
import { countsText, type Integrations, type Section } from "./organizedList.ts";

const esc = (s: unknown): string =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );

export interface SectionsOptions<T> {
  /** Singular noun for the counts: "workflow". */
  noun: string;
  integrations: Integrations;
  /** The item that was linked to (`?workflow=<id>`): its `renderItem` call gets `linked: true`. */
  linkedId?: string | null;
  /** Reads an item's id (needed with `linkedId`). */
  id?: (item: T) => string;
  /** False for pages whose items have no On/Off: the counts then read "5 events". */
  onOff?: boolean;
  /** Admin only: the From a removed integration heading gets a "Delete all of these" button (`org-delete-removed`);
   * organizedListView.ts's `removedDelete` option wires it. */
  removedAction?: boolean;
  /** One card, as HTML. Off items should carry the `off` class so they dim. */
  renderItem: (item: T, state: { linked: boolean }) => string;
}

/** The sections: a heading (integration logo, name, "N workflows, M on") over the cards. */
export function sectionsHtml<T>(sections: Section<T>[], options: SectionsOptions<T>): string {
  return sections
    .map((section) => {
      const info = section.integrationId ? options.integrations[section.integrationId] : undefined;
      const mark = info?.slug ? markHtml({ slug: info.slug, icon: info.icon, hasLogo: info.hasLogo }) : "";
      const cards = section.items
        .map((item) =>
          options.renderItem(item, { linked: options.linkedId != null && options.id?.(item) === options.linkedId }),
        )
        .join("");
      return `<section class="org-section" data-section="${esc(section.key)}">
        <h4 class="org-title">${mark}<span class="org-name">${esc(section.title)}</span><span class="org-counts">${esc(countsText(section, options.noun, { onOff: options.onOff }))}</span>${section.kind === "removed" && options.removedAction ? `<button type="button" class="org-btn danger org-delete-removed">Delete all of these</button>` : ""}</h4>
        <div class="org-items">${cards}</div>
      </section>`;
    })
    .join("");
}

export interface MenuAction {
  /** The page's own class for the click handler (`js-delete`). */
  cls: string;
  label: string;
  title?: string;
  danger?: boolean;
}

/** The "⋯" button and its menu (a bottom sheet on phones). Opening and closing: organizedListView.ts. */
export function menuHtml(actions: MenuAction[]): string {
  const items = actions
    .map(
      (a) =>
        `<button type="button" class="org-menu-item${a.danger ? " danger" : ""} ${esc(a.cls)}" role="menuitem"${a.title ? ` title="${esc(a.title)}"` : ""}>${esc(a.label)}</button>`,
    )
    .join("");
  return `<div class="org-more-wrap"><button type="button" class="org-more" aria-haspopup="menu" aria-expanded="false" aria-label="More actions" title="More actions">⋯</button><div class="org-menu" role="menu" hidden>${items}</div></div>`;
}

/** The On/Off switch. `label` names the item for screen readers. */
export function switchHtml(options: { on: boolean; cls: string; label: string }): string {
  const state = options.on ? "on" : "off";
  return `<button type="button" class="org-switch ${esc(options.cls)}" role="switch" aria-checked="${options.on}" aria-label="${esc(`${options.label}: ${state}`)}" title="${options.on ? "On — click to switch off" : "Off — click to switch on"}"><span class="org-switch-knob"></span></button>`;
}

/** The confirmation for "Delete all of these": says what goes and lists every item by name. The view puts it in a
 * `<dialog>` and listens for the `org-confirm-delete` / `org-confirm-cancel` buttons. */
export function removedConfirmHtml(names: string[], noun: string): string {
  const count = names.length;
  const what = `${count} ${noun}${count === 1 ? "" : "s"}`;
  return `<form method="dialog" class="org-confirm">
    <h3>Delete ${esc(what)}?</h3>
    <p>${count === 1 ? "This was" : "These were"} installed by an integration that has been removed. Deleting cannot be undone.</p>
    <ul class="org-confirm-list">${names.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    <div class="org-confirm-actions"><button type="button" class="org-btn org-confirm-cancel">Cancel</button><button type="button" class="org-btn danger org-confirm-delete">Delete ${esc(what)}</button></div>
  </form>`;
}

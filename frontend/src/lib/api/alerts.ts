/**
 * What every alert settings page shares (backend schemas/alerts.py): a channel's last delivery, a kind of
 * alert, and a message-capable action a route can use. Admin → Platform alerts (api/admin/platformAlerts.ts)
 * and Settings → Automation → Notifications (api/notifications.ts) build on these.
 */

export type DeliveryOutcome = "sent" | "failed" | "skipped";

export interface AlertDelivery {
  at: string;
  outcome: DeliveryOutcome;
  detail: string;
  /** The event that was sent; null for a test. */
  eventType: string | null;
  test: boolean;
}

export interface AlertKind {
  key: string;
  label: string;
  description: string;
  eventType: string;
  enabled: boolean;
  default: boolean;
}

export interface AlertActionInput {
  key: string;
  label: string;
  description: string;
  required: boolean;
}

export interface AlertTarget {
  integrationId: string;
  integrationName: string;
  provider: string;
  providerName: string;
  connectionEnabled: boolean;
  action: string;
  actionLabel: string;
  inputs: AlertActionInput[];
}

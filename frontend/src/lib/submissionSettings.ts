// A form's submission settings (an entry type's `capabilitiesJson.submission`) as the entry type page reads them.
//
// The server takes either spelling of a setting's name, `enableCaptcha` or `enable_captcha`, and stores what it was sent:
// a form made by a package or through the API often carries the second, the page writes the first. The page's boxes are
// named the first way, so a form stored the other way showed every box empty, and saving it wrote a second, contradicting
// copy of each setting. Read through `camelSettings` and both show the same and save as one.

const camel = (key: string): string => key.replace(/_([a-z0-9])/g, (_, letter: string) => letter.toUpperCase());

/** The settings with every name in the page's spelling. Where a setting is stored both ways, the page's own spelling wins. */
export function camelSettings(stored: unknown): Record<string, unknown> {
  if (stored === null || typeof stored !== "object" || Array.isArray(stored)) return {};
  const out: Record<string, unknown> = {};
  const entries = Object.entries(stored as Record<string, unknown>);
  for (const [key, value] of entries) if (camel(key) !== key) out[camel(key)] = value;
  for (const [key, value] of entries) if (camel(key) === key) out[key] = value;
  return out;
}

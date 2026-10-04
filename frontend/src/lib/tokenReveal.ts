/**
 * Show a freshly minted API token exactly once, straight from the create/rotate response.
 *
 * The token used to travel to the list page as `?token=…`, which put it in browser history and in
 * every access log between the browser and Marvin (Cloudflare tunnel, uvicorn). It now goes from
 * the response into the dialog and nowhere else: never a URL, never storage, never the console.
 * Takes the dialog through a narrow interface so it runs under `node --test` (tokenReveal.test.mjs).
 */

/** The slice of the token dialog this module touches. */
export interface TokenDialog {
  showModal(): void;
  close(): void;
  querySelector(selector: string): { textContent: string | null } | null;
}

export const TOKEN_VALUE_SELECTOR = "[data-token-value]";

/** Put `token` in the dialog and open it. Returns false (dialog untouched) when there's no token. */
export function revealTokenOnce(dialog: TokenDialog, token: string | null | undefined): boolean {
  const slot = dialog.querySelector(TOKEN_VALUE_SELECTOR);
  if (!token || !slot) return false;
  slot.textContent = token;
  dialog.showModal();
  return true;
}

/** Wipe the token from the page so it can't be read back after the dialog is dismissed. */
export function forgetToken(dialog: TokenDialog): void {
  const slot = dialog.querySelector(TOKEN_VALUE_SELECTOR);
  if (slot) slot.textContent = "";
}

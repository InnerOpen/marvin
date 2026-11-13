/**
 * API reads shared within one page request.
 *
 * A page, its layout and the layout's components each asked the API for the same things (who is signed in, their
 * workspaces, the current one, the entry types…), up to four times per page view, and each authenticated call has a
 * fixed cost. The middleware gives every GET page request its own cache (`Astro.locals.apiCache`); a read made through
 * `readOnce` with that request's locals goes to the API once, and every other caller in the request shares it.
 *
 * Nothing is shared across requests: the cache lives on the request's locals and goes with it. A request without one
 * (a form POST, which writes and then renders, or a call from the browser) reads straight from the API, as before.
 * Free of `astro:*` imports so `node --test` can load it.
 */

/** One request's reads, by token and path; the value is the read in flight or done. */
export type RequestCache = Map<string, Promise<unknown>>;

/** What `readOnce` needs from a request: its locals, or nothing outside one. */
export interface RequestScope {
  apiCache?: RequestCache;
}

export function createRequestCache(): RequestCache {
  return new Map();
}

/**
 * `load()` — the GET of `path` with `authToken` — at most once in this request. A caller arriving while the read is in
 * flight waits for the same one. Each caller gets its own copy of the answer, so one that sorts or edits what it got
 * can't change what another sees. A failed read is forgotten (each caller in flight gets the error): the next caller
 * asks the API again, as it would have before.
 */
export async function readOnce<T>(scope: RequestScope | null | undefined, path: string, authToken: string | undefined, load: () => Promise<T>): Promise<T> {
  const cache = scope?.apiCache;
  if (!cache) return load();
  const key = `${authToken ?? ""} GET ${path}`;
  let pending = cache.get(key) as Promise<T> | undefined;
  if (!pending) {
    const read: Promise<T> = new Promise<T>((resolve) => resolve(load()));
    pending = read;
    cache.set(key, read);
    read.catch(() => {
      if (cache.get(key) === read) cache.delete(key);
    });
  }
  return structuredClone(await pending);
}

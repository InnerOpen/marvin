import { getApiUrl, getCookieName, getSiteClientToken, hasApiBackend } from "./config";

export class ApiRequestError extends Error {
  status: number;
  url: string;
  body?: unknown;

  constructor(message: string, status: number, url: string, body?: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

const DEV_MODE = import.meta.env.DEV;
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

/**
 * Sleep for specified milliseconds
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Check if error is retryable (network errors or 5xx)
 */
function isRetryable(error: unknown): boolean {
  if (error instanceof ApiRequestError) {
    return error.status >= 500;
  }
  return true; // Network errors are retryable
}

/**
 * Get authentication token from Astro cookies (for SSR)
 * This should be called from Astro pages and passed to fetchApi
 */
export function getAuthToken(cookies?: { get: (name: string) => { value?: string } | undefined }): string | undefined {
  if (!cookies) return undefined;
  const cookie = cookies.get(getCookieName());
  return cookie?.value;
}

/**
 * Main API client function with retry logic and improved error handling
 *
 * @param path - API endpoint path
 * @param init - Fetch options
 * @param authToken - Optional authentication token (from Astro.cookies)
 */
export async function fetchApi<T>(path: string, init: RequestInit = {}, authToken?: string): Promise<T> {
  if (!hasApiBackend()) {
    throw new Error("MARVIN_API_URL is not configured.");
  }

  const url = getApiUrl(path);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  // Use authToken if provided (SSR context), otherwise fall back to the site-client token.
  // getSiteClientToken() reads process.env, so it only yields a token server-side — in the
  // browser it is empty, which is correct: the site token is a server-only credential.
  const siteClientToken = getSiteClientToken();
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  } else if (siteClientToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${siteClientToken}`);
  }

  // Include credentials to send cookies with requests
  const fetchInit: RequestInit = {
    ...init,
    headers,
    credentials: "include", // Send cookies with cross-origin requests
  };

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      if (DEV_MODE && attempt === 0) {
        const context = typeof window === "undefined" ? "SSR" : "Client";
        console.debug(`[${context}] ➡️  ${init.method || "GET"} ${path}`);
        if (authToken) {
          console.debug(`[${context}]    Auth: ${authToken.substring(0, 20)}...`);
        }
      }

      const startTime = DEV_MODE ? Date.now() : 0;
      const response = await fetch(url, fetchInit);

      if (DEV_MODE && attempt === 0) {
        const duration = Date.now() - startTime;
        const context = typeof window === "undefined" ? "SSR" : "Client";
        const statusEmoji = response.ok ? "✅" : "❌";
        console.debug(`[${context}] ${statusEmoji} ${init.method || "GET"} ${path} → ${response.status} (${duration}ms)`);
      }

      // Handle 401 Unauthorized - redirect to login
      if (response.status === 401) {
        if (DEV_MODE) {
          console.warn("[API] 401 Unauthorized - user needs to login");
        }
        // In SSR context we can't redirect, throw error instead
        throw new ApiRequestError("Unauthorized - please log in", response.status, url.toString());
      }

      // Handle other errors
      if (!response.ok) {
        let errorBody: any;
        const contentType = response.headers.get("content-type");

        try {
          // Clone response to allow reading body multiple times if needed
          const _responseClone = response.clone();

          if (contentType?.includes("application/json")) {
            errorBody = await response.json();
          } else {
            errorBody = await response.text();
          }
        } catch (_parseError) {
          // If parsing fails, try to get text from the clone
          try {
            errorBody = await response.text();
          } catch {
            errorBody = `Failed to parse error response (${response.status})`;
          }
        }

        // FastAPI error `detail` may be a string, or an array/object (e.g. 422 validation
        // errors). Never String() an object — that yields "[object Object]".
        let detailText: string | undefined;
        if (typeof errorBody === "object" && errorBody !== null && "detail" in errorBody) {
          const d = (errorBody as { detail: unknown }).detail;
          if (typeof d === "string") {
            detailText = d;
          } else if (Array.isArray(d)) {
            detailText = d
              .map((x) => (x && typeof x === "object" ? ((x as any).msg ?? JSON.stringify(x)) : String(x)))
              .join("; ");
          } else if (d != null) {
            detailText = JSON.stringify(d);
          }
        }
        const errorMessage = detailText ?? `API request failed with ${response.status}`;

        const error = new ApiRequestError(errorMessage, response.status, url.toString(), errorBody);

        // Retry on 5xx errors
        if (attempt < MAX_RETRIES && error.status >= 500) {
          if (DEV_MODE) {
            console.warn(`[API] Retrying after ${RETRY_DELAY_MS}ms (attempt ${attempt + 1}/${MAX_RETRIES})`);
          }
          await sleep(RETRY_DELAY_MS * (attempt + 1));
          continue;
        }

        throw error;
      }

      const data = (await response.json()) as T;
      return data;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      // Don't retry on non-retryable errors
      if (!isRetryable(error)) {
        throw lastError;
      }

      // Don't retry on last attempt
      if (attempt === MAX_RETRIES) {
        throw lastError;
      }

      if (DEV_MODE) {
        console.warn(`[API] Request failed, retrying... (attempt ${attempt + 1}/${MAX_RETRIES})`);
      }

      await sleep(RETRY_DELAY_MS * (attempt + 1));
    }
  }

  throw lastError || new Error("Request failed after retries");
}

# Authentication Usage Guide

This guide shows how to add authentication checks to Astro pages in the Marvin frontend.

## Available Functions

Import from `@/lib/auth`:

- `requireAuth()` - Require any authenticated user
- `requireAdmin()` - Require authenticated admin user
- `getCurrentUser()` - Get current user without redirect
- `isAuthenticated()` - Check if user is logged in (boolean)
- `isAdmin()` - Check if user is admin (boolean)

## Basic Usage

### Require Any Authenticated User

Most pages should use this:

```astro
---
import { requireAuth } from '@/lib/auth';
import AppLayout from '@/layouts/AppLayout.astro';

// Redirects to login if not authenticated
const user = await requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname);

// Now you can access user data
console.log(`User: ${user.username}`);
---

<AppLayout title="Dashboard">
  <h1>Welcome, {user.username}!</h1>
</AppLayout>
```

### Require Admin User

For admin-only pages:

```astro
---
import { requireAdmin } from '@/lib/auth';
import AdminLayout from '@/layouts/AdminLayout.astro';

// Redirects to login if not authenticated, to home if not admin
const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname);
---

<AdminLayout title="Admin Settings">
  <h1>Admin Page</h1>
</AdminLayout>
```

### Optional Authentication

For pages where auth is optional:

```astro
---
import { getCurrentUser } from '@/lib/auth';
import AppLayout from '@/layouts/AppLayout.astro';

const user = await getCurrentUser(Astro.cookies);
---

<AppLayout title="Home">
  {user ? (
    <p>Welcome back, {user.username}!</p>
  ) : (
    <a href="/login">Login</a>
  )}
</AppLayout>
```

### Boolean Checks

For conditional logic:

```astro
---
import { isAuthenticated, isAdmin } from '@/lib/auth';
import AppLayout from '@/layouts/AppLayout.astro';

const loggedIn = await isAuthenticated(Astro.cookies);
const admin = await isAdmin(Astro.cookies);
---

<AppLayout title="Features">
  {loggedIn && <p>You are logged in</p>}
  {admin && <a href="/admin">Admin Panel</a>}
</AppLayout>
```

## How It Works

### Return Path

When `requireAuth()` or `requireAdmin()` redirect to login, they include the current page path:

```
/login?return=/entries/123
```

After successful login, the user is redirected back to the original page.

### User Object

All auth functions return a `User` object when authenticated:

```typescript
interface User {
  id: string;
  username: string;
  email?: string;
  admin?: boolean;
  groupId?: string;
}
```

## Migration Guide

### Old Pattern (checking manually)

```astro
---
import { getAuthToken, fetchApi } from "@/lib/api/client";

const authToken = getAuthToken(Astro.cookies);

try {
  const currentUser = await fetchApi<any>('/api/self', {}, authToken);
  if (currentUser?.admin !== true) {
    return Astro.redirect('/');
  }
} catch (e) {
  return Astro.redirect('/login');
}
---
```

### New Pattern (using auth helpers)

```astro
---
import { requireAdmin } from "@/lib/auth";
import { getAuthToken } from "@/lib/api/client";

const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);
---
```

## Examples

### Dashboard Page

```astro
---
import { requireAuth } from '@/lib/auth';
import { getAuthToken } from '@/lib/api/client';
import { listEntries } from '@/lib/api/entries';
import AppLayout from '@/layouts/AppLayout.astro';

const user = await requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);
const entries = await listEntries(authToken);
---

<AppLayout title="Dashboard">
  <h1>Welcome, {user.username}</h1>
  <p>You have {entries.length} entries</p>
</AppLayout>
```

### Admin Settings Page

```astro
---
import { requireAdmin } from '@/lib/auth';
import { getAuthToken, fetchApi } from '@/lib/api/client';
import AdminLayout from '@/layouts/AdminLayout.astro';

const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);

const settings = await fetchApi('/api/admin/settings', {}, authToken);
---

<AdminLayout title="Settings">
  <h1>Admin Settings</h1>
</AdminLayout>
```

### Public Page with Optional Auth

```astro
---
import { getCurrentUser } from '@/lib/auth';
import Layout from '@/layouts/Layout.astro';

const user = await getCurrentUser(Astro.cookies);
---

<Layout title="Home">
  <header>
    {user ? (
      <nav>
        <a href="/">Dashboard</a>
        <span>Logged in as {user.username}</span>
      </nav>
    ) : (
      <nav>
        <a href="/login">Login</a>
      </nav>
    )}
  </header>
</Layout>
```

## Best Practices

1. **Always use `requireAuth()` or `requireAdmin()`** at the top of protected pages
2. **Pass `Astro.url.pathname`** to preserve the return path
3. **Use `getCurrentUser()`** only for optional auth scenarios
4. **Use boolean helpers** (`isAuthenticated`, `isAdmin`) for conditional rendering
5. **Keep auth token separate** - still use `getAuthToken()` for API calls

## Error Handling

Auth functions handle errors gracefully:

- Invalid/expired tokens → redirects to login
- Missing admin privilege → redirects to home
- Network errors → redirects to login

No try/catch needed for basic auth checks.

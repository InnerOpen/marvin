# Authentication Migration Checklist

Quick reference for updating existing pages to use the new auth system.

## For Regular Pages (Non-Admin)

### Before
```astro
---
import { getAuthToken, fetchApi } from "@/lib/api/client";

const authToken = getAuthToken(Astro.cookies);

try {
  const currentUser = await fetchApi<any>('/api/self', {}, authToken);
} catch (e) {
  return Astro.redirect('/login');
}
---
```

### After
```astro
---
import { requireAuth } from "@/lib/auth";
import { getAuthToken } from "@/lib/api/client";

const user = await requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);
---
```

## For Admin Pages

### Before
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
  return Astro.redirect('/');
}
---
```

### After
```astro
---
import { requireAdmin } from "@/lib/auth";
import { getAuthToken } from "@/lib/api/client";

const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);
---
```

## Pages to Update

### Admin Pages (use `requireAdmin`)
- [ ] frontend/src/pages/admin/maintenance.astro
- [ ] frontend/src/pages/admin/site-settings.astro
- [ ] frontend/src/pages/admin/users.astro
- [ ] frontend/src/pages/admin/groups/[id].astro
- [ ] frontend/src/pages/admin/users/[id].astro

### Platform Pages (use `requireAuth`)
- [ ] frontend/src/pages/platform/users.astro

### Publishing Pages (use `requireAuth`)
- [ ] frontend/src/pages/publishing/clients.astro

### Entry Pages (use `requireAuth`)
- [ ] frontend/src/pages/entries/[id].astro
- [ ] frontend/src/pages/entries/new.astro
- [ ] frontend/src/pages/entry-types.astro
- [ ] frontend/src/pages/entry-types/[id].astro

### Collection Pages (use `requireAuth`)
- [ ] frontend/src/pages/collections/[id].astro

### Asset Pages (use `requireAuth`)
- [ ] frontend/src/pages/assets.astro
- [ ] frontend/src/pages/assets/new.astro
- [ ] frontend/src/pages/assets/[id].astro

### Automation Pages (use `requireAuth`)
- [ ] frontend/src/pages/automation/notifications.astro
- [ ] frontend/src/pages/automation/notifications/[id].astro
- [ ] frontend/src/pages/automation/notifications/new.astro

### Workspace Pages (use `requireAuth`)
- [ ] frontend/src/pages/workspace/settings/index.astro
- [ ] frontend/src/pages/workspace/members.astro
- [ ] frontend/src/pages/workspace/invites.astro

### User Pages (use `requireAuth`)
- [ ] frontend/src/pages/user/api-tokens.astro

### Resource Pages (use `requireAuth`)
- [ ] frontend/src/pages/resources.astro
- [ ] frontend/src/pages/resources/[id].astro
- [ ] frontend/src/pages/resources/new.astro

## Already Updated
- [x] frontend/src/pages/index.astro (dashboard)
- [x] frontend/src/pages/admin/email-settings.astro

## Quick Find & Replace

To update all pages at once, you can use these patterns:

### Pattern 1: Basic auth check
Find:
```
const authToken = getAuthToken(Astro.cookies);

try {
  const currentUser = await fetchApi<any>('/api/self', {}, authToken);
} catch (e) {
  return Astro.redirect('/login');
}
```

Replace with:
```
const user = await requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname);
const authToken = getAuthToken(Astro.cookies);
```

### Pattern 2: Admin check
Find:
```
try {
  const currentUser = await fetchApi<any>('/api/self', {}, authToken);
  if (currentUser?.admin !== true) {
    return Astro.redirect('/');
  }
} catch (e) {
  return Astro.redirect('/');
}
```

Replace with:
```
const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname);
```

## Import Updates

Add to imports:
```astro
import { requireAuth } from "@/lib/auth";
// or
import { requireAdmin } from "@/lib/auth";
```

## Testing

After updating a page, test:
1. Access page while logged out → should redirect to login
2. Login → should redirect back to original page
3. For admin pages: access as non-admin → should redirect to home

## Benefits

- ✅ One-line auth check
- ✅ Automatic login redirect with return path
- ✅ Type-safe user object
- ✅ No try/catch needed
- ✅ Consistent across all pages
- ✅ Better UX (return to original page after login)

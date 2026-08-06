# GroupUp — PRD

## Overview
Mobile-first Expo React Native app (Italian) for organizing and joining activity groups (basket, calcio, tennis, biliardo, ping pong, discoteca, bar, volley, padel, running, viaggi, altro, custom).

## Authentication (multi-provider)
- **Email/Password** with mandatory email verification (Resend-alternative via Emergent integrations).
- **Google Sign-In** via Emergent-managed OAuth.
- **Apple Sign-In** (iOS only, hidden on Android/Web).
- **Password reset** via emailed short-lived (30 min) link.

Users may attach multiple auth providers to a single account (matched by email). One user record; `providers[]` field tracks how they've signed in.

## Onboarding
After first successful authentication, users complete a required profile: foto (from gallery, base64), sesso (Uomo/Donna/Altro), età (13-120). Editable anytime from Profile tab.

## Core Features
1. **Esplora feed**: list of upcoming groups with sticky horizontal category chips.
2. **Crea gruppo**: title, category (predefined + custom), free-text location, date (14 quick chips + custom DD/MM/YYYY input for any future date), time, min/max participants, min/max age, description.
3. **Group detail**: info, participants, join/leave, delete (owner only).
4. **Group chat**: participants-only, 4s polling.
5. **Profile tab**: avatar + name + gender pill + age pill, tabs "Creati"/"Partecipati", Edit profile, Logout.

## Tech Stack
- **Frontend**: Expo Router ~54, TypeScript, `react-native-safe-area-context`, `react-native-keyboard-controller`, `expo-image-picker`, `expo-web-browser`, `expo-linking`, `expo-secure-store`, `expo-apple-authentication`.
- **Backend**: FastAPI + Motor (MongoDB) + httpx + passlib[bcrypt] + PyJWT.
- **Emails**: Emergent-managed transactional email integration.
- **Storage**: `user_sessions.expires_at` TTL (7 days); `auth_tokens.expires_at` TTL (short-lived verify/reset); unique indexes on `users.email`, `users.user_id`, `users.apple_sub` (sparse).

## Design
Neo-Brutalist Vibrant Play. Palette: `#FDFBF7` bg, `#FF4747` primary, `#FFE600` accent yellow, 2px black borders + solid black offset shadows, rounded-full pills.

## Endpoints
- `POST /api/auth/session` — Google OAuth session exchange.
- `POST /api/auth/signup` — email/password registration (sends verify email).
- `POST /api/auth/verify-email` — token → session + user.
- `POST /api/auth/login` — email+password → session + user.
- `POST /api/auth/request-password-reset` / `POST /api/auth/confirm-reset` — password reset flow.
- `POST /api/auth/apple` — Apple identity_token → session + user.
- `GET /api/auth/me` / `PATCH /api/auth/me`.
- `POST /api/auth/logout`.
- `GET /api/groups` (?category, ?q) / `POST /api/groups` / `GET /api/groups/{id}` / `DELETE /api/groups/{id}`.
- `POST /api/groups/{id}/join` / `POST /api/groups/{id}/leave`.
- `GET /api/groups/mine`.
- `GET /api/groups/{id}/messages` / `POST /api/groups/{id}/messages`.

## Roadmap
- WebSocket chat when >200 concurrent users.
- Feed pagination.
- Geo filter (city).
- Push notifications (post-deploy).

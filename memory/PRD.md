# GroupUp — PRD

## Overview
Mobile-first (Expo React Native) social app in Italian for organizing and joining activity groups (basket, calcio, tennis, biliardo, ping pong, discoteca, bar, volley, padel, running, viaggi, altro, custom).

## Users
Anyone with a Google account. On first login, users complete an **onboarding profile** (foto, sesso, età) before entering the app.

## Core Features
1. **Google Login** via Emergent-managed OAuth.
2. **Profilo utente**: foto profilo (galleria, base64), nome, sesso (Uomo/Donna/Altro), età. Editable anytime.
3. **Esplora feed**: lista gruppi con filtri per categoria (chip orizzontali, sticky).
4. **Crea gruppo**: titolo, categoria (predefinita o custom), luogo (testo libero), data (14 giorni), orario, min/max partecipanti, fascia età min/max, descrizione.
5. **Dettaglio gruppo**: info, lista partecipanti, join/leave, delete (solo owner).
6. **Chat di gruppo**: messaggi tra partecipanti (polling ogni 4s), riservata a chi ha joined.
7. **Profilo tab**: avatar, dati, tab "Creati" / "Partecipati", logout, edit profilo.

## Tech Stack
- **Frontend**: Expo Router (~54), TypeScript, react-native-safe-area-context, react-native-keyboard-controller, expo-image-picker, expo-web-browser, expo-linking, expo-secure-store.
- **Backend**: FastAPI + Motor (MongoDB) + httpx for Emergent Auth session verification.
- **Storage**: `user_sessions.expires_at` TTL (7 days), unique indexes on emails/user_ids/session_tokens.

## Design
Archetype 6 (Vibrant Play) + Neo-Brutalist. Palette: `#FDFBF7` bg, `#FF4747` primary, `#FFE600` accent, 2px black borders + solid black offset shadows, rounded-full pills, tactile buttons.

## Endpoints
- `POST /api/auth/session` → exchange Emergent session_id for our token.
- `GET /api/auth/me` / `PATCH /api/auth/me` → fetch/update profile (name, picture, gender, age).
- `POST /api/auth/logout` → destroy session.
- `GET /api/groups` (?category, ?q) / `POST /api/groups` / `GET /api/groups/{id}` / `DELETE /api/groups/{id}` (owner).
- `POST /api/groups/{id}/join` / `POST /api/groups/{id}/leave`.
- `GET /api/groups/mine` → { created[], joined[] }.
- `GET /api/groups/{id}/messages` / `POST /api/groups/{id}/messages` (participants only).

## Roadmap (next)
- WebSocket chat when >200 concurrent users.
- Paginazione feed.
- Filtro geografico (città).
- Push notifications (post-deploy build).

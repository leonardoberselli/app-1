// Lightweight content moderation for user-generated text (titles,
// descriptions, custom "Altro" category labels).
//
// The list is deliberately Italian-first plus a small English overlap and
// covers common obfuscations (leetspeak, spaces between letters, repeated
// letters, punctuation). It is NOT a legal filter — it's a first line of
// defense that keeps the feed safe from obvious illegal / offensive posts.

const BLOCKED_WORDS: string[] = [
  // Droga
  "droga", "drug", "drugs",
  "cocaina", "cocaine", "coca",
  "eroina", "heroin",
  "crack",
  "cannabis", "marijuana", "weed", "erba", "ganja", "hashish", "hash",
  "metanfetamina", "meth",
  "ecstasy", "mdma", "lsd", "ketamina",
  "spaccio", "spacciare", "pusher",
  // Armi / violenza
  "armi", "pistola", "pistole", "fucile", "fucili", "kalashnikov",
  "weapon", "weapons", "gun", "guns", "rifle",
  "esplosivo", "esplosivi", "bomba", "bombe", "bomb",
  "terrorismo", "terrorist", "attentato",
  "uccidere", "ammazzare", "omicidio", "kill", "murder", "hitman",
  "stupro", "stuprare", "rape",
  // Sesso illegale / non consensuale
  "orgia", "orgie", "orgy", "orgies",
  "pedofilo", "pedofilia", "pedophile", "pedophilia", "minorenni",
  "prostituzione", "prostituta", "prostitute", "escort", "puttana",
  "zoofilia",
  // Odio / auto-lesionismo
  "nazismo", "nazista", "nazi",
  "suicidio", "suicide", "ammazzarsi", "autolesionismo",
];

/**
 * Normalize a piece of text so common obfuscations map back to a canonical
 * form: leetspeak digits → letters, punctuation stripped, repeated letters
 * collapsed, and a compact (no-space) form appended so "d r o g a" also
 * matches.
 */
export function normalize(text: string): string {
  const leet: Record<string, string> = {
    "0": "o", "1": "i", "3": "e", "4": "a",
    "5": "s", "7": "t", "@": "a", "$": "s",
    "!": "i", "è": "e", "é": "e", "à": "a",
    "ì": "i", "ò": "o", "ù": "u",
  };
  const lowered = text.toLowerCase();
  let out = "";
  for (const ch of lowered) out += leet[ch] ?? ch;
  // Collapse 3+ repeated chars: drogaaaa -> drogaa (keep double, kill triples)
  out = out.replace(/(.)\1{2,}/g, "$1$1");
  // Strip everything that isn't a letter or whitespace
  out = out.replace(/[^a-z\s]/g, " ");
  // Compact form (no spaces) catches spaced-out words
  const compact = out.replace(/\s+/g, "");
  return `${out} ${compact}`;
}

/**
 * Return the first forbidden term found in `text` (already normalized), or
 * null if the text is clean.
 */
export function findForbiddenWord(text: string): string | null {
  if (!text) return null;
  const n = normalize(text);
  for (const w of BLOCKED_WORDS) {
    if (n.includes(w)) return w;
  }
  return null;
}

/**
 * Convenience: check multiple fields at once. Returns a user-facing Italian
 * error message or null if all fields are clean.
 */
export function moderateFields(fields: Record<string, string | null | undefined>): string | null {
  for (const [, value] of Object.entries(fields)) {
    if (!value) continue;
    const bad = findForbiddenWord(value);
    if (bad) {
      return "Contenuto non consentito: sono vietati riferimenti a droga, armi, violenza o contenuti illegali.";
    }
  }
  return null;
}

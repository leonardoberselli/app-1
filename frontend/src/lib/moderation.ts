// Lightweight content moderation for user-generated text (titles,
// descriptions, custom "Altro" category labels, chat messages).
//
// Strategy:
// 1) Normalize the text: leetspeak digits/symbols → letters, lowercase,
//    strip punctuation, collapse 3+ repeated chars, and "glue back" runs
//    of single-letter tokens ("d r o g a" → "droga").
// 2) Match blocked STEMS (short prefixes) with a word-boundary rule at
//    the START of the stem. This catches obfuscated tails ("drog3",
//    "drog4", "drogaaa") without false positives on unrelated words that
//    just happen to contain the stem in the middle (e.g. "carmine" is
//    NOT flagged for "armi").

const _LEET_MAP: Record<string, string> = {
  "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
  "@": "a", "$": "s", "!": "i",
  "è": "e", "é": "e", "à": "a",
  "ì": "i", "ò": "o", "ù": "u",
};

// Short prefixes / stems. Any word starting with one of these is blocked.
const _BLOCKED_STEMS: string[] = [
  // Droga
  "drog", "drug", "cocain", "eroin", "cannab", "marij", "weed", "ganja",
  "hashish", "metanfet", "methamph", "ecstasy", "mdma", "lsd", "ketam",
  "spacci", "pusher", "stupefac",
  // Armi / violenza
  "arma", "armi", "pistol", "fucil", "kalash",
  "weapon", "guns", "rifle", "knife",
  "esplos", "bomb", "terror", "attentat",
  "uccider", "ammazz", "omicid", "hitman", "murder",
  "stupr", "rape",
  // Sesso illegale / esplicito
  "orgia", "orgie", "orgy", "pedofil", "pedoph", "minoren",
  "prostit", "escort", "puttana", "zoofil",
  "sesso", "porno",
  // Alcol
  "alcol", "alcool", "alcohol", "ubriac",
  // Odio / auto-lesionismo
  "nazism", "nazist", "razzism", "razzist",
  "suicid", "autolesion",
];

/**
 * Turn `text` into a canonical form suitable for stem matching:
 *  - leet chars → letters (digit substitutions)
 *  - lowercase
 *  - collapse 3+ repeated chars ("drogaaaa" → "drogaa")
 *  - strip everything that isn't a letter or a space
 *  - collapse whitespace runs to a single space
 *  - glue runs of 2+ single-letter tokens together ("d r o g a" → "droga")
 */
export function normalize(text: string): string {
  const lowered = text.toLowerCase();
  let out = "";
  for (const ch of lowered) out += _LEET_MAP[ch] ?? ch;
  out = out.replace(/(.)\1{2,}/g, "$1$1");
  out = out.replace(/[^a-z\s]/g, " ");
  out = out.replace(/\s+/g, " ").trim();

  // Glue runs of single-letter tokens: "d r o g a" → "droga", but leave
  // "il cane" untouched ("il" is 2 chars).
  // Repeat until no more collapses happen (safe: string strictly shrinks).
  const singleRun = /(?:^|\s)((?:[a-z]\s+){2,}[a-z])(?=\s|$)/g;
  let prev = "";
  while (prev !== out) {
    prev = out;
    out = out.replace(singleRun, (m) => " " + m.replace(/\s+/g, "") + " ");
    out = out.replace(/\s+/g, " ").trim();
  }
  return out;
}

/**
 * Return the first forbidden stem found in `text` (case-insensitive,
 * word-boundary at stem start), or null if the text is clean.
 */
export function findForbiddenWord(text: string): string | null {
  if (!text) return null;
  const normalized = normalize(text);
  for (const stem of _BLOCKED_STEMS) {
    // \b<stem>  — stem must be at the start of a word in the normalized form
    const re = new RegExp(`\\b${stem}`, "i");
    if (re.test(normalized)) return stem;
  }
  return null;
}

/**
 * Convenience: check multiple fields at once. Returns a user-facing Italian
 * error message or null if all fields are clean.
 */
export function moderateFields(
  fields: Record<string, string | null | undefined>,
): string | null {
  for (const [, value] of Object.entries(fields)) {
    if (!value) continue;
    if (findForbiddenWord(value)) {
      return "Contenuto non consentito: sono vietati riferimenti a droga, armi, violenza, sesso esplicito, alcol o contenuti illegali.";
    }
  }
  return null;
}

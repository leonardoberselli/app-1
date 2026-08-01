// Predefined categories for activities. Italian labels.
export type CategoryDef = {
  id: string;
  label: string;
  emoji: string;
  color: string;
};

export const CATEGORIES: CategoryDef[] = [
  { id: "basket", label: "Basket", emoji: "🏀", color: "#FF8A3D" },
  { id: "calcio", label: "Calcio", emoji: "⚽", color: "#4ADE80" },
  { id: "tennis", label: "Tennis", emoji: "🎾", color: "#A3E635" },
  { id: "biliardo", label: "Biliardo", emoji: "🎱", color: "#3B82F6" },
  { id: "ping_pong", label: "Ping Pong", emoji: "🏓", color: "#F472B6" },
  { id: "discoteca", label: "Discoteca", emoji: "🪩", color: "#A855F7" },
  { id: "bar", label: "Bar", emoji: "🍻", color: "#F59E0B" },
  { id: "volley", label: "Volley", emoji: "🏐", color: "#EF4444" },
  { id: "padel", label: "Padel", emoji: "🥎", color: "#22D3EE" },
  { id: "running", label: "Running", emoji: "🏃", color: "#10B981" },
  { id: "viaggi", label: "Viaggi", emoji: "✈️", color: "#0EA5E9" },
  { id: "altro", label: "Altro", emoji: "🎲", color: "#8B5CF6" },
];

export const CUSTOM_CATEGORY = {
  id: "custom",
  label: "Custom",
  emoji: "✨",
  color: "#FF4747",
};

export function findCategory(id: string) {
  return CATEGORIES.find((c) => c.id === id);
}

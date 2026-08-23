import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";

import { api } from "@/src/lib/api";

const STORAGE_KEY = "@groupup/location_prefs_v1";

export type LocationSource = "gps" | "manual" | null;

export type LocationPrefs = {
  /** Selected radius for the feed distance filter, in km. */
  radiusKm: number;
  /** Cached coordinates last resolved for this device (GPS or manual). */
  lat: number | null;
  lon: number | null;
  /** How coordinates were obtained (or null if unavailable). */
  source: LocationSource;
  /** User-entered reference city (only when source === "manual"). */
  manualCity: string;
  /** Province matched to the manual city (from Nominatim autocomplete). */
  manualProvince: string;
  /** @deprecated kept for backward-compat with older stored payloads. */
  manualStreet: string;
  /** Whether we have shown the initial permission request already. */
  askedOnce: boolean;
};

const DEFAULT_PREFS: LocationPrefs = {
  radiusKm: 30,
  lat: null,
  lon: null,
  source: null,
  manualCity: "",
  manualProvince: "",
  manualStreet: "",
  askedOnce: false,
};

type PermissionStatus = "granted" | "denied" | "undetermined";

type Ctx = {
  prefs: LocationPrefs;
  permission: PermissionStatus;
  canAskAgain: boolean;
  loading: boolean;
  /** Ask the OS for foreground location. Returns whether granted. */
  requestGps: () => Promise<boolean>;
  /** Resolve/set a manual reference city. If `coords` is provided (from the
   *  autocomplete suggestion), it is used directly, otherwise the backend
   *  Nominatim endpoint is called. */
  setManualLocation: (
    city: string,
    coords?: { lat: number; lon: number; province?: string },
  ) => Promise<{ ok: boolean; error?: string }>;
  setRadiusKm: (km: number) => Promise<void>;
  /** Re-fetch current GPS coordinates. */
  refreshGps: () => Promise<void>;
  /** Clear any cached location (keeps radius). */
  clearLocation: () => Promise<void>;
};

const LocationContext = createContext<Ctx | undefined>(undefined);

async function loadPrefs(): Promise<LocationPrefs> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = JSON.parse(raw) as Partial<LocationPrefs>;
    return { ...DEFAULT_PREFS, ...parsed };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

async function savePrefs(p: LocationPrefs): Promise<void> {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    // Ignore storage errors
  }
}

export function LocationProvider({ children }: { children: React.ReactNode }) {
  const [prefs, setPrefs] = useState<LocationPrefs>(DEFAULT_PREFS);
  const [permission, setPermission] = useState<PermissionStatus>("undetermined");
  const [canAskAgain, setCanAskAgain] = useState(true);
  const [loading, setLoading] = useState(true);

  const persist = useCallback(async (next: LocationPrefs) => {
    setPrefs(next);
    await savePrefs(next);
  }, []);

  const refreshGps = useCallback(async () => {
    try {
      const perm = await Location.getForegroundPermissionsAsync();
      setPermission(perm.status as PermissionStatus);
      setCanAskAgain(perm.canAskAgain);
      if (perm.status !== "granted") return;
      const pos = await Location.getLastKnownPositionAsync().catch(() => null)
        || (await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        }).catch(() => null));
      if (!pos) return;
      const next: LocationPrefs = {
        ...prefs,
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        source: "gps",
      };
      await persist(next);
    } catch (e) {
      console.warn("refreshGps failed", e);
    }
  }, [prefs, persist]);

  const requestGps = useCallback(async (): Promise<boolean> => {
    try {
      // Check first: if already granted, just refresh.
      const cur = await Location.getForegroundPermissionsAsync();
      setPermission(cur.status as PermissionStatus);
      setCanAskAgain(cur.canAskAgain);
      let status = cur.status;
      let ask = cur.canAskAgain;
      if (status !== "granted") {
        if (!ask) return false;
        const req = await Location.requestForegroundPermissionsAsync();
        status = req.status;
        ask = req.canAskAgain;
        setPermission(status as PermissionStatus);
        setCanAskAgain(ask);
      }
      // Persist that we asked at least once regardless of outcome
      const askedOnce = true;
      if (status !== "granted") {
        await persist({ ...prefs, askedOnce });
        return false;
      }
      const pos = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      await persist({
        ...prefs,
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        source: "gps",
        askedOnce,
      });
      return true;
    } catch (e) {
      console.warn("requestGps failed", e);
      return false;
    }
  }, [prefs, persist]);

  const setManualLocation = useCallback(
    async (
      city: string,
      coords?: { lat: number; lon: number; province?: string },
    ): Promise<{ ok: boolean; error?: string }> => {
      const c = (city || "").trim();
      if (!c) return { ok: false, error: "Inserisci una città" };
      try {
        let lat: number;
        let lon: number;
        if (coords && Number.isFinite(coords.lat) && Number.isFinite(coords.lon)) {
          lat = coords.lat;
          lon = coords.lon;
        } else {
          const res = await api.geocode(c);
          lat = res.lat;
          lon = res.lon;
        }
        await persist({
          ...prefs,
          lat,
          lon,
          source: "manual",
          manualCity: c,
          manualProvince: coords?.province || "",
          askedOnce: true,
        });
        return { ok: true };
      } catch (e: any) {
        return { ok: false, error: e?.message || "Indirizzo non trovato" };
      }
    },
    [prefs, persist],
  );

  const setRadiusKm = useCallback(
    async (km: number) => {
      const clamped = Math.max(1, Math.min(100, Math.round(km)));
      await persist({ ...prefs, radiusKm: clamped });
    },
    [prefs, persist],
  );

  const clearLocation = useCallback(async () => {
    await persist({
      ...prefs,
      lat: null,
      lon: null,
      source: null,
      manualCity: "",
      manualProvince: "",
      manualStreet: "",
    });
  }, [prefs, persist]);

  // Bootstrap on mount
  useEffect(() => {
    (async () => {
      const p = await loadPrefs();
      setPrefs(p);
      try {
        const perm = await Location.getForegroundPermissionsAsync();
        setPermission(perm.status as PermissionStatus);
        setCanAskAgain(perm.canAskAgain);
      } catch {}
      setLoading(false);
    })();
  }, []);

  return (
    <LocationContext.Provider
      value={{
        prefs,
        permission,
        canAskAgain,
        loading,
        requestGps,
        setManualLocation,
        setRadiusKm,
        refreshGps,
        clearLocation,
      }}
    >
      {children}
    </LocationContext.Provider>
  );
}

export function useLocationPrefs(): Ctx {
  const ctx = useContext(LocationContext);
  if (!ctx) throw new Error("useLocationPrefs must be used within LocationProvider");
  return ctx;
}

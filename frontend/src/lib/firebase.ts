import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { initializeApp, getApps, getApp, FirebaseApp } from "firebase/app";
// eslint-disable-next-line @typescript-eslint/no-unused-vars
import type { Auth } from "firebase/auth";

// Firebase project config for GroupUp.
// These values are safe to expose on the client (they identify the project publicly).
const firebaseConfig = {
  apiKey: "AIzaSyCfHWq1CR3bcuXgn0I44kkgvjHZiOjsY-o",
  authDomain: "grupup1-e23ee.firebaseapp.com",
  projectId: "grupup1-e23ee",
  storageBucket: "grupup1-e23ee.firebasestorage.app",
  messagingSenderId: "297410719787",
  appId: "1:297410719787:android:d09fd6363d117eb2e43a6e",
};

// Web Client ID (OAuth type 3) taken from google-services.json.
// Used by the native Google Sign-In library for Android to obtain an idToken
// exchangeable with Firebase.
export const GOOGLE_WEB_CLIENT_ID =
  "297410719787-duhqift1dpnnrfj2ft91pfibd74r73a7.apps.googleusercontent.com";

// iOS Client ID (from GoogleService-Info.plist).
export const GOOGLE_IOS_CLIENT_ID =
  "297410719787-pvhg23vbe26bhu5bqn1bgg3j7fcoq3eq.apps.googleusercontent.com";

const app: FirebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);

let _auth: any;

if (Platform.OS === "web") {
  // Web: default persistence is IndexedDB / LocalStorage.
  const { getAuth, browserLocalPersistence, setPersistence } = require("firebase/auth");
  _auth = getAuth(app);
  // Best-effort — some environments don't allow indexedDB.
  setPersistence(_auth, browserLocalPersistence).catch(() => {});
} else {
  // React Native: use AsyncStorage persistence.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const rnAuth = require("firebase/auth");
  try {
    _auth = rnAuth.initializeAuth(app, {
      persistence: rnAuth.getReactNativePersistence(AsyncStorage),
    });
  } catch {
    // Already initialized (fast refresh).
    _auth = rnAuth.getAuth(app);
  }
}

export const auth = _auth as Auth;
export { app };

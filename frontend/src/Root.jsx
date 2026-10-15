import { Suspense, lazy } from "react";
import App from "./App.jsx";

// Public share links (/share/<token>) render a read-only dashboard with no
// auth. Everything else is the authenticated app. A share-link visitor never
// needs the app, and an app user rarely opens a share page, so the public
// dashboard is its own chunk.
const PublicDashboard = lazy(() => import("./components/PublicDashboard.jsx"));

export default function Root() {
  const shareMatch = window.location.pathname.match(/^\/share\/([A-Za-z0-9_-]+)/);
  return shareMatch
    ? <Suspense fallback={null}><PublicDashboard token={shareMatch[1]} /></Suspense>
    : <App />;
}

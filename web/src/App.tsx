import { HashRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ComparePage } from "./pages/ComparePage";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { StatsPage } from "./pages/StatsPage";
import { TrainerModal } from "./pages/TrainerModal";
import "./App.css";

function AppNav() {
  const location = useLocation();
  const section = location.pathname.startsWith("/compare")
    ? "compare"
    : location.pathname.startsWith("/stats")
      ? "stats"
      : "leaderboard";
  return (
    <nav className="app-nav">
      <NavLink to="/singles/cursed/none" className={section === "leaderboard" ? "active" : ""}>
        Leaderboard
      </NavLink>
      <NavLink to="/compare" className={section === "compare" ? "active" : ""}>
        Compare
      </NavLink>
      <NavLink to="/stats" className={section === "stats" ? "active" : ""}>
        Stats
      </NavLink>
    </nav>
  );
}

function App() {
  return (
    <HashRouter>
      <AppNav />
      <Routes>
        <Route path="/" element={<Navigate to="/singles/cursed/none" replace />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/:battleType/:curseVariant/:filter" element={<LeaderboardPage />}>
          <Route path=":label" element={<TrainerModal />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default App;

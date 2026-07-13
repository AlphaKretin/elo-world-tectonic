import { HashRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AboutPage } from "./pages/AboutPage";
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
      : location.pathname.startsWith("/about")
        ? "about"
        : "leaderboard";
  return (
    <nav className="app-nav">
      <NavLink to="/about" className="app-brand">
        <img src={`${import.meta.env.BASE_URL}favicon-32x32.png`} alt="" />
        <span className="app-brand-text">
          <span className="app-brand-name">Pokémon Tectonic Elo World</span>
          <span className="app-brand-subtitle">Leaderboard &amp; Analysis</span>
        </span>
      </NavLink>
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
        <Route path="/" element={<Navigate to="/about" replace />} />
        <Route path="/about" element={<AboutPage />} />
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

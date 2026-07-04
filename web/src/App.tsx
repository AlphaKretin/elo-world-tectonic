import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { TrainerModal } from "./pages/TrainerModal";

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/singles/cursed" replace />} />
        <Route path="/:battleType/:curseVariant" element={<LeaderboardPage />}>
          <Route path=":label" element={<TrainerModal />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default App;

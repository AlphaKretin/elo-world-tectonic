import { usePageTitle } from "../hooks/usePageTitle";
import "./AboutPage.css";

export function AboutPage() {
  usePageTitle(
    "About",
    "What Pokémon Tectonic Elo World is, how to read its leaderboards, and the methodology and caveats behind its ratings.",
  );

  return (
    <div className="page about-page">
      <h1>About</h1>

      <section>
        <h2>What is this?</h2>
        <p>
          Pokémon Tectonic Elo World is an independent fan project that ranks every trainer battle from the fangame{" "}
          <a href="https://tectonic-game.com/" target="_blank" rel="noreferrer">
            Pokémon Tectonic
          </a>{" "}
          by fighting them against each other and fitting a rating from the results — the same idea as{" "}
          <a href="https://www.youtube.com/@tom7" target="_blank" rel="noreferrer">
            tom7
          </a>
          's{" "}
          <a href="https://www.youtube.com/watch?v=DpXy041BIlA" target="_blank" rel="noreferrer">
            Elo World
          </a>{" "}
          chess-engine tournament and{" "}
          <a href="https://www.youtube.com/@pimanrules" target="_blank" rel="noreferrer">
            pimanrules
          </a>
          '{" "}
          <a href="https://www.youtube.com/watch?v=8yUPhRJtNJM" target="_blank" rel="noreferrer">
            Pokémon Red
          </a>{" "}
          (
          <a href="https://www.youtube.com/watch?v=247qD1qulSQ" target="_blank" rel="noreferrer">
            redux
          </a>
          ) and{" "}
          <a href="https://www.youtube.com/watch?v=Q6E6OaWb7LQ" target="_blank" rel="noreferrer">
            Crystal
          </a>{" "}
          ranking videos, applied to Tectonic's roster of story encounters instead.
        </p>
        <p>
          Each entry on this site is one specific trainer fight you'd meet playing through the game — say, a
          particular Gym Leader's rematch team — not the cosmetic trainer class (Youngster, Gym Leader, etc.) they're
          dressed as. Two trainers sharing a class are still ranked separately, since it's the actual team and fight
          being compared, not the costume.
        </p>
        <p>
          This site isn't an official part of Pokémon Tectonic or endorsed by its dev team — it's a side project
          that happens to be run by one of that team's developers, kept deliberately separate from the game itself.
        </p>
      </section>

      <section>
        <h2>How the ratings work</h2>
        <p>
          Every trainer fights every other trainer across a round robin of simulated battles, using the game's own
          AI on both sides. Each battle's win/loss/draw result feeds a Bradley-Terry rating fit (the same model
          behind chess Elo) — so a trainer's rating reflects how often they beat opponents who themselves beat other
          opponents, not just a raw win count. Rank is that rating sorted high to low; tier is a coarser letter-grade
          bucketing of the same ratings.
        </p>
      </section>

      <section>
        <h2>Reading the leaderboard</h2>
        <ul>
          <li>
            <strong>Format picker</strong> (Singles/Doubles × Cursed/Uncursed, plus a filter) — Tectonic has an
            optional harder mode where the Tarot Amulet's curses affect gym leaders and story fights. "Cursed" here
            battles trainers with those curses active as rolled; "Uncursed" re-simulates the same trainers with
            curse effects stripped out, so the two are directly comparable tournaments rather than one being a
            filtered subset of the other.
          </li>
          <li>
            <strong>Filters</strong> narrow which battles count toward the rating fit without changing what was
            battled — e.g. excluding cursed match-ups, or restricting to level-70 teams only.
          </li>
          <li>
            <strong>Rating / Tier</strong> — the fitted strength estimate and its letter-grade bucket.
          </li>
          <li>
            <strong>W / L / D, Win%, Avg/Max rounds</strong> — this trainer's raw record and battle length in the
            selected format.
          </li>
        </ul>
        <p>
          <strong>Compare</strong> lines up two formats side by side to see how a trainer's rank/rating shifts
          between them (e.g. cursed vs. uncursed). <strong>Stats</strong> plots any two metrics against each other
          across the whole roster — ratings, win rate, team level, and more.
        </p>
      </section>

      <section>
        <h2>Caveats</h2>
        <ul>
          <li>
            Battles are played by the game's built-in trainer AI, not by humans or a stronger custom bot — ratings
            measure how these teams perform under that AI's decision-making, not the ceiling of what's possible with
            them.
          </li>
          <li>
            Ratings carry real statistical uncertainty, especially for trainers with fewer battles or a smaller
            overlap of shared opponents with the rest of the field; treat close ranks as roughly tied rather than a
            strict ordering.
          </li>
          <li>
            Curses, held items, and team compositions are Tectonic's own game balance, not something this project
            adjusts for — trainer strength here is entirely a function of the team and curses they were assigned.
          </li>
        </ul>
      </section>

      <section>
        <h2>Battle Station</h2>
        <p>
          This website covers the aggregate ratings and leaderboards; <strong>Battle Station</strong> is the
          companion desktop app for going deeper on individual matches — browse the full results set, generate any
          specific pairing as a watchable replay and step through it turn-by-turn, or set up a custom top-16
          elimination bracket. Source and downloads are on{" "}
          <a href="https://github.com/AlphaKretin/elo-world-tectonic" target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </p>
      </section>
    </div>
  );
}

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
          If you&rsquo;re familiar with <a href="https://www.youtube.com/@pimanrules">Pimanrules&rsquo;</a>{" "}
          <a href="https://www.youtube.com/watch?v=Q6E6OaWb7LQ"><em>Elo World</em> series</a> of
          videos, it&rsquo;s that for Pok&eacute;mon Tectonic. If you&rsquo;re
          not, let me explain.
        </p>
        <p>
          I took every NPC Trainer in Pok&eacute;mon Tectonic and simulated a
          round robin tournament, having each of them battle each other.
          Based on their results, I computed an Elo rating and other
          statistics to sort them into a leaderboard, and you can view those
          details here.
        </p>
        <p>
          Pok&eacute;mon Tectonic is a fangame that includes every
          Pok&eacute;mon up through Generation 8, overhauled to ideally all
          have a distinct mechanical niche where they can be viable. Trainer
          battles are more difficult and engaging than the canon games,
          without being as overbearing as something like a Kaizo hack. The
          unique &ldquo;curse&rdquo; mechanic also adds optional special
          conditions to certain boss fights. All of these factors make it
          interesting to see how the trainers measure up.
        </p>
      </section>

      <section>
        <h2>How does it work?</h2>
        <p>
          Since Pok&eacute;mon Tectonic is a Pok&eacute;mon Essentials
          fangame, I was able to modify the Ruby code directly to orchestrate
          battles between NPC Trainers, skip the graphics to speed things up,
          and fix any issues that arose, rather than having to deal with
          emulator savestates and memory edits.
        </p>
        <p>
          For clarity, I am one of the developers on Pok&eacute;mon Tectonic,
          which is how I had enough familiarity with the codebase to make
          these changes. However, this is a personal side project,{" "}
          <em>not</em> officially associated with the game.
        </p>
        <p>
          Rating scores are calculated using the Bradley-Terry model. This is
          the same model underlying Chess Elo, but despite my colloquial use
          of the term it&rsquo;s not technically identical. The main
          difference is that Elo is meant to evolve one game at a time, while
          our model has the entire dataset from the start. The{" "}
          <a href="https://www.youtube.com/watch?v=247qD1qulSQ&t=3029s">
            <em>Pokemon Red Elo World Redux</em> video
          </a>{" "}
          contains a good explanation if you&rsquo;re interested in the
          underlying maths.
        </p>
        <p>
          Note that we see an extreme breadth of ratings in these results,
          from -700 all the way up to almost 3000. This may be unfamiliar if
          you&rsquo;re used to Chess or other competitive games, but it&rsquo;s
          normal and expected for our data set, since we have a huge
          difference in power level between the strongest and weakest.
        </p>
      </section>

      <section>
        <h2>Can I watch the battles?</h2>
        <p>
          You can! While this website covers the aggregate ratings and
          leaderboards,{" "}
          <a href="https://github.com/AlphaKretin/elo-world-tectonic/releases">Battle Station</a> is a companion
          desktop app that lets you browse the full results set, create and
          watch replays of any pairing, and even simulate fantasy Top 16
          brackets.
        </p>
      </section>

      <section>
        <h2>What are all these different formats?</h2>
        <p>
          Because Pok&eacute;mon Tectonic has a variety of factors that can
          affect a trainer&rsquo;s performance, I couldn&rsquo;t just run one
          tournament. First and foremost, a decent number of notable trainers
          have teams built for Double Battles, so ranking only by Singles
          performance would be unfair. Technically there are a few trainers
          who also fight in Triples, but the number is far fewer and it
          wasn&rsquo;t worth the extra simulation &mdash; especially not for
          Skyler.
        </p>
        <p>
          In any case, the point is that I simulated everything in both
          Singles and Doubles formats. If you&rsquo;re curious to see who
          does better or worse between formats, that&rsquo;s what the Compare
          tab is for.
        </p>
        <p>
          The next part of the format selector is &ldquo;Cursed&rdquo; or
          &ldquo;Uncursed&rdquo;. As mentioned above, certain boss fights have
          special Curse mechanics that swing the fight in their favour, e.g.
          putting the opponent under a permanent Torment effect. The
          &ldquo;Cursed&rdquo; setting has these in full effect to match the
          player&rsquo;s experience. However, these hard mode fights often
          also have a stronger team, separate from the unfair effects, so the
          &ldquo;Uncursed&rdquo; setting allows you to see how these enhanced
          teams do in a fair fight. Note that sometimes there is no team
          enhancement with the curse, in which case the fight becomes
          identical to its base version and doesn&rsquo;t get a separate
          ranking in Uncursed format.
        </p>
        <p>
          An important note about ratings: when comparing, e.g., Doubles and
          Singles, the exact score isn&rsquo;t directly comparable, because
          the ratings were computed from completely different sets of
          battles. However, with Cursed vs Uncursed, any fight that
          didn&rsquo;t involve a curse is unchanged, and the ratings models
          were specifically fit on that overlap with the extra battles
          tacked on top, so their ratings <em>are</em> directly comparable.
        </p>
        <p>
          Finally, there are various arbitrary filters. If you&rsquo;d rather
          not worry about this curse nonsense at all, you can exclude them
          from the pool entirely. You can also filter for Level 70
          (Tectonic&rsquo;s maximum level) to see the best of the best, or
          check out who amongst the Developer cameos is strongest. Note that
          these don&rsquo;t just filter down the existing results, the
          ratings are recomputed with this smaller pool of competition.
        </p>
      </section>

      <section>
        <h2>Are there any limitations to be aware of?</h2>
        <p>
          A few. For one, RNG is obviously going to be a factor in the
          simulated fights. The battles were simulated with a consistent
          seed so that the results were deterministic, but a close fight
          still could have gone differently with a different seed. Rather
          than simulate many battles between each trainer pair, we hope that
          things will average out fairly over the entire set of opponents.
        </p>
        <p>
          The most notable source of RNG is speed ties. For the most part, I
          made sure it didn&rsquo;t matter which trainer was in which slot,
          so that unlike Pimanrules I didn&rsquo;t have to do a double round
          robin tournament, halving the effort. The only remaining asymmetry
          is how random numbers are assigned when breaking speed ties. This
          doesn&rsquo;t give any one side a specific, consistent advantage,
          but it does mean that swapping the sides could produce a different
          result. I made sure the sides of the battle were assigned by a
          fair and consistent method so that this didn&rsquo;t skew anyone&rsquo;s
          results.
        </p>
        <p>
          Another thing to be aware of is that every trainer in the dataset
          had to fight on their own, even if they&rsquo;d usually fight with
          a partner. This unavoidably disadvantages those trainers, but it is
          an accurate assessment to show that they&rsquo;re weaker on their
          own, and doing it any other way would have introduced significant
          complication.
        </p>
        <p>
          Finally, it&rsquo;s worth noting that all of the simulations were
          performed on a dev build of the game after version 3.4&rsquo;s
          release, but before content for any future update is finalised.
          This means it doesn&rsquo;t quite match any official release, but
          porting the simulation framework to another build would have been
          a massive headache. The main symptom of this is trainers from the
          Alloyed Thicket dungeon being levelled down from late-game to
          mid-game.
        </p>
      </section>
    </div>
  );
}

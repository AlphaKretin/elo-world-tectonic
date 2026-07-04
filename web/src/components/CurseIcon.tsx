import { RemoteSprite } from "./RemoteSprite";

interface Props {
  title: string;
}

// Shared curse-roll disambiguation icon -- used by both LeaderboardTable
// and ComparePage so a trainer known to be curse-rolled for a given format
// is marked the same way everywhere.
export function CurseIcon({ title }: Props) {
  return (
    <RemoteSprite kind="Items" name="TAROTAMULET_ACTIVE" className="trainer-curse-icon" alt="Cursed" title={title} />
  );
}

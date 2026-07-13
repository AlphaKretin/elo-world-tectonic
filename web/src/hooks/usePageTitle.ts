import { useEffect } from "react";

const SITE_NAME = "Pokémon Tectonic Elo World";
const DEFAULT_DESCRIPTION =
  "An independent fan project ranking Pokémon Tectonic trainers by Elo tournament results, with leaderboards, stats, and replay analysis.";

function descriptionTag(): HTMLMetaElement {
  let tag = document.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (!tag) {
    tag = document.createElement("meta");
    tag.name = "description";
    document.head.appendChild(tag);
  }
  return tag;
}

export function usePageTitle(page: string, description?: string) {
  useEffect(() => {
    // Restores whatever was set before this effect ran (rather than a
    // hardcoded site default) so a nested title -- e.g. a trainer modal
    // opened from within the Compare page -- reverts to the parent page's
    // title/description on close, not the bare site name.
    const prevTitle = document.title;
    const tag = descriptionTag();
    const prevDescription = tag.content;

    document.title = `${page} | ${SITE_NAME}`;
    tag.content = description ?? DEFAULT_DESCRIPTION;
    return () => {
      document.title = prevTitle;
      descriptionTag().content = prevDescription;
    };
  }, [page, description]);
}

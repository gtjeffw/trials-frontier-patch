# Ghost bundles (`trials-frontier-bundle`, format 1)

A bundle is one rider's best times and ghost replays, shared as a public GitHub repository so that other players can
race them in a patched game and so that the times survive. `scripts/ghost_bundle.py` makes (`export`), checks
(`check`), publishes (`publish`), finds (`search`) and imports (`import`) them.

## Finding bundles

Published bundles carry the GitHub topic `trials-frontier-bundle` (also `trials-frontier`,
`trials-frontier-ghosts`, `game-preservation`) and are named `trials-frontier-ghosts-<rider>`:

```
gh search repos --topic trials-frontier-bundle
```

That search is the index for now; a future collecting service can start from it.

## Layout

```
trials-frontier-bundle.json        the manifest (below)
ghosts/<leaderboard>.bin           the rider's ghosts, exactly as the game stores them
others/<HASH>/<leaderboard>.bin    optional: other riders' ghosts the game downloaded as opponents
avatar.png                         optional: the rider's picture (146x146)
README.md, LICENSE                 for people; the manifest is the source of truth
```

## Manifest

```json
{
 "format": "trials-frontier-bundle", "format_version": 1,
 "game": {"name": "Trials Frontier", "version": "7.9.0", "platform": "iOS"},
 "created": "2026-10-10T12:00:00Z",
 "tool": "https://github.com/gtjeffw/trials-frontier-patch scripts/ghost_bundle.py",
 "license": "CC0-1.0",
 "rider": {"name": "…", "game_hash": "1A2B3C4D", "profile_sha256": "…64 hex…",
           "avatar": {"file": "avatar.png", "sha256": "…"}},
 "publisher": {"github": "<login>", "statement": "The publisher states that the rider is their own …"},
 "results": [{"leaderboard": 65537, "track": 1, "faults": 0, "time_ms": 14932, "bike": 15,
              "source": "save", "track_name": "…"}],
 "ghosts":  [{"leaderboard": 65537, "track": 1, "time_ms": 14932, "bike": 15, "file": "ghosts/65537.bin",
              "sha256": "…", "source": "save", "track_name": "…"}],
 "others":  [{"game_hash": "5E6F7A8B", "name": "…", "ghosts": [ … as above, "source": "downloaded-opponent" … ]}]
}
```

- **others**: only with `export --include-others` (by hash, no names) or `--include-others-with-names` (adds the
  in-game names the publisher's save keeps for some opponents; usernames are pseudonymous, but whether sharing them
  is acceptable is the publisher's call, and `publish` lists them before asking for agreement).

- **leaderboard**: the game's leaderboard id: track id in the low 16 bits, bike class in the high bits
  (`track | 0x10000 << (class - 1)`); event and weekly tracks have their own ids. `track` = `leaderboard & 0xFFFF`.
  `track_name` is optional (from the publisher's copy of the game).
- **time_ms / faults / bike**: as the game records them; a ghost's `time_ms` must equal the drive time inside the
  ghost file (16-byte header, then zlib; version 3 bodies start with u32 bike, u32 drive time).
- **source**: `save` (in the game's save when exported: the years of online play, possibly offline play since),
  `local-services` (played later in a patched game with local services), `downloaded-opponent`.
- **Rider identity**: never the profile id itself. Profile ids are 128-bit UUIDs: Ubisoft's, or for a player who
  was never on Ubisoft a random version-4 UUID the local server makes up on first start (kept in the store as
  `new_player_profile`; the game stores it in its save). `profile_sha256` = sha256 of `"trials-frontier-profile:"
  + profile id` is the rider's identity: different players never share one, and anyone who already knows a
  profile id can recognise it. `game_hash` = the game's 32-bit `mt::String::getHashCode` of the profile id; the
  game names downloaded opponents' files after it (`robot_ghost-<HASH>-<lb>.robot`), so it is all we know of most
  opponents. With 32 bits, two riders sharing a hash become likely at tens of thousands of riders, so the hash is
  only a *link*: consolidation keys a bundle's own rider by `profile_sha256`, and attaches hash-only opponent ghosts
  to it only when exactly one claimed rider has that hash; servers recognise the player by `profile_sha256`
  (a stranger with the player's hash still shows) and merge a layer rider with a downloaded opponent of the same
  hash only when no other layer rider has it.
- **Who is who**: `rider` is the publisher's own rider: the profile the export was made from (the save's own name,
  id hashes, best times and ghosts). `publisher.github` is the GitHub account that published it, and
  `publisher.statement` says, inside the signed manifest, that the rider is theirs. Everything under `others` is
  explicitly *not* the publisher's: other riders' ghosts their game downloaded.
- **Proof of the publisher** (made by `publish`): the files are committed through GitHub's API, so GitHub signs
  every commit for the account that made it (committer `web-flow`, shown as Verified). A bundle is its publisher's
  when every commit in its repository is GitHub-signed and authored by the account `publisher.github` names
  (`ghost_bundle.py verify <owner/repo>`, and `community.py sync` before using a bundle). Nothing to keep or lose:
  no key on the publisher's machine; the signatures live in the commits, so copies of the repository keep them.
- **Claims**: a bundle proves that a GitHub account published *a statement* that a rider is theirs, and when (the
  signed commits); it cannot prove ownership of the Ubisoft account (Ubisoft has purged many). A future fan
  server can combine: the GitHub-signed commits (who), the earliest publication (when), `profile_sha256` (the claimant had a
  save with that profile id; they can show the save privately to the server), and the same rider across several
  devices or bundles. Conflicting claims to one rider are for such a server to resolve.

## Licences: check every bundle

Each bundle carries its own licence, chosen by its publisher (`license` in the manifest, and its `LICENSE` file):
today `CC0-1.0` (public domain dedication, the default) or `CC-BY-4.0` (credit required); future versions of the
tools may allow others. The optional 2019 world records are MIT (their copyright notice must travel with copies).

- **Playing:** using bundles in your own patched game is what they are published for.
- **Republishing, passing on a layer or an app with one built in, or serving the data publicly** (a website, a
  fan server, an archive): check and honour the licence of **every** source, e.g. credit CC-BY publishers and
  keep the MIT notice. `community.py build` prints a licence summary and writes `NOTICE.md` into the layer (each
  source, its publisher, licence, link and commit, plus licence texts that must travel); `community.json` records
  the licence of each source, and every result and ghost names the source it came from.
- **Publishing your own bundle:** `publish` explains the licence you grant (CC0: anyone may use it for any purpose
  without credit, irrevocably) and asks you to confirm it, that the rider is your own, how the data is expected to
  be used (patched games, record-tracking sites, archives, fan servers; other uses cannot be foreseen), that it is
  public and lasting, and, with `others`, that you take responsibility for sharing them (names need a separate
  "share names" confirmation).

## Rules for readers

Bundles are untrusted input. `check` (also run by `community.py sync` and `build`) refuses anything unexpected: unknown format version,
wrong types or ranges, file names outside the patterns above, symlinks, files over 2 MB, sha256 mismatches, and
ghosts whose drive time differs from the manifest. New optional keys may be added within format 1; anything
incompatible gets a new `format_version`.

## Updates and redundancy

- **Publishers update** with `ghost_bundle.py update <bundle>`: the same export options again (kept in the bundle
  folder's `.export.json`, never published), merged with what the bundle already had (best result and fastest
  ghost per leaderboard, so an update never loses anything), a summary of new and better times, agreement, a new
  signed commit pushed to the same repository. `--documents <dir>` takes this update from another copy of the same
  profile: PlayCover's data, or an iPhone/iPad's Documents pulled with `scripts/ios_device.py pull-data` (iOS 17+)
  or copied with Finder (file-sharing build). A different profile is refused. Readers get updates with their next
  `community.py update`.
- **Nothing is re-shared by accident.** Export takes the rider's own times and ghosts only from the save and the
  player's own entries in the local store; the community layer is never written into that store. `others` holds
  only opponent files the *original online game* downloaded: once the local server runs, the game also saves the
  robot opponents it serves (which may come from other people's bundles), so with a store only the files the
  store imported are exported, and the store never imports a served opponent (see the local server's notes:
  made-up ids are recognised by their hash, layer ghosts by hash, track and time).
- **Bounded growth.** Every bundle has at most one ghost per rider and leaderboard, and consolidation keeps one
  (the fastest) per rider and leaderboard over all sources, so many bundles carrying the same opponent cost
  download size only, never duplicates in the game.

## Community layer (what the game reads)

`scripts/community.py` keeps a list of sources (defaults in `community/sources.json`: the patch author's bundle,
and the 2019 world records from dutscher/trialstrackmap, pinned commit and sha256, on by default; plus
your own additions), fetches them into a cache (`sync`: only a newer copy that passes every check replaces the
cached one; failures keep the last good copy), and `build`s a layer from scratch, so revisions and removals in a
source show up:

```
community.json   {"format": "trials-frontier-community", "format_version": 1, "sources": [...], "conflicts": [...],
                  "riders": {<rider id>: {"name", "game_hash", "source"}},
                  "results": {"track<leaderboard>": {<rider id>: <result as in store.json>}},
                  "ghosts": {<content id>: {"profile", "track_id", "source", "metadata"}}}
ghosts/<content id>.bin, avatars/<rider id>.png
```

Rider ids: a bundle's own rider `uuid5(URL, "trials-frontier-rider:" + profile_sha256)`, riders known only by hash
the server's own id for them (`uuid5(URL, "trials-frontier-robot:" + hash)`), world-record riders
`uuid5(URL, "trialstrackmap-rider:" + name)`; content ids start at 1000000000. When one profile is claimed by
several bundles: verified publishers first, then the **first published** wins, by GitHub's own creation time of the
repository (recorded at sync; the publisher cannot set it, unlike the manifest's `created`). Further bundles of
the same rider by the winning account are merged (best per leaderboard); claims by other accounts are ignored and
listed in `conflicts`, as are hashes shared by different claimed riders. Copying someone's published bundle under
another account therefore never wins; a rider who never publishes could be claimed first by someone who knows
their profile id (old saves hold some opponents' ids), which only evidence such as the player's own save, checked
by a future server, could settle. Names from `others` only fill in riders nobody claimed.

A third source type, `leaderboard-cache`, is a player's copy of the game's friends leaderboards
(`Library/Caches/lbstorage.bin`, or its `scripts/lbcache.py export`; `community.py add <file>`). `sync` checks it and
keeps only the export (game hash and profile sha256 instead of profile ids, best time per leaderboard; names when
read from the cache file itself, while a shared export has them only if made with `--with-names`). In
`build` each of its riders joins the bundle that claims the same profile sha256, else the rider id of its game hash
(the one hash-only opponent ghosts get), naming it if it has only a placeholder; its results count best-only like
any other. No ghosts come from it.

`install` copies the layer to `Documents/LocalServices/community` (game closed); `build.py --community` builds one
into the app (used when the data has none: iPhone/iPad). Both servers overlay it when the store loads: riders merge
with the store's own (by id, else by the game hash of a named opponent's real profile id), a layer result shows
only where it beats the stored one, the player's own rider is skipped (its avatar is used), and nothing of the
layer is ever written to `store.json` (tests/test_parity.py checks this).

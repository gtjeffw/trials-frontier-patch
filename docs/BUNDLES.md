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
trials-frontier-bundle.json.sig    SSH signature of the manifest by the publisher (namespace trials-frontier-bundle)
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
- **Rider identity**: never the profile id itself. `game_hash` = the game's `mt::String::getHashCode` of the
  profile id as 8 hex digits; the game names downloaded opponents' files after it (`robot_ghost-<HASH>-<lb>.robot`),
  so bundles and the opponents in everyone's saves can be matched. It is only 32 bits, so collisions are possible:
  `profile_sha256` = sha256 of `"trials-frontier-profile:" + profile id` settles them, and lets anyone who
  already knows a profile id (from a save, or a future service) recognise it.
- **Who is who**: `rider` is the publisher's own rider: the profile the export was made from (the save's own name,
  id hashes, best times and ghosts). `publisher.github` is the GitHub account that published it, and
  `publisher.statement` says, inside the signed manifest, that the rider is theirs. Everything under `others` is
  explicitly *not* the publisher's: other riders' ghosts their game downloaded.
- **Signature** (always made by `publish`): the manifest, which lists the sha256 of every file, signed with an SSH
  key of the publisher's GitHub account; `check --verify` checks it against that account's public keys
  (`api.github.com/users/<login>/keys` and `/ssh_signing_keys`). `publish` uses a key of yours that is already on
  GitHub, or offers to create a signing-only key (`~/.ssh/trials_frontier_bundle_ed25519`) and add it, and refuses
  to publish a signature that does not verify.
- **Claims**: a signed bundle proves that a GitHub account published *a statement* that a rider is theirs, and
  when (git history); it cannot prove ownership of the Ubisoft account (Ubisoft has purged many). A future fan
  server can combine: the signature (who), the earliest publication (when), `profile_sha256` (the claimant had a
  save with that profile id; they can show the save privately to the server), and the same rider across several
  devices or bundles. Conflicting claims to one rider are for such a server to resolve.

## Rules for readers

Bundles are untrusted input. `check` (also run by `import`) refuses anything unexpected: unknown format version,
wrong types or ranges, file names outside the patterns above, symlinks, files over 2 MB, sha256 mismatches, and
ghosts whose drive time differs from the manifest. New optional keys may be added within format 1; anything
incompatible gets a new `format_version`.

## Import

`import` adds the rider (and any `others`) to the patched game's store: riders are keyed by `game_hash`, so a
downloaded opponent "Rider 1A2B3C4D" gets its name and further ghosts from the rider's own bundle; best times only
improve; one ghost per rider and leaderboard (the faster one). Your own bundle adds nothing to your own game.

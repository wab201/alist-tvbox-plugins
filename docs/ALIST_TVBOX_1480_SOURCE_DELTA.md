# AList-TVBox 1.48.0 source delta evidence

## Pinned source

- Base: `1.47.1` / `05397d10cd1b8085670a628eb56cb94182fa885e`
- Target: `1.48.0` / `8f01c0f7521c172c439b31a89731764346f15f63`
- Range: `1.47.1..1.48.0`
- Commits: `7`
- Changed files: `34`
- Exact checkout: `D:\自写爬虫\work\alist_tvbox_latest_1.48.0_20260816_rest_git`
- Source archive: `D:\自写爬虫\work\alist_tvbox_1.48.0_8f01c0f.zip`
- Archive SHA256: `21740023DAE200ACF35A7465D5BC18C062187FB697C6A1498AC50222BDF4D4F8`

The checkout was reconstructed from GitHub REST tree/blob data after Git smart HTTP reset repeatedly. All seven added commit trees were checked with `missing=0`; the final checkout is clean and `git fsck --connectivity-only` succeeds. Intermediate commit blobs must be fetched by `(commit, path)`, never substituted with the final tag's same-path bytes.

## Release scope

The exact 34-file delta adds live danmaku support for Huya, Douyu, Bilibili and Douyin, adds persisted rendering configuration, updates the live UI, and repairs Kuaishou playback session handling. It also replaces `spring.jar` and its declared MD5.

This is source evidence only. It does not claim that live danmaku or Kuaishou playback was exercised on a deployed server, MuMu, FongMi, or a real TV device.

## Compatibility boundary

The following Git blobs are identical in `1.47.1` and `1.48.0`:

| Contract owner | Git blob |
| --- | --- |
| `src/main/resources/static/Atvp.py` | `9d47b50a6160a4301b37865a14f212e77165f84f` |
| `History.java` | `71aa330238387555a72bd19999a3e72f05b11b2e` |
| `PlaybackSyncInput.java` | `e4aaaca32316d7a3cc4aca9c009924bae7bac63c` |
| `PlaybackSyncService.java` | `ca7badd7a49eea8cc1cb84b1af4552eec9ee88c3` |

Therefore the raw plugin loader, History DTO conversion, playback synchronization input and service-level resume contract did not change at source level. This does not replace the mandatory V80 ATVP/FongMi dual-runtime gates.

## Spring identity

- Git blob: `6d144e3b69ddad8606e7518a21ead7a630bb9001`
- Bytes: `386120`
- SHA256: `FF4CED5C99786B0AFD8D2BFE44E78D6299647E59F7D23886B6846E34F0619E96`
- MD5: `fe356c2873db42e210fdc1866a2cfb06`
- `classes.dex` bytes: `1363108`
- `classes.dex` SHA256: `338BC29B032149AA76E3329825945A6CB9077C1DA58D321539A9755481CEB889`

The JAR still contains the pinned `PyProxy`, `playerContent`, `PlaybackSyncer`, `atvp_resume:`, `groupIndex`, `sourceIndex`, `subgroupIndex`, and `subgroupName` markers.

## Verifier boundary

`tools/verify_alist_tvbox_1480_contract.py` inherits the complete `1.47.1` verifier. The inherited verifier may fail only its eight release/JAR identity checks. Its `ok`, failed `checks`, and declared `failures` must be structurally valid and exactly consistent; duplicate or undeclared failures are rejected. Any additional inherited failure is a compatibility regression and stops the gate.

The `1.48.0` verifier additionally requires:

- exact tag, commit, clean worktree and 34-file delta;
- exact release-note scope;
- unchanged ATVP/History/playback blobs;
- exact `spring.jar`, MD5 and `classes.dex` identities;
- preserved resume markers;
- bounded danmaku configuration, shared/tokenized routes, four platform clients and protocol-test source;
- Kuaishou session-cookie/device registration source markers.

## Stop conditions

- Any pinned tag, commit, changed-file set, blob, JAR or DEX identity differs.
- The inherited `1.47.1` verifier reports anything outside the eight expected version/JAR failures.
- Any ATVP, History or playback source blob changes relative to `1.47.1`.
- Verification needs credentials, production writes, deployment, browser automation, MuMu, or a live media request.

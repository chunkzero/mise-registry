# mise-registry

Release index for [mise-chunkzero](https://github.com/chunkzero/mise-chunkzero). Each tool has a file in `tools/`
listing every published release, oldest to newest, with a download URL and sha256 per platform, plus `channels` that
point at the newest `latest`, `beta` and `nightly` releases.

Release workflows add entries through `chunkzero/release-tools/mise-registry`, which opens an auto-merging pull request.
Validation rejects changes to published entries and downloads every new archive to check its sha256.

```sh
python3 scripts/registry.py add chunk entry.json  # register a release and move its channel
python3 scripts/registry.py check --base origin/main
```

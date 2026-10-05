import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import registry

NIGHTLY = "0.1.0-nightly.20261004062300.ge282f11816cd"
LATER_NIGHTLY = "0.1.0-nightly.20261005062300.g0123456789ab"


def entry(version):
    return {
        "version": version,
        "tag": f"v{version}",
        "assets": {"linux-x64": {
            "url": f"https://github.com/chunkzero/chunk/releases/download/v{version}/chunk-{version}-linux-x64.tar.gz",
            "sha256": "a" * 64,
        }},
    }


class RegistryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tools = Path(temporary.name)
        (tools / "chunk.json").write_text(json.dumps({"repository": "chunkzero/chunk", "channels": {}, "versions": []}))
        patcher = mock.patch.object(registry, "TOOLS", tools)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_moves_each_channel_to_its_newest_version(self):
        for version in (LATER_NIGHTLY, NIGHTLY, "0.1.0-beta.1", "0.1.0"):
            registry.add("chunk", entry(version))
        loaded = registry.load("chunk")
        self.assertEqual(loaded["channels"], {"nightly": LATER_NIGHTLY, "beta": "0.1.0-beta.1", "latest": "0.1.0"})
        self.assertEqual([item["version"] for item in loaded["versions"]],
                         ["0.1.0-beta.1", NIGHTLY, LATER_NIGHTLY, "0.1.0"])

    def test_re_adding_is_a_no_op_but_changing_is_rejected(self):
        registry.add("chunk", entry("0.1.0"))
        registry.add("chunk", entry("0.1.0"))
        changed = entry("0.1.0")
        changed["assets"]["linux-x64"]["sha256"] = "b" * 64
        with self.assertRaises(SystemExit):
            registry.add("chunk", changed)

    def test_rejects_urls_outside_the_tools_release(self):
        wrong = entry("0.1.0")
        wrong["assets"]["linux-x64"]["url"] = "https://example.com/chunk.tar.gz"
        with self.assertRaises(SystemExit):
            registry.add("chunk", wrong)

    def test_rejects_unknown_version_formats(self):
        with self.assertRaises(SystemExit):
            registry.add("chunk", entry("0.1.0-nightly.20261004.ge282f11816cd"))


if __name__ == "__main__":
    unittest.main()

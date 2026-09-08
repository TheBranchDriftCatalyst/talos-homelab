#!/usr/bin/env python3
"""Exercise the deployed Bluetooth prerequisite gate without a radio or cluster.

Run: python3 scripts/security/test-bt-agent-preflight.py
Requires PyYAML. These tests do not assert that the BLE scanner itself works.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "applications/bt-radar/base/40-bt-agent.yaml"
POD = yaml.safe_load(MANIFEST.read_text())["spec"]["template"]["spec"]
GATE = POD["initContainers"][0]


class BluetoothPrerequisiteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sysfs = Path(self.directory.name)

    def start_gate(self):
        process = subprocess.Popen(
            GATE["command"],
            env={**os.environ, "SYSFS_ROOT": str(self.sysfs), "POLL_SECONDS": "0.05"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.addCleanup(self.stop_gate, process)
        return process

    @staticmethod
    def stop_gate(process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=3)

    def assert_waiting(self, process, reason):
        with self.assertRaises(subprocess.TimeoutExpired) as captured:
            process.communicate(timeout=0.2)
        self.assertIn(reason.encode(), captured.exception.output)
        self.assertIsNone(process.poll(), "missing hardware must not complete or crash the gate")

    def test_missing_subsystem_waits_without_starting_scanner(self):
        self.assert_waiting(self.start_gate(), "host subsystem absent")

    def test_empty_subsystem_waits_for_adapter(self):
        (self.sysfs / "class/bluetooth").mkdir(parents=True)
        self.assert_waiting(self.start_gate(), "subsystem present but no HCI adapter")

    def test_detects_adapter_appearing_after_start(self):
        process = self.start_gate()
        self.assert_waiting(process, "host subsystem absent")
        (self.sysfs / "class/bluetooth/hci0").mkdir(parents=True)
        output, _ = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn("adapter hci0 is present", output)

    def test_resolves_real_sysfs_style_adapter_symlink(self):
        (self.sysfs / "class/bluetooth").mkdir(parents=True)
        (self.sysfs / "devices/radio/hci1").mkdir(parents=True)
        (self.sysfs / "class/bluetooth/hci1").symlink_to("../../devices/radio/hci1")
        process = self.start_gate()
        output, _ = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn("adapter hci1 is present", output)

    def test_dangling_adapter_symlink_does_not_pass(self):
        (self.sysfs / "class/bluetooth").mkdir(parents=True)
        (self.sysfs / "class/bluetooth/hci0").symlink_to("../../devices/missing")
        self.assert_waiting(self.start_gate(), "subsystem present but no HCI adapter")

    def test_gate_has_readonly_host_view_and_no_privileged_access(self):
        self.assertFalse(POD["automountServiceAccountToken"])
        self.assertEqual(GATE["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertTrue(GATE["securityContext"]["runAsNonRoot"])
        self.assertFalse(GATE["securityContext"]["allowPrivilegeEscalation"])
        self.assertNotIn("envFrom", GATE)
        self.assertNotIn("privileged", GATE["securityContext"])
        self.assertEqual(GATE["volumeMounts"], [
            {"name": "host-sys", "mountPath": "/host/sys", "readOnly": True}
        ])
        self.assertEqual(POD["volumes"], [
            {"name": "host-sys", "hostPath": {"path": "/sys", "type": "Directory"}}
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)

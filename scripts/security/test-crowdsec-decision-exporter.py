#!/usr/bin/env python3
"""Offline contract checks for the read-only decision inventory."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('exporter', ROOT / 'infrastructure/base/crowdsec/decision-exporter/exporter.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def decision(id_=1, **extra):
    return {'id': id_, 'origin': 'crowdsec', 'duration': '1h2m3.5s', 'value': '198.51.100.42',
            'scope': 'Ip', 'type': 'ban', 'scenario': 'homelab/test', **extra}


class InventoryTest(unittest.TestCase):
    def test_duration_and_expiry(self):
        self.assertEqual(exporter.inventory([decision()], 100)['1']['expires'], 3823.5)
        with self.assertRaises(ValueError):
            exporter.seconds('1hgarbage')

    def test_community_simulated_expired_are_excluded(self):
        payload = [decision(1, origin='CAPI'), decision(2, simulated=True),
                   decision(3, duration='-1s'), decision(4, duration='0s'), decision(5)]
        self.assertEqual(list(exporter.inventory(payload, 100)), ['5'])

    def test_null_is_successful_empty_inventory(self):
        self.assertIn('crowdsec_local_decisions_count 0', exporter.render(exporter.inventory(None, 100), 100))

    def test_cap_and_label_escaping(self):
        rows = exporter.inventory([decision(i, scenario='quote"\nslash\\') for i in range(1002)], 100)
        result = exporter.render(rows, 100)
        self.assertEqual(result.count('crowdsec_local_decision_expires_timestamp_seconds{'), 1000)
        self.assertIn('crowdsec_local_decisions_omitted 2', result)
        self.assertIn('quote\\"\\nslash\\\\', result)

    def test_failure_discards_stale_metrics(self):
        state = exporter.Inventory()
        state.metrics = exporter.render(exporter.inventory([decision()], 100), 100)
        with patch.dict('os.environ', {'API_KEY_FILE': '/not/a/real/key'}):
            state.refresh()
        self.assertEqual(state.metrics, 'crowdsec_decision_inventory_success 0\n')


if __name__ == '__main__':
    unittest.main()

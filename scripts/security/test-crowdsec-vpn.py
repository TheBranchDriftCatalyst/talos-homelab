#!/usr/bin/env python3
"""Regression: cscli bundles unrelated CAPI decisions inside returned alerts."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('vpn', Path(__file__).with_name('check-crowdsec-vpn.py'))
vpn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpn)


class DecisionMatchTest(unittest.TestCase):
    def test_unrelated_bundled_ip_is_not_a_preexisting_ban(self):
        self.assertFalse(vpn.decision_applies({'value': '198.51.100.2', 'duration': '1h'}, '198.51.100.1'))

    def test_matching_ip_and_range_are_detected(self):
        for value in ('198.51.100.1', '198.51.100.0/24'):
            self.assertTrue(vpn.decision_applies({'value': value, 'duration': '1h'}, '198.51.100.1'))

    def test_simulated_and_expired_decisions_are_not_enforced(self):
        for extra in ({'simulated': True}, {'duration': '-1s'}, {'duration': '0s'}):
            self.assertFalse(vpn.decision_applies({'value': '198.51.100.1', 'duration': '1h', **extra}, '198.51.100.1'))


if __name__ == '__main__':
    unittest.main()

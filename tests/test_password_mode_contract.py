"""Static contract for the intentionally simple personal password mode."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PasswordModeContractTests(unittest.TestCase):
    def test_sshd_fragment_forces_all_project_rpc_without_a_shell(self) -> None:
        config = (ROOT / "deploy/ssh/sshd_config.d/research-memory.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("AuthenticationMethods password", config)
        self.assertIn("PasswordAuthentication yes", config)
        self.assertIn("PubkeyAuthentication no", config)
        self.assertIn("--allow-all-projects --permission write", config)
        self.assertIn("PermitTTY no", config)
        self.assertIn("AllowTcpForwarding no", config)


if __name__ == "__main__":
    unittest.main()

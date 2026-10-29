"""The outbound secret filter: code ABOUT keys passes, key VALUES are refused. No network.

Standing ruling 2026-10-27 ("fix all three"): a cold review of Dispatch was refused on identifiers
such as `api_key = self._api_key()` and `api_key: str`. Both directions are pinned here.
"""
import pathlib
import sys
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import consult  # noqa: E402

# Built at run time so this file itself never carries a scannable literal key.
AWS = "AKIA" + "QX7TZ2LMB4KPW9RD"
GHP = "ghp_" + "a8Zq3LmN0pR7tV2xW5yB9cD4eF6gH1jK2sQ1"
SK = "sk-" + "proj-" + "Q8vX2mN7pL4kR9tB3zW6yC1dF5gH0jS"
SKANT = "sk-" + "ant-api03-" + "Zr4Xk9Qm2Lp7Vb3Nt8Wc5Yd1Fg6Hj0Ks"
SLACK = "xox" + "b-1234567890-0987654321-Ab3dEf6hIj9kLm2nOp5q"
GOOG = "AIza" + "SyD3x9Kq2Lm7Np4Rt8Vw1Yz5Bc0Fg6Hj2Ks"
HEX = "9f3a7c2e8b1d" + "4f6a0c5e9b2d7f1a3c8e"
B64 = "Zm9vYmFyOTg3" + "NjU0MzIxcXdlcnR5dWlvcGFz"

PASS = [
    "api_key = self._api_key()",
    "def connect(api_key: str, timeout: int = 30):",
    "    api_key: str",
    "api_key = os.environ['OPENAI_API_KEY']",
    'api_key = os.environ.get("ANTHROPIC_API_KEY")',
    "secret_key = settings.SECRET_KEY",
    "access_token = resp.json()['access_token']",
    "password = getpass.getpass()",
    "password: Optional[str] = None",
    "api_key=api_key,",
    "self.api_key = api_key",
    'headers = {"Authorization": f"Bearer {token}"}',
    "api_key = 'YOUR_API_KEY_HERE'",
    'api_key = "<your key>"',
    'password = "changeme"',
    "API_KEY=${OPENAI_API_KEY}",
    'access_token: "xxxxxxxxxxxxxxxxxxxxxxxx"',
    "client_secret = load_secret('client')",
    "The api_key: parameter is read from the environment.",
    "api_key = None",
    "password = ''",
    "auth_token = AUTH_TOKEN_ENV_NAME",
    'apiKey: "!bin/genai-token"',
    'fake = "sk-FAKE-PLANTED-0000-DO-NOT-PRINT"',
    '"auth": {"api_key": "sk-omlx-test-key"}',
]
BLOCK = [
    "-----BEGIN RSA PRIVATE " + "KEY-----",
    "-----BEGIN OPENSSH PRIVATE " + "KEY-----",
    "key = '%s'" % SK,
    "x-api-key: %s" % SKANT,
    "aws_access_key_id = %s" % AWS,
    "token %s" % GHP,
    "SLACK=%s" % SLACK,
    "maps key %s" % GOOG,
    "Authorization: Bearer %s" % B64,
    'api_key = "%s"' % HEX,
    "api_key: '%s'" % B64,
    "API_KEY=%s" % HEX,
    "aws_secret_access_key = %s" % B64,
    'password = "hunter' + '22!"',
    'client_secret: str = "%s"' % HEX,
    '"access_token": "%s"' % B64,
]


class SecretFilter(unittest.TestCase):
    def test_identifiers_and_parameters_pass(self):
        for text in PASS:
            with self.subTest(text=text):
                self.assertEqual(consult.scan_payload(text), [])

    def test_key_values_are_refused(self):
        for text in BLOCK:
            with self.subTest(text=text):
                self.assertTrue(consult.scan_payload(text))

    def test_values_embedded_in_a_large_code_payload_still_refuse(self):
        code = "\n".join(PASS) * 50
        self.assertEqual(consult.scan_payload(code), [])
        self.assertTrue(consult.scan_payload(code + "\nOPENAI=%s\n" % SK))


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from server import provider_key_crypto


class ProviderKeyCryptoTests(unittest.TestCase):
    def test_encryption_round_trip_and_wrong_key_rejected(self):
        first = Fernet.generate_key().decode()
        second = Fernet.generate_key().decode()
        with patch.dict(os.environ, {'PROVIDER_SETTINGS_FERNET_KEY': first}):
            encrypted = provider_key_crypto.encrypt('secret-test-value')
            self.assertTrue(encrypted.startswith(provider_key_crypto.PREFIX))
            self.assertNotIn('secret-test-value', encrypted)
            self.assertEqual('secret-test-value', provider_key_crypto.decrypt(encrypted))
            self.assertEqual(encrypted, provider_key_crypto.encrypt(encrypted))
        with patch.dict(os.environ, {'PROVIDER_SETTINGS_FERNET_KEY': second}):
            with self.assertRaises(RuntimeError):
                provider_key_crypto.decrypt(encrypted)

    def test_production_cannot_write_plaintext_without_master_key(self):
        with patch.dict(os.environ, {'APP_ENV': 'production', 'PROVIDER_SETTINGS_FERNET_KEY': ''}):
            with self.assertRaises(RuntimeError):
                provider_key_crypto.encrypt('secret-test-value')

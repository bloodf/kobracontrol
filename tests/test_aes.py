"""AES-128: FIPS-197 block vector, NIST SP 800-38A CBC vectors, PKCS#7 padding and error cases."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import aes  # noqa: E402

H = bytes.fromhex
NIST_KEY = H("2b7e151628aed2a6abf7158809cf4f3c")
NIST_IV = H("000102030405060708090a0b0c0d0e0f")
NIST_PT = H("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51"
            "30c81c46a35ce411e5fbc1191a0a52ef" "f69f2445df4f9b17ad2b417be66c3710")
NIST_CT = H("7649abac8119b246cee98e9b12e9197d" "5086cb9b507219ee95db113a917678b2"
            "73bed6b8e3c1743b7116e69e22229516" "3ff1caa1681fac09120eca307586e1a7")


class BlockTests(unittest.TestCase):
    def test_fips197_appendix_c1(self):
        key = H("000102030405060708090a0b0c0d0e0f")
        pt, ct = H("00112233445566778899aabbccddeeff"), H("69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(aes.encrypt_block(key, pt), ct)
        self.assertEqual(aes.decrypt_block(key, ct), pt)


class CbcTests(unittest.TestCase):
    def test_sp800_38a_encrypt(self):
        self.assertEqual(aes.encrypt_cbc(NIST_KEY, NIST_IV, NIST_PT, pad=False), NIST_CT)

    def test_sp800_38a_decrypt(self):
        self.assertEqual(aes.decrypt_cbc(NIST_KEY, NIST_IV, NIST_CT, unpad=False), NIST_PT)

    def test_padded_round_trip_all_lengths(self):
        for n in range(0, 40):
            data = bytes(range(n))
            ct = aes.encrypt_cbc(NIST_KEY, NIST_IV, data)
            self.assertEqual(len(ct) % 16, 0)
            self.assertGreater(len(ct), n)
            self.assertEqual(aes.decrypt_cbc(NIST_KEY, NIST_IV, ct), data)

    def test_full_block_gets_extra_padding_block(self):
        self.assertEqual(len(aes.encrypt_cbc(NIST_KEY, NIST_IV, b"x" * 16)), 32)

    def test_bad_padding(self):
        bad_tails = [b"\x00" * 16, b"\x11" * 16, b"\x01" * 14 + b"\x03\x02"]
        for tail in bad_tails:
            ct = aes.encrypt_cbc(NIST_KEY, NIST_IV, tail, pad=False)
            with self.assertRaises(ValueError, msg=tail.hex()):
                aes.decrypt_cbc(NIST_KEY, NIST_IV, ct)

    def test_bad_ciphertext_length(self):
        for n in (0, 15, 17):
            with self.assertRaises(ValueError):
                aes.decrypt_cbc(NIST_KEY, NIST_IV, b"\x00" * n)

    def test_unpadded_encrypt_needs_whole_blocks(self):
        with self.assertRaises(ValueError):
            aes.encrypt_cbc(NIST_KEY, NIST_IV, b"abc", pad=False)

    def test_bad_key_and_iv_length(self):
        with self.assertRaises(ValueError):
            aes.encrypt_cbc(b"short", NIST_IV, b"")
        with self.assertRaises(ValueError):
            aes.decrypt_cbc(NIST_KEY, b"short", NIST_CT)
        with self.assertRaises(ValueError):
            aes.encrypt_block(NIST_KEY, b"short")


if __name__ == "__main__":
    unittest.main()

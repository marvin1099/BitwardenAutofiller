#!/usr/bin/env python

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os

import hashlib
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend


def generate_key_from_input(data, key_size=32):
    """Generate a fixed-size key using SHA-256 hash."""
    hash_object = hashlib.sha256(data.encode())
    return hash_object.digest()[
        :key_size
    ]  # Ensure the key size is appropriate


def encrypt_aes_256(plaintext, passphrase):
    """Encrypt plaintext using AES-256 with a key derived from a passphrase."""
    key = generate_key_from_input(passphrase)
    iv = os.urandom(16)  # AES block size is 16 bytes

    cipher = Cipher(
        algorithms.AES(key), modes.CBC(iv), backend=default_backend()
    )
    encryptor = cipher.encryptor()

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_plaintext = padder.update(plaintext.encode()) + padder.finalize()

    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    return iv + ciphertext


def decrypt_aes_256(ciphertext, passphrase):
    """Decrypt ciphertext using AES-256 with a key derived from a passphrase."""
    key = generate_key_from_input(passphrase)
    iv = ciphertext[:16]
    ciphertext = ciphertext[16:]

    cipher = Cipher(
        algorithms.AES(key), modes.CBC(iv), backend=default_backend()
    )
    decryptor = cipher.decryptor()

    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

    return plaintext.decode()

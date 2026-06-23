"""Generate an Ed25519 key pair for the one-way VideoBrief boundary."""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


private_key = Ed25519PrivateKey.generate()
print("VIDEO_BRIEF_PRIVATE_KEY=%r" % private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("utf-8"))
print("MEDIA_BRIEF_PUBLIC_KEY=%r" % private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("utf-8"))

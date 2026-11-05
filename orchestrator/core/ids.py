import secrets
import time

ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'


def new_id(prefix: str) -> str:
    """ULID: 48-bit millisecond timestamp and 80 random bits, Crockford base32."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(ALPHABET[value & 31])
        value >>= 5
    return prefix + '_' + ''.join(reversed(chars))

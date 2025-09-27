import json
from cryptography.fernet import Fernet
from base64 import b64encode, b64decode


def dataencode(cround, data):
    docrypt = Fernet(cround.qr_fernet)
    return b64encode(docrypt.encrypt(str(data).encode())).decode("ascii")


def datadecode(cround, data):
    docrypt = Fernet(cround.qr_fernet)
    return int(docrypt.decrypt(b64decode(data.encode())))


def is_admin_user(user):
    return user.is_authenticated and user.groups.filter(name="Admin").exists()

from trytond.pool import PoolMeta
from trytond.config import config


__all__ = [
    'User',
    ]


class User(metaclass=PoolMeta):
    __name__ = 'res.user'

    @classmethod
    def check_password(cls, password, hash_):
        if config.getboolean('debug', 'ignore_passwords', default=False):
            return True, None
        return super(User, cls).check_password(password, hash_)

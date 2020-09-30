from trytond.pool import PoolMeta
from trytond.config import config


__all__ = [
    'User',
    ]


class User(metaclass=PoolMeta):
    __name__ = 'res.user'

    @classmethod
    def get_login(cls, login, parameters):
        if config.getboolean('debug', 'ignore_passwords', default=False):
            return cls.search([('login', '=', login)])[0].id
        return super().get_login(login, parameters)

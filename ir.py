from sql import Null

from trytond.pool import PoolMeta, Pool
from trytond.config import config
from trytond.transaction import Transaction


__all__ = [
    'User',
    'ActionKeyword',
    ]


class User(metaclass=PoolMeta):
    __name__ = 'res.user'

    @classmethod
    def get_login(cls, login, parameters):
        if config.getboolean('debug', 'ignore_passwords', default=False):
            user = cls.search([('login', '=', login)])
            if user:
                return user[0].id
        return super().get_login(login, parameters)


class ActionKeyword(metaclass=PoolMeta):
    __name__ = 'ir.action.keyword'

    @classmethod
    def __register__(cls, module):
        super().__register__(module)

        cursor = Transaction().connection.cursor()
        keyword_table = cls.__table__()
        wizard_table = Pool().get('ir.action.wizard').__table__()

        table = keyword_table.join(wizard_table, condition=(
                keyword_table.action == wizard_table.action))

        cursor.execute(*table.select(keyword_table.id, where=(
                (wizard_table.wiz_name == 'ir.model.debug') &
                (keyword_table.keyword == 'form_action') &
                (keyword_table.model != Null))))
        matches = cursor.fetchall()
        if not matches:
            return

        for keyword in matches:
            cursor.execute(*keyword_table.update(
                    columns=[keyword_table.model],
                    values=[Null],
                    where=(keyword_table.id == keyword)))

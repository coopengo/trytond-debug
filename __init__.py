# This file is part of Coog. The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import inspect
import re
import logging

from trytond.pool import Pool
import debug


def register():
    Pool.register(
        debug.FieldInfo,
        debug.ModelInfo,
        debug.VisualizeDebug,
        debug.DebugModelInstance,
        debug.DebugMROInstance,
        debug.DebugMethodInstance,
        debug.DebugMethodMROInstance,
        debug.DebugFieldInstance,
        debug.DebugViewInstance,
        debug.DebugOnChangeRelation,
        debug.DebugOnChangeWithRelation,
        module='debug', type_='model')

    Pool.register(
        debug.DebugModel,
        debug.Debug,
        debug.RefreshDebugData,
        debug.OpenInitialFrame,
        module='debug', type_='wizard')

    try:
        Pool.register_post_init_hooks(
            set_method_names_for_profiling,
            name_one2many_gets, module='debug')
    except:
        logging.getLogger().warning('Post init hooks disabled')


def set_method_names_for_profiling(pool):
    '''
        Patches the pool initialization to separate given methods per model
        in @profile reports.

        Methods to patch are set in trytond.conf :

            [debug]
            methods=read,_validate,search,create,delete
    '''
    from trytond.config import config

    def change_method_name_for_profiling(klass, method_name):
        '''
            Override method_name in klass to use
            "<method_name>__<model_name>" as name in order to appear as a
            different line when profiling.
        '''
        if not hasattr(klass, method_name):
            return
        if method_name in klass.__dict__:
            return
        method = getattr(klass, method_name)
        if inspect.ismethod(method) and method.__self__ is klass:
            template = '@classmethod'
        else:
            template = ''
        template += '''
def %s(*args, **kwargs):
    return super(klass, args[0]).%s(*args[1:], **kwargs)
setattr(klass, method_name, %s)'''
        patched_name = method_name + '__' + re.sub(
            r'[^A-Za-z0-9]+', '_', klass.__name__)
        exec template % (patched_name, method_name, patched_name) in \
            {'klass': klass, 'method_name': method_name}, {}

    meth_names = config.get('debug', 'methods')
    if not meth_names:
        return
    for meth_name in meth_names.split(','):
        logging.getLogger().warning(
            'Patching %s for profiling, not recommanded for prod!'
            % meth_name)
        for klass in pool._pool[pool.database_name].get(
                'model', {}).values():
            change_method_name_for_profiling(klass, meth_name)


def name_one2many_gets(pool):
    from trytond.config import config

    to_patch = (config.get('debug', 'fields_methods') or '').split(',')
    if not to_patch:
        return

    for meth_name in to_patch:
        logging.getLogger().warning(
            'Patching fields \'%s\' method for profiling, not recommanded '
            'for prod!' % meth_name)
        for klass in pool._pool[pool.database_name].get(
                'model', {}).values():
            for fname, field in klass._fields.items():
                if not hasattr(field, meth_name):
                    continue
                template = '''
def %s(*args, **kwargs):
    return field.__class__.%s(field, *args, **kwargs)
object.__setattr__(field, '%s', %s)'''
                patched_name = ('__field_%s__' % meth_name) + re.sub(
                    r'[^A-Za-z0-9]+', '_', klass.__name__) + '__' + fname
                exec template % (patched_name, meth_name, meth_name,
                    patched_name) in {'field': field}, {}

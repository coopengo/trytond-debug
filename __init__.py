# This file is part of Coog. The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from collections import defaultdict

import types
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
            tryton_syntax_analysis,
            set_method_names_for_profiling,
            name_one2many_gets, module='debug')
    except:
        logging.getLogger().warning('Post init hooks disabled')


def set_method_names_for_profiling(pool, update):
    '''
        Patches the pool initialization to separate given methods per model
        in @profile reports.

        Methods to patch are set in trytond.conf :

            [debug]
            methods=read,_validate,search,create,delete
    '''
    if update:
        return

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


def name_one2many_gets(pool, update):
    '''
        Patches the pool initialization to separate fields methods per model /
        field_name in @profile reports.

        Methods to patch are set in trytond.conf :

            [debug]
            fields_methods=get,set
    '''
    if update:
        return

    from trytond.config import config
    from trytond.model import fields as tryton_fields

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
                if (isinstance(field, tryton_fields.TimeDelta) and
                        meth_name == 'get'):
                    # Weird case we need to bypass
                    continue
                template = '''
def %s(*args, **kwargs):
    return field.__class__.%s(field, *args, **kwargs)
object.__setattr__(field, '%s', %s)'''
                patched_name = ('__field_%s__' % meth_name) + re.sub(
                    r'[^A-Za-z0-9]+', '_', klass.__name__) + '__' + fname
                exec template % (patched_name, meth_name, meth_name,
                    patched_name) in {'field': field}, {}


def tryton_syntax_analysis(pool, update):
    if update:
        return

    logging.getLogger('modules').info('Running trytond syntax analysis')
    detect_api_changes(pool)


def detect_api_changes(pool):
    '''
        Tries to detect api problems, that is method definitions that are not
        compatible among overrides. For instance, overriding :

        def test(a, b, c)

        with

        def test(a, b)

        will cause a warning since it does not honor the base API, which may be
        overriden in other modules.
    '''
    # Used to compensate arg number for static methods vs class methods
    def is_static(klass, mname):
        return isinstance(getattr(klass, mname), types.FunctionType)

    # Extract module name from class
    def m_name(mro):
        try:
            return str(mro).split('.')[2]
        except:
            return str(mro)

    for klass in pool._pool[pool.database_name].get('model', {}).values():
        meths_data = defaultdict(list)
        full_mro = klass.__mro__[::-1]
        for mname in dir(klass):
            if not callable(getattr(klass, mname)):
                continue
            for mro in full_mro:
                if 'trytond.pool' in str(mro):
                    continue
                cur_func = getattr(mro, mname, None)
                if not cur_func:
                    continue
                try:
                    raw = inspect.getargspec(cur_func)
                except:
                    # Functions which are actually partials are not
                    # inspectable
                    continue
                meths_data[mname].append((mro, raw))
        for mname, data in meths_data.iteritems():
            if len(data) <= 1:
                continue
            p_args, p_star_args, p_kwargs, p_def = None, None, None, None
            p_module, p_static = None, None
            for module, arg_data in data:
                if module.__name__ != klass.__name__:
                    continue
                if p_module is None:
                    p_args, p_star_args, p_kwargs, p_def = arg_data
                    p_module, p_static = module, is_static(module, mname)
                    continue
                args, star_args, kwargs, defaults = arg_data
                static = is_static(module, mname)
                if (len(p_args) + bool(p_static) == 1 and p_star_args and
                        p_kwargs):
                    continue
                real_args = len(args) - len(defaults or []) + bool(static)
                p_real_args = len(p_args) - len(p_def or []) + bool(p_static)
                if p_real_args != real_args and not star_args:
                    break
            else:
                continue
            logging.getLogger().warning('Incompatible method '
                'description for method %s::%s' % (klass.__name__, mname))
            logging.getLogger().warning('    %s : %s' % (m_name(p_module),
                    str((p_args, p_star_args, p_kwargs, p_def))))
            logging.getLogger().warning('    %s : %s' % (m_name(module),
                    str((args, star_args, kwargs, defaults))))

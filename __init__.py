# This file is part of Coog. The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import sys
import time
from collections import defaultdict
from io import StringIO

import types
import inspect
import re
import logging

from trytond.pool import Pool

from . import debug
from . import ir

logger = logging.getLogger('trytond:debug_module')


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
        ir.User,
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
            name_one2many_gets,
            activate_auto_profile,
            enable_debug_views,
            module='debug')
    except AttributeError:
        logger.warning('Post init hooks disabled')


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
        exec(
            template % (patched_name, method_name, patched_name),
            {'klass': klass, 'method_name': method_name}, {})

    to_patch = [
        x.strip()
        for x in (config.get('debug', 'methods') or '').split(',')
        if x.strip()]
    if not to_patch:
        return

    for meth_name in to_patch:
        logger.warning(
            'Patching model \'%s\' method for profiling' % meth_name)
        for klass in pool._pool[pool.database_name].get('model', {}).values():
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

    to_patch = [
        x.strip()
        for x in (config.get('debug', 'fields_methods') or '').split(',')
        if x.strip()]
    if not to_patch:
        return

    for meth_name in to_patch:
        logger.warning(
            'Patching fields \'%s\' method for profiling' % meth_name)
        for klass in pool._pool[pool.database_name].get('model', {}).values():
            for fname, field in list(klass._fields.items()):
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
                exec(
                    template % (
                        patched_name, meth_name, meth_name, patched_name),
                    {'field': field}, {})


def activate_auto_profile(pool, update):
    if update:
        return

    from configparser import NoSectionError
    from trytond.config import config
    from trytond.pool import PoolMeta

    logger = logging.getLogger('trytond.autoprofile')
    try:
        from profilehooks import profile
        threshold = config.getfloat('debug', 'auto_profile_threshold') or 0
        order = config.get('debug', 'auto_profile_order') or 'cumulative'
        entries = config.getint('debug', 'auto_profile_entries') or 80
        filename = config.get('debug', 'auto_profile_filename') or None
        dirs = config.getboolean('debug', 'auto_profile_show_dirs') or False

        def is_class_or_dual_method(method):
            return hasattr(method, '_dualmethod') or (
                isinstance(method, types.MethodType) and
                isinstance(method.__self__, PoolMeta))

        def auto_profile(f):
            def wrapped(self, *args, **kwargs):
                old_stdout = sys.stdout
                my_stdout = sys.stdout = StringIO()
                start = time.time()
                res = profile(f, immediate=True, sort=list(order.split(',')),
                    entries=entries, filename=filename, dirs=dirs)(
                    self, *args, **kwargs)
                end = time.time()
                sys.stdout = old_stdout
                if end - start >= threshold:
                    for line in my_stdout.getvalue().split('\n'):
                        logger.info(line)
                return res
            if hasattr(f, '__origin_function'):
                wrapped.__origin_function = f.__origin_function
            return wrapped

        def auto_profile_cls(f):
            @classmethod
            def wrapped(cls, *args, **kwargs):
                old_stdout = sys.stdout
                my_stdout = sys.stdout = StringIO()
                start = time.time()
                res = profile(f, immediate=True, sort=list(order.split(',')),
                    entries=entries, filename=filename, dirs=dirs)(
                    *args, **kwargs)
                end = time.time()
                sys.stdout = old_stdout
                if end - start >= threshold:
                    for line in my_stdout.getvalue().split('\n'):
                        logger.info(line)
                return res
            if hasattr(f, '__origin_function'):
                wrapped.__origin_function = f.__origin_function
            return wrapped

        for _, data in config.items('auto_profile'):
            model, methods = data.split(':')
            *pool_type, model = model.strip().split('/')
            pool_type = (pool_type or ['model'])[0]

            Model = pool._pool[pool.database_name].get(pool_type).get(model)
            for method in methods.split(','):
                method = method.strip()
                logger.warning('Enabling auto-profile for %s -> %s' % (
                        model, method))
                method_obj = getattr(Model, method)
                if is_class_or_dual_method(method_obj):
                    setattr(Model, method, auto_profile_cls(method_obj))
                else:
                    setattr(Model, method, auto_profile(method_obj))
    except ImportError:
        logger.warning('profilehooks not found, auto-profiling disabled')
    except NoSectionError:
        pass


def tryton_syntax_analysis(pool, update):
    if update:
        return

    from trytond.config import config
    enabled = config.getboolean('debug', 'enable_syntax_analysis')
    if not enabled:
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
        except IndexError:
            return str(mro)

    def prototype_match(proto_1, proto_2):
        # proto_1 should be a "subset" of proto_2
        # "name" vs "name=None" is ok, "name=None" vs "name" is not
        if any([ignore_proto(proto_1), ignore_proto(proto_2)]):
            # Ignore all *args / **kwargs with no other arguments
            return True
        args_1, star_args_1, kwargs_1, defaults_1, static_1 = proto_1
        args_2, star_args_2, kwargs_2, defaults_2, static_2 = proto_2
        if bool(star_args_1) != bool(star_args_2):
            return False
        if bool(kwargs_1) != bool(kwargs_2):
            return False
        diff = bool(static_1) - bool(static_2)
        if len(args_1) + diff != len(args_2):
            return False
        if len(defaults_1 or []) > len(defaults_2 or []):
            return False
        if diff > 0:
            args_2 = args_2[1:]
        elif diff < 0:
            args_1 = args_1[1:]
        if (args_1[-len(defaults_1 or [0]):] !=
                args_2[-len(defaults_1 or [0]):]):
            return False
        return True

    def ignore_proto(proto):
        if not proto:
            return True
        args, star_args, kwargs, defaults, static = proto
        if len(args) + bool(static) == 1 and star_args and kwargs:
            return True
        return False

    for klass in pool._pool[pool.database_name].get('model', {}).values():
        meths_data = defaultdict(list)
        full_mro = klass.__mro__[::-1]
        for mname in dir(klass):
            if not callable(getattr(klass, mname)):
                continue
            for mro in full_mro:
                cur_func = getattr(mro, mname, None)
                if not cur_func:
                    continue
                try:
                    raw = inspect.getfullargspec(cur_func)
                except TypeError:
                    # Functions which are actually partials are not
                    # inspectable
                    raw = None
                else:
                    raw = tuple(raw)[:4] + (is_static(mro, mname),)
                try:
                    cur_func = getattr(super(mro, klass), mname, None)
                    super_raw = inspect.getfullargspec(cur_func)
                except TypeError:
                    # Functions which are actually partials are not
                    # inspectable
                    super_raw = None
                else:
                    super_raw = tuple(super_raw)[:4] + (
                        is_static(super(mro, klass), mname),)
                meths_data[mname].append((mro, raw, super_raw))
        for mname, data in meths_data.items():
            if len(data) <= 1:
                continue
            p_proto, found = None, False
            for module, arg_data, super_data in reversed(data):
                if p_proto is None and not ignore_proto(arg_data):
                    p_proto = arg_data
                if ignore_proto(super_data):
                    if found and module.__name__ == klass.__name__:
                        break
                    continue
                if not prototype_match(p_proto, super_data):
                    found = True
                else:
                    p_proto = super_data
            else:
                continue
            logger.warning(
                'Incompatible method '
                'description for method %s::%s' % (klass.__name__, mname))
            for module, arg_data, _ in data:
                if (arg_data is not None and module.__name__ == klass.__name__
                        and 'trytond.pool' not in str(module)):
                    logger.warning('    %s : %s' % (
                            m_name(module), str(arg_data[:-1])))


def enable_debug_views(pool, update):
    if update:
        return

    from trytond.config import config

    enabled = config.getboolean('debug', 'debug_views')
    if not enabled:
        return

    logger.warning('Enabling debugging views')

    from trytond.model import ModelView, ModelSQL, fields
    from trytond.transaction import Transaction

    previous_fields_view_get = ModelView.fields_view_get.__func__

    @classmethod
    def patched_fields_view_get(cls, view_id=None, view_type='form',
            level=None):
        if not Transaction().context.get('developper_view'):
            return previous_fields_view_get(cls, view_id, view_type, level)
        if not issubclass(cls, ModelSQL):
            return previous_fields_view_get(cls, view_id, view_type, level)

        # Specific feature in tryton fork
        expand_toolbar = bool(
            Pool().get('ir.module').search([('name', '=', 'coog_core')]))
        result = {
            'model': cls.__name__,
            'type': view_type,
            'field_childs': None,
            'view_id': 0,
            }
        xml = '<?xml version="1.0"?>'
        fnames = []
        if view_type == 'tree':
            xml += '<tree>'
            xml += '<field name="id"/>'
            xml += '<field name="rec_name" expand="1"/>'
            xml += '</tree>'
            fnames += ['rec_name', 'id']
        else:
            res = cls.fields_get()
            xml += '<form col="2">'
            for fname in sorted(res):
                if res[fname]['type'] in ('timestamp'):
                    continue
                relation = res[fname].get('relation', None)
                if relation:
                    Target = Pool().get(relation)
                    if not issubclass(Target, ModelView):
                        continue
                if res[fname]['type'] in (
                        'one2many', 'many2many', 'text', 'dict'):
                    xml += '<separator name="%s" colspan="2"/>' % fname
                    xml += '<field name="%s" colspan="2"' % fname
                    if expand_toolbar:
                        # expand_toolbar is available
                        xml += ' height="200" expand_toolbar="0"/>'
                    else:
                        xml += ' height="200"/>'
                else:
                    xml += '<label name="%s"/><field name="%s"/>' % (
                        fname, fname)
                fnames.append(fname)
            xml += '</form>'
        result['arch'] = xml
        result['fields'] = cls.fields_get(fnames)
        for fname in fnames:
            name = result['fields'][fname]['string'] + ' (%s)' % fname
            if issubclass(type(cls._fields[fname]), fields.Function):
                name += ' [Function]'
            result['fields'][fname].update({
                    'string': name,
                    'states': {'readonly': True},
                    'on_change': [],
                    'on_change_with': [],
                    })
        return result

    setattr(ModelView, 'fields_view_get', patched_fields_view_get)

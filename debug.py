# This file is part of Coog. The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import os
import inspect
from collections import defaultdict
import pprint
import logging

from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.config import config
from trytond.rpc import RPC
from trytond.model import ModelSQL, ModelView, fields
from trytond.transaction import Transaction
from trytond.pool import Pool
from trytond.pyson import Eval, Bool

logger = logging.getLogger(__name__)
METHOD_TEMPLATES = ['default_', 'on_change_with_', 'on_change_', 'order_']

__all__ = [
    'FieldInfo',
    'ModelInfo',
    'DebugModel',
    'VisualizeDebug',
    'Debug',
    'DebugModelInstance',
    'DebugMROInstance',
    'DebugFieldInstance',
    'DebugMethodInstance',
    'DebugMethodMROInstance',
    'DebugViewInstance',
    'DebugOnChangeRelation',
    'DebugOnChangeWithRelation',
    'RefreshDebugData',
    'OpenInitialFrame',
    ]


def open_path(rel_path, patterns):
    import trytond
    new_path = [trytond.__file__, '..', '..'] + [x for x in rel_path]
    new_path = os.path.abspath(os.path.join(*new_path))
    editor = os.environ.get('EDITOR', None)
    if editor is None:
        logging.getLogger().warning('No editor found, feature disabled')
    if editor == 'nvim':
        from neovim import attach
        path = '/tmp/nvim_' + os.path.basename(os.environ.get('VIRTUAL_ENV',
                os.environ.get('NVIM_LISTEN_ADDRESS', 'root'))) + '.sock'
        nvim = attach('socket', path=path)
        nvim.command('tabnew')
        nvim.command('edit %s' % new_path)
        prev_pos = nvim.eval("getpos('.')")[1]
        for pattern_group in patterns:
            for pattern in pattern_group:
                nvim.command("execute search('%s', 'w')" % pattern)
                new_pos = nvim.eval("getpos('.')")[1]
                if new_pos != prev_pos:
                    prev_pos = new_pos
                    break
                prev_pos = new_pos
        try:
            nvim.command('execute "normal zO"')
        except:
            # Vim fails if no folds were found
            pass
    elif editor == 'gvim':
        os.system(editor + ' -c edit ' + new_path + ' &')
    else:
        os.system(editor + ' ' + new_path + ' &')
    return


class FieldInfo(ModelView):
    'Field Info'

    __name__ = 'ir.model.debug.model_info.field_info'

    name = fields.Char('Field name')
    kind = fields.Char('Field type')
    is_function = fields.Boolean('Is Function')
    target_model = fields.Char('Target Model')
    string = fields.Char('String')
    state_required = fields.Text('State Required')
    is_required = fields.Boolean('Is required')
    state_readonly = fields.Text('State Readonly')
    is_readonly = fields.Boolean('Is readonly')
    state_invisible = fields.Text('State Invisible')
    is_invisible = fields.Boolean('Is invisible')
    has_domain = fields.Boolean('Has domain')
    field_domain = fields.Text('Domain')
    id_to_calculate = fields.Integer('Id To Calculate')
    calculated_value = fields.Char('Calculated Value')


class ModelInfo(ModelView):
    'Model Name'

    __name__ = 'ir.model.debug.model_info'

    model_name = fields.Selection('get_possible_model_names', 'Model Name')
    field_infos = fields.One2Many('ir.model.debug.model_info.field_info',
        '', 'Fields Infos')
    hide_functions = fields.Boolean('Hide Functions')
    filter_value = fields.Selection([
            ('name', 'Name'),
            ('kind', 'Kind'),
            ('string', 'String')], 'Filter Value')
    id_to_calculate = fields.Integer('Id To Calculate')
    to_evaluate = fields.Char('To Evaluate', states={
            'invisible': ~Bool(Eval('id_to_calculate', False))},
        help="Use the 'instance' keyword to get the instanciated model",
        depends=['id_to_calculate'])
    evaluation_result = fields.Text('Evaluation Result', states={
            'invisible': ~Bool(Eval('id_to_calculate', False))},
        readonly=True, depends=['id_to_calculate'])
    must_raise_exception = fields.Boolean('Must Raise Exception')
    previous_runs = fields.Text('Previous runs', states={
            'invisible': ~Bool(Eval('id_to_calculate', False))},
        readonly=True, depends=['id_to_calculate'])

    @classmethod
    def __setup__(cls):
        super(ModelInfo, cls).__setup__()
        cls.__rpc__.update({
                'raw_model_infos': RPC(),
                'raw_module_infos': RPC(),
                'raw_field_infos': RPC(),
                })
        cls._buttons.update({
                'follow_link': {},
                })

    @classmethod
    def get_possible_model_names(cls):
        pool = Pool()
        return list([(x, x) for x in
                pool._pool[pool.database_name]['model'].keys()])

    def get_field_info(self, field, field_name):

        info = Pool().get('ir.model.debug.model_info.field_info')()
        info.name = field_name
        info.string = field.string
        if isinstance(field, fields.Function):
            if self.hide_functions:
                return None
            info.is_function = True
            real_field = field._field
        else:
            info.is_function = False
            real_field = field
        info.kind = real_field.__class__.__name__
        if isinstance(field, (fields.Many2One, fields.One2Many)):
            info.target_model = field.model_name
        elif isinstance(field, fields.Many2Many):
            if field.target:
                info.target_model = Pool().get(field.relation_name)._fields[
                    field.target].model_name
            else:
                info.target_model = field.relation_name
        else:
            info.target_model = ''
        for elem in ('required', 'readonly', 'invisible'):
            setattr(info, 'is_%s' % elem, getattr(field, elem, False))
            setattr(info, 'state_%s' % elem, repr(field.states.get(elem, {})))
        field_domain = getattr(field, 'domain', None)
        if field_domain:
            info.has_domain = True
            info.field_domain = repr(field_domain)
        return info

    @classmethod
    def default_filter_value(cls):
        return 'name'

    @fields.depends('model_name', 'hide_functions', 'filter_value',
        'field_infos', 'id_to_calculate')
    def on_change_filter_value(self):
        self.recalculate_field_infos()

    @fields.depends('model_name', 'hide_functions', 'filter_value',
        'field_infos', 'id_to_calculate')
    def on_change_hide_functions(self):
        self.recalculate_field_infos()

    @fields.depends('model_name', 'hide_functions', 'filter_value',
        'field_infos', 'id_to_calculate')
    def on_change_model_name(self):
        self.to_evaluate = ''
        self.evaluation_result = ''
        self.recalculate_field_infos()

    @fields.depends('model_name', 'hide_functions', 'filter_value',
        'field_infos', 'id_to_calculate')
    def on_change_id_to_calculate(self):
        self.on_change_hide_functions()

    @fields.depends('model_name', 'id_to_calculate', 'to_evaluate',
        'must_raise_exception', 'previous_runs')
    def on_change_to_evaluate(self):
        if not self.to_evaluate:
            self.evaluation_result = ''
            return
        if not self.id_to_calculate or not self.model_name:
            self.evaluation_result = ''
            self.previous_runs = ''
            return
        if self.previous_runs:
            previous_runs = self.previous_runs[1:].split('\n\n')
        else:
            previous_runs = ['']
        if previous_runs[0] != self.to_evaluate:
            self.previous_runs = '\n\n'.join(
                ['# %s (%i)\n%s' % (self.model_name, self.id_to_calculate,
                        self.to_evaluate)] + [x for x in previous_runs if x])
        try:
            self.evaluation_result = pprint.pformat(self.evaluate())
        except Exception as exc:
            if self.must_raise_exception:
                raise
            self.evaluation_result = 'ERROR: %s' % str(exc)

    def evaluate(self):
        context = {
            'instance': Pool().get(self.model_name)(self.id_to_calculate),
            }
        return eval(self.to_evaluate, context)

    @ModelView.button_change('model_name', 'id_to_calculate', 'to_evaluate',
        'must_raise_exception', 'previous_runs', 'hide_functions',
        'filter_value', 'field_infos')
    def follow_link(self):
        try:
            target = self.evaluate()
            if not isinstance(target, ModelSQL):
                return
        except:
            return
        self.id_to_calculate = target.id
        self.model_name = target.__name__
        self.evaluation_result = ''
        self.to_evaluate = ''
        self.recalculate_field_infos()

    def recalculate_field_infos(self):
        self.field_infos = []
        if not self.model_name:
            return
        TargetModel = Pool().get(self.model_name)
        all_fields_infos = [self.get_field_info(field, field_name)
                for field_name, field in TargetModel._fields.items()]
        self.field_infos = sorted(
            [x for x in all_fields_infos if x is not None],
            key=lambda x: getattr(x, self.filter_value))
        if self.id_to_calculate:
            for field in self.field_infos:
                try:
                    field.calculated_value = str(getattr(
                            TargetModel(self.id_to_calculate), field.name))
                except Exception as exc:
                    field.calculated_value = 'ERROR: %s' % str(exc)

    @classmethod
    def raw_field_info(cls, base_model, field_name):
        if isinstance(base_model, str):
            base_model = Pool().get(base_model)
        field = base_model._fields[field_name]
        result = {
            'name': field_name,
            'string': field.string,
            }
        result['is_function'] = False
        if isinstance(field, fields.Function):
            result['is_function'] = True
            result['getter'] = field.getter
            if field.setter:
                result['setter'] = field.setter
            if field.searcher:
                result['searcher'] = field.searcher
            field = field._field
        result['kind'] = field.__class__.__name__
        if isinstance(field, (fields.Many2One, fields.One2Many)):
            result['target_model'] = field.model_name
        elif isinstance(field, fields.Many2Many):
            if field.target:
                result['target_model'] = Pool().get(
                    field.relation_name)._fields[field.target].model_name
            else:
                result['target_model'] = field.relation_name
        if isinstance(field, fields.Selection):
            if isinstance(field.selection, str):
                result['selection_method'] = field.selection
            else:
                result['selection_values'] = dict([x
                        for x in field.selection if x[0]])
        for elem in ('required', 'readonly', 'invisible'):
            result['is_%s' % elem] = getattr(field, elem, False)
            result['state_%s' % elem] = repr(field.states.get(elem, {}))
        for elem in ('on_change', 'on_change_with', 'default'):
            result[elem] = hasattr(base_model, '%s_%s' % (elem, field_name))
        field_domain = getattr(field, 'domain', None) or None
        result['has_domain'] = bool(field_domain)
        if field_domain:
            result['domain'] = repr(field_domain)
        result['module'] = ''
        for frame in base_model.__mro__[::-1]:
            full_name = str(frame)[8:-2].split('.')
            if len(full_name) < 2:
                continue
            if full_name[1] == 'modules':
                result['module'] = full_name[2]
            if getattr(frame, field_name, None) is not None:
                break
        return result

    @classmethod
    def raw_field_infos(cls, models=None):
        pool = Pool()
        if models is None:
            models = [x[0] for x in cls.get_possible_model_names()]
        infos = cls.raw_model_infos(models)
        for name in models:
            base_model = pool.get(name)
            infos[name]['fields'] = {}
            for fname in base_model._fields:
                infos[name]['fields'][fname] = cls.raw_field_info(base_model,
                    fname)
        return infos

    @classmethod
    def extract_mro(cls, model_class, model_name):
        result, methods, first_occurence = {}, {}, False
        for elem in dir(model_class):
            if elem == 'on_change_with':
                # Particular case
                continue
            if elem.startswith('__') and elem not in ('__register__',
                    '__setup__'):
                continue
            if not callable(getattr(model_class, elem)):
                continue
            for ftemplate in METHOD_TEMPLATES:
                if elem.startswith(ftemplate):
                    methods[elem] = {
                        'field': elem[len(ftemplate):],
                        '_function': None,
                        'mro': {},
                        }
                    break
            else:
                methods[elem] = {
                    'field': '',
                    '_function': None,
                    'mro': {},
                    }
        mro = model_class.__mro__

        model_name_dots = len(model_name.split('.'))
        for line in mro[::-1][1:]:
            full_name = str(line)[8:-2].split('.')
            if full_name[1] == 'pool':
                continue
            new_line = {
                'module': '',
                'override': 0,
                'initial': 0,
                'base_name': full_name[-1],
                'path': '.'.join(full_name[:-1]),
                }
            if full_name[1] == 'modules':
                new_line['module'] = full_name[2]
            if str(line)[:-2].endswith(model_name):
                new_line['override'] = 1 if first_occurence else 0
                new_line['initial'] = 0 if first_occurence else 1
                new_line['base_name'] = model_name
                new_line['path'] = '.'.join(
                    full_name[:-model_name_dots])
                first_occurence = True
            result['% 3d' % (len(result) + 1)] = new_line
            for mname, mvalues in methods.items():
                cur_func = getattr(line, mname, None)
                if not cur_func:
                    continue
                key = getattr(cur_func, 'im_func', cur_func)
                if key == mvalues['_function']:
                    continue
                m_mro = dict(new_line)
                m_mro['initial'] = 0 if len(mvalues['mro']) else 1
                m_mro['override'] = 1 if len(mvalues['mro']) else 0
                mvalues['mro']['% 3d' % (
                        len(mvalues['mro']) + 1)] = m_mro
                mvalues['_function'] = key
                if m_mro['initial']:
                    try:
                        raw = inspect.getargspec(cur_func)
                    except:
                        # Functions which are actually partials are not
                        # inspectable
                        continue
                    mvalues['parameters'] = mname + inspect.formatargspec(*raw)
        to_pop = []
        for mname, mvalues in methods.items():
            if not mvalues['mro']:
                to_pop.append(mname)
                continue
            if not mvalues['mro']['% 3d' % len(mvalues['mro'])]['module']:
                to_pop.append(mname)
                continue
            mvalues.pop('_function')
        for mname in to_pop:
            methods.pop(mname)
        return result, methods

    @classmethod
    def extract_views(cls, model_class, model_name, model_data_cache):
        pool = Pool()
        View = pool.get('ir.ui.view')
        views = {x.id: x for x in View.search([('model', '=', model_name)])}
        master_views = {}
        other_masters = defaultdict(list)
        for view in views.values():
            if not view.inherit:
                master_views[view.id] = {
                    'module': view.module or '',
                    'type': view.type or '',
                    'priority': view.priority or '',
                    'field_childs': view.field_childs or '',
                    'name': view.name or '',
                    'functional_id': model_data_cache.get(
                        (view.module, view.id), view.name or ''),
                    'inherit': [],
                    }
            else:
                other_masters[view.inherit.id].append(view)

        for view_id, children in other_masters.items():
            if view_id not in views:
                continue
            if view_id not in master_views:
                view = views[view_id]
                master_views[view.id] = {
                    'module': view.module or '',
                    'type': view.type or '',
                    'priority': view.priority or '',
                    'field_childs': view.field_childs or '',
                    'name': view.name or '',
                    'functional_id': model_data_cache[(view.module, view.id)],
                    'inherit': [],
                    }
            for child in children:
                master_views[view_id]['inherit'].append({
                        'module': child.module or '',
                        'type': child.type or '',
                        'priority': child.priority or '',
                        'field_childs': child.field_childs or '',
                        'functional_id': model_data_cache[(child.module,
                                child.id)],
                        'name': child.name or master_views[view_id]['name'],
                        })

        def view_sort(x):
            if x not in model_class._modules_list:
                return len(model_class._modules_list)
            return model_class._modules_list.index(x['module'])

        master_views = {'% 3i' % idx: val
            for idx, val in enumerate(
                sorted(master_views.values(), key=view_sort))}

        for view in master_views.values():
            if len(view['inherit']) == 0:
                del view['inherit']
                continue
            view['inherit'].sort(key=view_sort)
            view['inherit'] = {
                '% 3i' % idx: val for idx, val in enumerate(view['inherit'])}
        return master_views

    @classmethod
    def raw_model_infos(cls, models):
        pool = Pool()
        infos = {}
        model_data = pool.get('ir.model.data').search([
                ('model', '=', 'ir.ui.view')])
        model_data_cache = {(x.module, x.db_id): x.fs_id for x in model_data}
        for model_name in models:
            Model = pool.get(model_name)
            try:
                string = Model._get_name()
            except AssertionError:
                # None type has no attribute splitlines
                string = Model.__name__
            mro, methods = cls.extract_mro(Model, model_name)
            infos[model_name] = {
                'string': string,
                'mro': mro,
                'methods': methods,
                'views': cls.extract_views(Model, model_name,
                    model_data_cache),
                }
        return infos

    @classmethod
    def raw_module_infos(cls):
        infos = {}
        for module in Pool().get('ir.module').search([],
                order=[('name', 'DESC')]):
            infos[module.name] = {
                'state': module.state,
                'childs': [x.name for x in module.childs],
                }
        return infos

    @fields.depends('id_to_calculate', 'model_name', 'to_evaluate')
    def autocomplete_to_evaluate(self):
        if not self.id_to_calculate or not self.to_evaluate.strip():
            return [self.to_evaluate]
        base = self.to_evaluate.lstrip()
        if ' ' in base:
            return [self.to_evaluate]
        try:
            base = base.split('.')
            target = base[-1]
            base = base[:-1]
            if not base or base[0] != 'instance':
                return [self.to_evaluate]
            instance = Pool().get(self.model_name)(self.id_to_calculate)
            value = eval('.'.join(base), {}, {'instance': instance})
            if not isinstance(value, (ModelSQL, ModelView)):
                return [self.to_evaluate]
            return sorted(['.'.join(base + [k])
                    for k in value.__class__._fields.keys()
                    if k.startswith(target)] + [self.to_evaluate])
        except Exception:
            return [self.to_evaluate]


class DebugModel(Wizard):
    'Debug Model'

    __name__ = 'ir.model.debug'

    start_state = 'model_info'
    model_info = StateView('ir.model.debug.model_info',
        'debug.model_info_view_form',
        [Button('Quit', 'end', 'tryton-cancel')])

    def default_model_info(self, name):
        return {
            'model_name': Transaction().context.get('active_model', None),
            'id_to_calculate': Transaction().context.get('active_id', None),
            'hide_functions': False,
            'filter_value': 'name',
            }


class VisualizeDebug(ModelView):
    'Debug Visualize'

    __name__ = 'debug.visualize'

    pyson = fields.Text('Pyson to Transform')
    synch_model_data = fields.Boolean('Synchronise Model Data')
    result = fields.Text('Result')


class Debug(Wizard):
    'Debug'

    __name__ = 'debug'

    start_state = 'run'
    run = StateTransition()
    display = StateView('debug.visualize', 'debug.visualize_view_form',
        [Button('Quit', 'end', 'tryton-cancel'),
            Button('Re-Run', 'run', 'tryton-go-next')])

    def run_code(self):
        # Run your code. return value will be wrote down in the display window
        if self.display.synch_model_data:
            return self.synch_model_data()
        elif self.display.pyson:
            return self.transform_pyson()

    def transform_pyson(self):
        from trytond.pyson import Eval, Bool, Or, PYSONEncoder, And, Not  # NOQA
        encoded = PYSONEncoder().encode(eval(self.display.pyson))
        return ''.join([x if x != '"' else '&quot;' for x in encoded])

    def synch_model_data(self):
        ModelData = Pool().get('ir.model.data')
        to_sync = ModelData.search([('out_of_sync', '=', True)])
        nb_to_sync = len(to_sync)
        if to_sync:
            ModelData.sync(to_sync)
        to_sync = ModelData.search([('out_of_sync', '=', True)])
        return 'Synchronised %s/%s model data' % (nb_to_sync - len(to_sync),
            nb_to_sync)

    def transition_run(self):
        return 'display'

    def default_display(self, name):
        res = self.display._default_values
        if not res:
            return res
        res.update({'result': self.run_code()})
        return res


class DebugModelInstance(ModelSQL, ModelView):
    'Model for debug'

    __name__ = 'debug.model'
    _history = True

    name = fields.Char('Name', select=True, readonly=True)
    string = fields.Char('String', readonly=True)
    mro = fields.One2Many('debug.model.mro', 'model', 'MRO',
        order=[('order', 'ASC')])
    fields_ = fields.One2Many('debug.model.field', 'model', 'Fields',
        order=[('name', 'ASC')])
    methods = fields.One2Many('debug.model.method', 'model', 'Methods',
        order=[('name', 'ASC')])
    views = fields.One2Many('debug.model.view', 'model', 'Views',
        order=[('order', 'ASC')])
    initial_module = fields.Function(
        fields.Char('Declared in'),
        'get_initial_module')
    initial_frame = fields.Function(
        fields.Many2One('debug.model.mro', 'Initial Frame'),
        'get_initial_frame')

    @classmethod
    def __setup__(cls):
        super(DebugModelInstance, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls.__rpc__.update({'refresh': RPC(readonly=False)})
        cls._buttons.update({'open_initial': {}})

    @classmethod
    def __register__(cls, module):
        cls._history = False
        super(DebugModelInstance, cls).__register__(module)
        cls._history = True

    @classmethod
    def _update_history_table(cls):
        update = config.get('debug', 'auto_refresh_debug_data')
        if update:
            logging.getLogger().warning('Auto refreshing debug data, '
                'this may take some time. Clear "auto_refresh_debug_data" '
                'in configuration file to avoid')
            cls.refresh()

    def get_initial_frame(self, name):
        return [x.id for x in self.mro if x.kind == 'initial'][0]

    def get_initial_module(self, name):
        return [x.module for x in self.mro if x.kind == 'initial'][0]

    @classmethod
    @ModelView.button_action('debug.act_open_initial')
    def open_initial(cls, models):
        pass

    @classmethod
    def refresh(cls, name=None, models=None):
        cls._history = False
        Model = Pool().get('debug.model')

        # Fetch current data
        base_data = Pool().get('ir.model.debug.model_info').raw_field_infos(
            models)

        # Delete all existing instances
        cls.delete(cls.search([('name', 'in', base_data.keys())]))

        # Existing models
        existing_models = {x.name: x for x in cls.search([])}

        # Import Models, MRO, Methods
        for model_name, data in base_data.items():
            logger.debug('Importing model %s' % model_name)
            cls.import_model(model_name, data)
        Model.save([x['__instance'] for x in base_data.values()])

        # Import Fields
        for model_name, data in base_data.items():
            logger.debug('Importing fields for model %s' % model_name)
            cls.import_fields(model_name, data, base_data, existing_models)
        Model.save([x['__instance'] for x in base_data.values()])

        # Import Views
        for model_name, data in base_data.items():
            logger.debug('Importing views for model %s' % model_name)
            cls.import_views(model_name, data, base_data)
        Model.save([x['__instance'] for x in base_data.values()])

        # Finalize fields
        cls.finalize_fields(base_data)
        Model.save([x['__instance'] for x in base_data.values()])

    @classmethod
    def import_model(cls, model_name, data):
        pool = Pool()
        Model = pool.get('debug.model')
        MRO = pool.get('debug.model.mro')
        Method = pool.get('debug.model.method')
        MethodMRO = pool.get('debug.model.method.mro')
        new_model = Model()
        new_model.name = model_name
        new_model.string = data['string']

        mro_lines = []
        for order, mro_data in data['mro'].items():
            mro = MRO()
            mro.order = int(order.replace(' ', ''))
            mro.base_name = mro_data['base_name']
            mro.module = mro_data['module']
            if mro_data['override']:
                mro.kind = 'override'
            elif mro_data['initial']:
                mro.kind = 'initial'
            else:
                mro.kind = ''
            mro.path = mro_data['path']
            mro_lines.append(mro)
        new_model.mro = mro_lines

        methods = []
        for method_name, method_data in data['methods'].items():
            method = Method()
            method.name = method_name

            mro_lines = []
            for order, mro_data in method_data['mro'].items():
                mro = MethodMRO()
                mro.order = int(order.replace(' ', ''))
                mro.base_name = mro_data['base_name']
                mro.module = mro_data['module']
                if mro_data['override']:
                    mro.kind = 'override'
                elif mro_data['initial']:
                    mro.kind = 'initial'
                else:
                    mro.kind = ''
                mro.path = mro_data['path']
                mro_lines.append(mro)
            method.mro = mro_lines
            methods.append(method)
        new_model.methods = methods
        data['__instance'] = new_model

    @classmethod
    def import_fields(cls, model_name, data, full_data, existing_models):
        model = full_data[model_name]['__instance']
        methods = {x.name: x for x in model.methods}

        Field = Pool().get('debug.model.field')
        fields = []
        for field_name, field_data in data['fields'].items():
            field = Field()
            field.name = field_name
            field.module = field_data['module']
            field.string = field_data['string']
            field.kind = field_data['kind']
            field.function = field_data['is_function']
            if field_data.get('target_model', None):
                if field_data['target_model'] in existing_models:
                    field.target_model = existing_models[
                        field_data['target_model']]
                else:
                    field.target_model = full_data[field_data['target_model']][
                        '__instance']
            field.default_method = methods.get(
                'default_%s' % field_name, None)
            field.on_change_method = methods.get(
                'on_change_%s' % field_name, None)
            field.on_change_with_method = methods.get(
                'on_change_with_%s' % field_name, None)
            field.order_method = methods.get(
                'order_%s' % field_name, None)
            field.selection_method = methods.get(
                field_data.get('selection_method', None), None)
            field.getter = methods.get(
                field_data.get('getter', None), None)
            field.setter = methods.get(
                field_data.get('setter', None), None)
            field.searcher = methods.get(
                field_data.get('searcher', None), None)
            if field_data.get('selection_values', None):
                field.selection_values = '\n'.join(
                    ['%s :%s' % (k, v)
                        for k, v in field_data['selection_values'].items()])
            field.domain = field_data.get('domain', '')
            field.invisible = field_data.get('state_invisible', '')
            field.required = 'True' if field_data['is_required'] else \
                field_data.get('state_required')
            field.readonly = 'True' if field_data['is_readonly'] else \
                field_data.get('state_readonly')
            fields.append(field)
        full_data[model_name]['__instance'].fields_ = fields

    @classmethod
    def import_views(cls, model_name, data, full_data):
        View = Pool().get('debug.model.view')
        model = full_data[model_name]['__instance']
        fields = {x.name: x for x in model.fields_}

        def import_view(view_data):
            view = View()
            view.module = view_data['module']
            view.name = view_data['name']
            view.functional_id = view_data['functional_id']
            view.kind = view_data['type'] or 'inherit'
            view.priority = view_data['priority']
            if view_data.get('field_childs', None):
                view.field_childs = fields[view_data['field_childs']]
            sub_views = []
            for order, sub_view in view_data.get('inherit', {}).items():
                sub_views.append(import_view(sub_view))
                sub_views[-1].order = int(order.replace(' ', ''))
            view.inherit = sub_views
            return view

        views = []
        for order, view_data in data['views'].items():
            views.append(import_view(view_data))
            views[-1].order = int(order.replace(' ', ''))
        full_data[model_name]['__instance'].views = views

    @classmethod
    def finalize_fields(cls, full_data):
        pool = Pool()
        Field = pool.get('debug.model.field')

        for model_instance in [x['__instance'] for x in full_data.values()]:
            Model = pool.get(model_instance.name)
            cur_data = full_data[model_instance.name]
            fields = {x.name: Field(x.id)
                for x in cur_data['__instance'].fields_}
            for field in model_instance.fields_:
                if field.on_change_method:
                    on_change_fields = []
                    for fname in getattr(getattr(Model,
                                field.on_change_method.name), 'depends', []):
                        if fname.startswith('_parent_'):
                            continue
                        fname = fname.split('.')[0]
                        if fname not in fields:
                            logging.getLogger().warning(
                                'Cannot find field %s on %s for on_change_%s' %
                                (fname, model_instance.name, field.name))
                        else:
                            on_change_fields.append(fields[fname])
                    field.on_change_fields = on_change_fields
                if field.on_change_with_method:
                    on_change_with_fields = []
                    for fname in getattr(getattr(Model,
                                field.on_change_with_method.name),
                            'depends', []):
                        if fname.startswith('_parent_'):
                            continue
                        fname = fname.split('.')[0]
                        if fname not in fields:
                            logging.getLogger().warning('Cannot find field %s '
                                'on %s for on_change_with_%s' % (
                                    fname, model_instance.name, field.name))
                        else:
                            on_change_with_fields.append(fields[fname])
                    field.on_change_with_fields = on_change_with_fields
            model_instance.fields_ = list(model_instance.fields_)


class DebugMROInstance(ModelSQL, ModelView):
    'Model MRO for debug'

    __name__ = 'debug.model.mro'

    model = fields.Many2One('debug.model', 'model', select=True, required=True,
        ondelete='CASCADE')
    order = fields.Integer('Order', readonly=True)
    base_name = fields.Char('Base Name', readonly=True)
    module = fields.Char('Module', readonly=True)
    kind = fields.Selection([('', ''), ('initial', 'Initial'),
            ('override', 'Override')], 'Kind', readonly=True)
    path = fields.Char('Path', readonly=True)

    @classmethod
    def __setup__(cls):
        super(DebugMROInstance, cls).__setup__()
        cls._buttons.update({'open_file': {}})

    @classmethod
    @ModelView.button
    def open_file(cls, mros):
        assert len(mros) == 1
        file_path = mros[0].path.split('.')
        file_path[-1] += '.py'
        open_path(file_path, [('^class ' + mros[0].base_name,
                    '^ *__name__ = .%s.' % mros[0].model.name)])


class DebugFieldInstance(ModelSQL, ModelView):
    'Model field for debug'

    __name__ = 'debug.model.field'

    model = fields.Many2One('debug.model', 'model', select=True, required=True,
        ondelete='CASCADE')
    name = fields.Char('Name', select=True, readonly=True)
    module = fields.Char('Module', readonly=True)
    string = fields.Char('String', readonly=True)
    kind = fields.Char('Kind', readonly=True)
    function = fields.Boolean('Function', readonly=True)
    target_model = fields.Many2One('debug.model', 'Target Model',
        ondelete='SET NULL', states={'invisible': ~Eval('target_model')},
        depends=['target_model'], readonly=True, select=True)
    selection_method = fields.Many2One('debug.model.method',
        'Selection Method', ondelete='SET NULL',
        states={'invisible': ~Eval('selection_method')},
        depends=['selection_method'], readonly=True, select=True)
    selection_values = fields.Text('Selection Values', states={'invisible':
            ~Eval('selection_values')}, depends=['selection_values'],
        readonly=True)
    domain = fields.Text('Domain', readonly=True)
    invisible = fields.Text('Invisible', readonly=True)
    readonly = fields.Text('Readonly', readonly=True)
    required = fields.Text('Required', readonly=True)
    default_method = fields.Many2One('debug.model.method', 'Default Method',
        ondelete='SET NULL', readonly=True, select=True)
    on_change_method = fields.Many2One('debug.model.method',
        'On Change Method', ondelete='SET NULL', readonly=True, select=True)
    on_change_with_method = fields.Many2One('debug.model.method',
        'On Change With Method', ondelete='SET NULL', readonly=True,
        select=True)
    order_method = fields.Many2One('debug.model.method', 'Order Method',
        ondelete='SET NULL', readonly=True, select=True)
    getter = fields.Many2One('debug.model.method', 'Getter',
        ondelete='SET NULL', states={'invisible': ~Eval('getter')},
        depends=['getter'], readonly=True, select=True)
    setter = fields.Many2One('debug.model.method', 'Setter',
        ondelete='SET NULL', states={'invisible': ~Eval('setter')},
        depends=['setter'], readonly=True, select=True)
    searcher = fields.Many2One('debug.model.method', 'Searcher',
        ondelete='SET NULL', states={'invisible': ~Eval('searcher')},
        depends=['searcher'], readonly=True, select=True)
    on_change_fields = fields.Many2Many('debug.model.field.on_change',
        'from_field', 'to_field', 'On Change Fields', readonly=True)
    on_change_with_fields = fields.Many2Many(
        'debug.model.field.on_change_with', 'from_field', 'to_field',
        'On Change With Fields', readonly=True)

    @classmethod
    def __setup__(cls):
        super(DebugFieldInstance, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))


class DebugMethodInstance(ModelSQL, ModelView):
    'Model method for debug'

    __name__ = 'debug.model.method'

    model = fields.Many2One('debug.model', 'name', select=True, required=True,
        ondelete='CASCADE')
    name = fields.Char('Name', select=True, readonly=True)
    mro = fields.One2Many('debug.model.method.mro', 'method', 'MRO',
        order=[('order', 'ASC')])
    initial_frame = fields.Function(
        fields.Many2One('debug.model.method.mro', 'Initial Frame'),
        'get_initial_frame')

    @classmethod
    def __setup__(cls):
        super(DebugMethodInstance, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls._buttons.update({'open_initial': {}})

    def get_initial_frame(self, name):
        return [x.id for x in self.mro if x.kind == 'initial'][0]

    @classmethod
    @ModelView.button_action('debug.act_open_initial')
    def open_initial(cls, models):
        pass


class DebugMethodMROInstance(ModelSQL, ModelView):
    'Method MRO for debug'

    __name__ = 'debug.model.method.mro'

    method = fields.Many2One('debug.model.method', 'method', select=True,
        required=True, ondelete='CASCADE')
    order = fields.Integer('Order', readonly=True)
    base_name = fields.Char('Base Name', readonly=True)
    module = fields.Char('Module', readonly=True)
    kind = fields.Selection([('', ''), ('initial', 'Initial'),
            ('override', 'Override')], 'Kind', readonly=True)
    path = fields.Char('Path', readonly=True)

    @classmethod
    def __setup__(cls):
        super(DebugMethodMROInstance, cls).__setup__()
        cls._buttons.update({'open_file': {}})

    @classmethod
    @ModelView.button
    def open_file(cls, mros):
        assert len(mros) == 1
        file_path = mros[0].path.split('.')
        file_path[-1] += '.py'
        open_path(file_path, [('^class ' + mros[0].base_name,
                    '^ *__name__ = .%s.' % mros[0].method.model.name),
                ('^ *def ' + mros[0].method.name + r'(\(|$)',)])


class DebugViewInstance(ModelSQL, ModelView):
    'Model view for debug'

    __name__ = 'debug.model.view'

    model = fields.Many2One('debug.model', 'model', select=True,
        ondelete='CASCADE')
    parent_view = fields.Many2One('debug.model.view', 'Parent View',
        select=True, ondelete='CASCADE', readonly=True)
    name = fields.Char('File Name', select=True, readonly=True)
    functional_id = fields.Char('Functional Id', readonly=True)
    module = fields.Char('Module', readonly=True)
    kind = fields.Selection([('form', 'Form'), ('tree', 'Tree'),
            ('board', 'Board'), ('inherit', 'Inherit'), ('graph', 'Graph'),
            ('calendar', 'Calendar')],
        'Kind', readonly=True)
    priority = fields.Integer('Priority', readonly=True)
    order = fields.Integer('Order', readonly=True)
    field_childs = fields.Many2One('debug.model.field', 'Fields Childs',
        ondelete='SET NULL', readonly=True, select=True)
    inherit = fields.One2Many('debug.model.view', 'parent_view', 'Inherit',
        order=[('order', 'ASC')], readonly=True)

    @classmethod
    def __setup__(cls):
        super(DebugViewInstance, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls._buttons.update({'open_file': {}})

    @classmethod
    @ModelView.button
    def open_file(cls, views):
        assert len(views) == 1
        open_path(['trytond', 'modules', views[0].module, 'view',
                views[0].name + '.xml'], [])


class DebugOnChangeRelation(ModelSQL, ModelView):
    'On Change Relation for debug'

    __name__ = 'debug.model.field.on_change'

    from_field = fields.Many2One('debug.model.field', 'From Field',
        required=True, select=True, ondelete='CASCADE')
    to_field = fields.Many2One('debug.model.field', 'From Field',
        required=True, select=True, ondelete='CASCADE')


class DebugOnChangeWithRelation(ModelSQL, ModelView):
    'On Change With Relation for debug'

    __name__ = 'debug.model.field.on_change_with'

    from_field = fields.Many2One('debug.model.field', 'From Field',
        required=True, select=True, ondelete='CASCADE')
    to_field = fields.Many2One('debug.model.field', 'From Field',
        required=True, select=True, ondelete='CASCADE')


class RefreshDebugData(Wizard):
    'Refresh Debug Data'

    __name__ = 'debug.refresh'

    start_state = 'refresh'
    refresh = StateTransition()

    def transition_refresh(self):
        with Transaction().set_user(0):
            Pool().get('debug.model').refresh(None)
        return 'end'


class OpenInitialFrame(Wizard):
    'Open Initial Frame'

    __name__ = 'debug.open_initial'

    start_state = 'open_frame'
    open_frame = StateTransition()

    def transition_open_frame(self):
        active_model = Transaction().context.get('active_model')
        assert active_model in ('debug.model', 'debug.model.method')
        Model = Pool().get(active_model)
        instance = Model(Transaction().context.get('active_id'))
        instance.initial_frame.open_file([instance.initial_frame])
        return 'end'

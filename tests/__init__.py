# This file is part of Coog. The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

try:
    from trytond.modules.debug.tests.test_debug import suite
except ImportError:
    from .test_debug import suite

__all__ = ['suite']

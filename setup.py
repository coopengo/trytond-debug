#!/usr/bin/env python
# This file is part of Coog.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from setuptools import setup
import re
import os
import io
try:
    from configparser import ConfigParser
except ImportError:
    from configparser import ConfigParser


def read(fname):
    return io.open(
        os.path.join(os.path.dirname(__file__), fname),
        'r', encoding='utf-8').read()


def get_require_version(name):
    if minor_version % 2:
        require = '%s >= %s.%s.dev0, < %s.%s'
    else:
        require = '%s >= %s.%s, < %s.%s'
    require %= (name, major_version, minor_version,
        major_version, minor_version + 1)
    return require

config = ConfigParser()
config.readfp(open('tryton.cfg'))
info = dict(config.items('tryton'))
for key in ('depends', 'extras_depend', 'xml'):
    if key in info:
        info[key] = info[key].strip().splitlines()
version = info.get('version', '0.0.1')
major_version, minor_version, _ = version.split('.', 2)
major_version = int(major_version)
minor_version = int(minor_version)
name = 'trytond_debug'

download_url = 'http://github.com/coopengo/trytond_debug/'
if minor_version % 2:
    version = '%s.%s.dev0' % (major_version, minor_version)
    download_url = 'git+http://github.com/coopengo/trytond_debug#egg=master'

requires = []
for dep in info.get('depends', []):
    if not re.match(r'(ir|res)(\W|$)', dep):
        requires.append(get_require_version('trytond_%s' % dep))
requires.append(get_require_version('trytond'))

tests_require = [get_require_version('proteus')]
dependency_links = []
if minor_version % 2:
    # Add development index for testing with proteus
    dependency_links.append('https://trydevpi.tryton.org/')

setup(name=name,
    version=version,
    description='Tryton module to help development',
    long_description=read('README'),
    author='Coopengo',
    author_email='dev@coopengo.com',
    url='http://www.coopengo.com/',
    download_url=download_url,
    keywords='tryton debug development',
    package_dir={'trytond.modules.debug': '.'},
    packages=[
        'trytond.modules.debug',
        ],
    package_data={
        'trytond.modules.debug': (info.get('xml', [])
            + ['tryton.cfg', 'view/*.xml', 'locale/*.po']),
        },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Plugins',
        'Framework :: Tryton',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Natural Language :: English',
        'Natural Language :: French',
        'Operating System :: Linux',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        ],
    license='GPL-3',
    install_requires=requires,
    dependency_links=dependency_links,
    zip_safe=False,
    entry_points="""
    [trytond.modules]
    debug = trytond.modules.debug
    """,
    test_loader='trytond.test_loader:Loader',
    tests_require=tests_require,
    use_2to3=True,
    )

# -*- coding: utf-8 -*-
{
    'name': "mrp_production_schedule_custom",
    'version': "1",
    'author': "Develoop Software",
    'category': "CRM",
    'summary': "Modificaciones en el programa maestro de produccion",
    'website': "https://www.develoop.net/",
    'description': """
        - Modificaciones en el programa maestro de produccion
    """,
    'depends': ['base','mrp_mps'],
    'data': [
        'views/assets.xml',
        'views/mrp_production_schedule_custom.xml',
    ],
    'qweb': [
        'static/src/xml/qweb.xml',
    ],
    'images': ['static/description/icon.png'],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}

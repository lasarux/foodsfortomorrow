# -*- coding: utf-8 -*-

import logging
import calendar
import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, exceptions, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class ForecastSales(models.Model):
    
    _name = 'x.forecast.sale'
    _description = "forecast sale"
    _order = 'x_mes desc, x_producto asc, id desc'

    x_cajas = fields.Integer(string="Cajas")
    x_comercial = fields.Many2one('res.users', string="Comercial", readonly=True)
    x_contacto = fields.Many2one('res.partner', string="Contacto", readonly=True)
    x_cuenta_analitica = fields.Many2one('account.analytic.account', string="Cuenta analítica", readonly=True)
    x_kg = fields.Float(string="Kg")
    x_mes = fields.Date(string="Mes", readonly=True)
    x_mes_format = fields.Char(string="Mes/Año", readonly=True, required=True)
    x_producto = fields.Many2one('product.product', string="Producto", readonly=True, required=True)
    x_rotacion = fields.Float(string="Rotación", readonly=True)
    x_tipo = fields.Selection([
        ('cliente','Cliente'),
        ('canal','Canal')
        ], string="Tipo", readonly=True)
    x_unidades = fields.Integer(string="Unidades")
    x_locked = fields.Boolean("Bloqueado", default=False)
    
    x_forecast_catalog_id = fields.Many2one('x.forecast.catalog', required=True, ondelete='cascade', index=True, copy=False)

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        # if(self._context.get('is_tree',False)):
        args += [('x_comercial', '=', self.env.user.id)]
        return super(ForecastSales, self)._search(args, offset=offset, limit=limit, order=order, count=count, access_rights_uid=access_rights_uid)


    def onchange(self, values, field_name, field_onchange):
        # OVERRIDE
        # As the dynamic lines in this model are quite complex, we need to ensure some computations are done exactly
        # at the beginning / at the end of the onchange mechanism. So, the onchange recursivity is disabled.
        return super(ForecastSales, self.with_context(recursive_onchanges=False)).onchange(values, field_name, field_onchange)

    @api.onchange('x_unidades')
    def x_unidades_change(self):
        self.x_cajas = self.x_unidades / (self.x_producto.x_studio_unidades_por_caja if self.x_producto.x_studio_unidades_por_caja > 0 else 1)
        self.x_kg = self.x_cajas * self.x_producto.x_studio_peso_umb_gr / 1000
        
        resto = self.x_unidades % (self.x_producto.x_studio_unidades_por_caja if self.x_producto.x_studio_unidades_por_caja > 0 else 1)
        #recursive_onchanges
        if(resto > 0):
            return {
                'warning':{
                    'title': "Información: División inexacta",
                    'message': "La división entre " + str(self.x_unidades) + " (unidades) y " + str(self.x_producto.x_studio_unidades_por_caja) + " (unidades por caja) genera un resto de " + str(resto)
                }
            }
    
    @api.onchange('x_cajas')
    def x_cajas_change(self):
        self.x_unidades = self.x_cajas * self.x_producto.x_studio_unidades_por_caja
        self.x_kg = self.x_cajas * self.x_producto.x_studio_peso_umb_gr / 1000
        

    @api.onchange('x_kg')
    def x_kg_change(self):
        self.x_cajas = self.x_kg * 1000 / (self.x_producto.x_studio_peso_umb_gr if self.x_producto.x_studio_peso_umb_gr > 0 else 1)
        self.x_unidades = self.x_cajas * self.x_producto.x_studio_unidades_por_caja
        resto = self.x_kg * 1000 % (self.x_producto.x_studio_peso_umb_gr if self.x_producto.x_studio_peso_umb_gr > 0 else 1)
        if(resto > 0):
            return {
                'warning':{
                    'title': "Información: División inexacta",
                    'message': "La división entre " + str(self.x_kg * 1000) + " (gramos) y " + str(self.x_producto.x_studio_peso_umb_gr) + " (peso neto UMB gr) genera un resto de " + str(resto)
                }
            }

    def forecast_change_field_locked(self):
        if(datetime.date.today().day > 25):
            forecast = self.env['x.forecast.sale'].search([('x_mes','<=',datetime.date.today()),('x_locked','!=',True)])
            for record in forecast:
                record.x_locked = True
            

class ForecastCatalog(models.Model):

    _name = 'x.forecast.catalog'
    _description = "forecast catalog"
    _order = 'x_producto asc, x_contacto asc, id asc'


    def _get_domain_x_comercial(self):
        return [('id','=',self.env.user.id)]

    x_comercial = fields.Many2one('res.users', string="Comercial", required=True, 
        default=lambda self: self.env.user.id, domain=_get_domain_x_comercial)
    x_contacto = fields.Many2one('res.partner', string="Contacto", domain="[('parent_id', '=', False)]")
    x_cuenta_analitica = fields.Many2one('account.analytic.account', string="Cuenta analítica")
    x_producto = fields.Many2one('product.product', string="Producto", required=True)
    x_tipo = fields.Selection([
        ('cliente','Cliente'),
        ('canal','Canal')
        ], string="Tipo", required=True)

    x_forecast_sales = fields.One2many('x.forecast.sale', 'x_forecast_catalog_id', copy=True, auto_join=True)
    # x_order_line = fields.One2many('sale.order.line', 'order_id', string='Order Lines', states={'cancel': [('readonly', True)], 'done': [('readonly', True)]}, copy=True, auto_join=True)
    

    # order_id = fields.Many2one('sale.order', string='Order Reference', required=True, ondelete='cascade', index=True, copy=False)
    # order_line = fields.One2many('sale.order.line', 'order_id', string='Order Lines', states={'cancel': [('readonly', True)], 'done': [('readonly', True)]}, copy=True, auto_join=True)

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        # if(self._context.get('is_tree',False)):
        args += [('x_comercial', '=', self.env.user.id)]
        return super(ForecastCatalog, self)._search(args, offset=offset, limit=limit, order=order, count=count, access_rights_uid=access_rights_uid)

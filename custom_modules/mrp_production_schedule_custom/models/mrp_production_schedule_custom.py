# -*- coding: utf-8 -*-

import math
from odoo import api, fields, models, exceptions, SUPERUSER_ID, _
from odoo.exceptions import AccessError, UserError, ValidationError


class mrp_production_schedule_custom_0(models.Model):
    
    _inherit = 'mrp.production.schedule'

    @api.model
    def get_mps_view_state(self, domain=False):
        """ Return the global information about MPS and a list of production
        schedules values with the domain.

        :param domain: domain for mrp.production.schedule
        :return: values used by the client action in order to render the MPS.
            - dates: list of period name
            - production_schedule_ids: list of production schedules values
            - manufacturing_period: list of periods (days, months or years)
            - company_id: user current company
            - groups: company settings that hide/display different rows
        :rtype: dict
        """
        productions_schedules = self.env['mrp.production.schedule'].search(domain or [])
        productions_schedules_states = productions_schedules.get_production_schedule_view_state()
        
        ###############################################
        
        for production in productions_schedules_states:
            if(production.get('product_id') and production.get('forecast_ids')):
                product_template =  self.env['product.template'].search([('id','=',production['product_id'][0])], limit=1)
                if(product_template.seller_ids):
                    time_days = product_template.seller_ids[0].x_studio_transit_time + product_template.seller_ids[0].delay
                    moq = product_template.seller_ids[0].min_qty
                    quantity_week = math.ceil(time_days/7)
                    if(quantity_week > 0):
                        forecast_ids = production.get('forecast_ids')
                        for forecast in range(len(forecast_ids)):
                            if((forecast + quantity_week) <= len(forecast_ids)):
                                if(forecast_ids[forecast + quantity_week]['safety_stock_qty'] < moq):
                                    forecast_ids[forecast + quantity_week]['state'] = 'launched'
                                    break
                            else:
                                break
                    

        ###############################################

        company_groups = self.env.company.read([
            'mrp_mps_show_starting_inventory',
            'mrp_mps_show_demand_forecast',
            'mrp_mps_show_indirect_demand',
            'mrp_mps_show_actual_demand',
            'mrp_mps_show_to_replenish',
            'mrp_mps_show_actual_replenishment',
            'mrp_mps_show_safety_stock',
            'mrp_mps_show_available_to_promise',
        ])
        return {
            'dates': self.env.company._date_range_to_str(),
            'production_schedule_ids': productions_schedules_states,
            'manufacturing_period': self.env.company.manufacturing_period,
            'company_id': self.env.company.id,
            'groups': company_groups,
        }